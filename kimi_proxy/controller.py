# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 BESTNYPRO INC
# Licensed under the Business Source License 1.1 — see LICENSE file

"""Request orchestration through the proxy pipeline."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, AsyncIterator

import aiohttp
from aiohttp import web

_DEBUG_LOG = Path(__file__).resolve().parent.parent / "kimi-proxy-debug.jsonl"


def _sanitize(obj: Any) -> Any:
    """Recursively redact API keys from a dict/list structure."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(item) for item in obj]
    if isinstance(obj, str) and obj.startswith("Bearer "):
        token = obj[7:]
        return f"Bearer {token[:6]}<truncated>" if len(token) > 6 else "Bearer <redacted>"
    return obj


def _debug_log(direction: str, data: Any) -> None:
    """Append a debug record to the debug JSONL log."""
    record = {"t": time.strftime("%H:%M:%S"), "dir": direction, "data": _sanitize(data)}
    try:
        with open(_DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass

from .config import ProxyConfig
from .instructions import inject_instructions
from .logging_svc import MetricsLogger, RequestSummary, UsageLogger, print_summary
from .thinking import strip_think
from .transform import (
    create_transformer,
    full_response_to_sse,
    sse_line,
    transform_full_response,
)
from .upstream import UpstreamClient, UpstreamError


def _apply_model_alias(body: dict[str, Any], aliases: dict[str, str]) -> dict[str, Any]:
    """Replace model name via alias map."""
    model = body.get("model", "")
    if model in aliases:
        body = {**body, "model": aliases[model]}
    return body


def _enforce_context_budget(
    body: dict[str, Any],
    max_tokens: int,
    keep_last: int,
) -> tuple[dict[str, Any], int]:
    """Trim message history if the context budget is exceeded.

    Returns (body, number_of_messages_removed).
    """
    if max_tokens <= 0:
        return body, 0

    messages = body.get("messages", [])
    if len(messages) <= keep_last:
        return body, 0

    # Rough estimate: ~3 chars per token
    char_budget = max_tokens * 3

    # Always preserve system messages
    system_msgs = [m for m in messages if m.get("role") == "system"]
    non_system = [m for m in messages if m.get("role") != "system"]

    # Keep only the last keep_last messages
    kept = non_system[-keep_last:] if len(non_system) > keep_last else non_system

    # Check character budget
    def _msg_chars(m: dict[str, Any]) -> int:
        c = m.get("content", "")
        if isinstance(c, str):
            return len(c)
        if isinstance(c, list):
            return sum(len(p.get("text", "")) for p in c if isinstance(p, dict))
        return 0

    removed_count = len(messages) - len(system_msgs) - len(kept)
    total = sum(_msg_chars(m) for m in system_msgs + kept)
    while kept and total > char_budget:
        removed = kept.pop(0)
        removed_count += 1
        total -= _msg_chars(removed)

    new_messages = system_msgs + kept
    return {**body, "messages": new_messages}, removed_count


class ProxyController:
    """Controller: handles HTTP requests, coordinates components."""

    def __init__(
        self,
        cfg: ProxyConfig,
        session: aiohttp.ClientSession,
        usage_logger: UsageLogger,
        metrics_logger: MetricsLogger,
    ) -> None:
        self._cfg = cfg
        self._upstream = UpstreamClient(cfg, session)
        self._usage = usage_logger
        self._metrics = metrics_logger

    async def handle_models(self, request: web.Request) -> web.Response:
        """GET /v1/models — proxy the model list."""
        try:
            async with aiohttp.ClientSession() as s:
                headers: dict[str, str] = {}
                if self._cfg.api_key:
                    headers["Authorization"] = f"Bearer {self._cfg.api_key}"
                async with s.get(
                    f"{self._cfg.upstream_base}/v1/models",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    body = await resp.read()
                    return web.Response(
                        body=body,
                        status=resp.status,
                        content_type="application/json",
                    )
        except Exception as exc:
            return web.json_response(
                {"error": {"message": str(exc), "type": "proxy_error"}},
                status=502,
            )

    async def handle_chat_completions(self, request: web.Request) -> web.StreamResponse:
        """POST /v1/chat/completions — main handler."""
        t_start = time.monotonic()
        summary = RequestSummary(think_mode=self._cfg.think_mode, t_start=t_start)

        # --- Read request body ---
        try:
            body: dict[str, Any] = await request.json()
        except Exception:
            return web.json_response(
                {"error": {"message": "Invalid JSON", "type": "invalid_request_error"}},
                status=400,
            )

        _debug_log("request_in", {"model": body.get("model"), "stream": body.get("stream"), "msg_count": len(body.get("messages", [])), "headers": dict(request.headers)})

        # --- Request transformation pipeline (collecting summary facts) ---
        original_model = body.get("model", "unknown")
        summary.msg_count = len(body.get("messages", []))

        body = _apply_model_alias(body, self._cfg.model_aliases)
        if body.get("model") != original_model:
            summary.alias_from = original_model

        summary.forced_params = dict(self._cfg.force_params)
        body = self._inject_force_params(body)

        summary.instructions = "custom" if self._cfg.custom_instructions else "agent"
        body = self._inject_instructions(body)

        body, stripped = self._strip_think_history(body)
        summary.stripped_think = stripped

        body, trimmed = _enforce_context_budget(
            body,
            self._cfg.context.max_tokens,
            self._cfg.context.keep_last,
        )
        summary.trimmed_msgs = trimmed

        model = body.get("model", "unknown")
        is_stream = body.get("stream", False)
        messages = body.get("messages", [])

        summary.model = model
        summary.stream = is_stream
        summary.messages = messages

        # --- Send upstream ---
        _debug_log("upstream_request", {"model": model, "stream": is_stream, "url": self._cfg.upstream_url})
        try:
            if is_stream:
                return await self._stream_response(request, body, model, messages, t_start, summary)
            else:
                return await self._handle_json(body, model, messages, t_start, summary)
        except UpstreamError as exc:
            _debug_log("upstream_error", {"status": exc.status, "body": exc.body[:500]})
            summary.status = exc.status or 502
            summary.finish()
            print_summary(summary, self._cfg.console_enabled)
            return web.json_response(
                {
                    "error": {
                        "message": f"Upstream error: {exc.status}",
                        "type": "upstream_error",
                        "body": exc.body[:500],
                    }
                },
                status=exc.status if exc.status >= 400 else 502,
            )

    # ------------------------------------------------------------------
    #  Pipeline steps (High Cohesion)
    # ------------------------------------------------------------------

    def _inject_force_params(self, body: dict[str, Any]) -> dict[str, Any]:
        """Force-set parameters from config."""
        for k, v in self._cfg.force_params.items():
            body[k] = v
        return body

    def _inject_instructions(self, body: dict[str, Any]) -> dict[str, Any]:
        """Inject custom_instructions + AGENT_INSTRUCTION."""
        messages = body.get("messages", [])
        new_messages = inject_instructions(messages, self._cfg.custom_instructions)
        return {**body, "messages": new_messages}

    def _strip_think_history(self, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Strip think-blocks from message history. Returns (body, count_cleaned)."""
        if not self._cfg.strip_think_from_history:
            return body, 0

        messages = body.get("messages", [])
        new_messages = []
        cleaned = 0
        for msg in messages:
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                if isinstance(content, str) and ("<think>" in content or "<details>" in content):
                    msg = {**msg, "content": strip_think(content)}
                    cleaned += 1
            new_messages.append(msg)
        return {**body, "messages": new_messages}, cleaned

    # ------------------------------------------------------------------
    #  Stream handler
    # ------------------------------------------------------------------

    async def _stream_response(
        self,
        request: web.Request,
        body: dict[str, Any],
        model: str,
        messages: list[dict[str, Any]],
        t_start: float,
        summary: RequestSummary,
    ) -> web.StreamResponse:
        """Streaming response: read upstream SSE, transform, send to client."""
        resp, attempts = await self._upstream.post_stream(body)
        summary.attempts = attempts
        summary.retried = attempts > 1

        stream = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
        await stream.prepare(request)

        transformer = create_transformer(self._cfg.think_mode, model)
        ttft: float | None = None
        usage_data: dict[str, Any] | None = None
        chunk_count = 0

        try:
            async for raw_line in resp.content:
                if ttft is None:
                    ttft = (time.monotonic() - t_start) * 1000

                line = raw_line.strip()
                if not line:
                    continue

                # Transform each SSE line
                raw_text = line if isinstance(line, str) else line.decode("utf-8", errors="replace")
                _debug_log("sse_upstream", raw_text[:300])
                out_lines = transformer.transform_line(line if isinstance(line, bytes) else line.encode())
                for out_line in out_lines:
                    chunk_count += 1
                    text = out_line.decode("utf-8", errors="replace")
                    _debug_log("sse_client", text[:300])
                    # Intercept usage data
                    if text.startswith("data: ") and '"usage"' in text:
                        try:
                            payload = json.loads(text[6:].strip())
                            if "usage" in payload:
                                usage_data = payload["usage"]
                        except (json.JSONDecodeError, KeyError):
                            pass

                    await stream.write(out_line)

                # If this is [DONE]
                if line == b"data: [DONE]" or line == "data: [DONE]":
                    break

        except (ConnectionResetError, aiohttp.ClientError, asyncio.CancelledError):
            summary.status = "client disconnected"
        finally:
            resp.close()

        _debug_log("stream_done", {"chunks_sent": chunk_count, "ttft_ms": ttft, "usage": usage_data})

        total_ms = (time.monotonic() - t_start) * 1000

        # Logging + pretty console summary
        summary.ttft_ms = ttft
        summary.usage = usage_data
        summary.finish()
        print_summary(summary, self._cfg.console_enabled)

        self._usage.log(model, usage_data, ttft, total_ms, attempts, messages)
        self._metrics.log(model, ttft, total_ms, 200, attempts)

        return stream

    # ------------------------------------------------------------------
    #  JSON (non-stream) handler
    # ------------------------------------------------------------------

    async def _handle_json(
        self,
        body: dict[str, Any],
        model: str,
        messages: list[dict[str, Any]],
        t_start: float,
        summary: RequestSummary,
    ) -> web.Response:
        """Handle non-stream request."""
        result = await self._upstream.post_json(body)
        total_ms = (time.monotonic() - t_start) * 1000

        _debug_log("upstream_response", {"choices": len(result.get("choices", [])), "has_content": bool(result.get("choices", [{}])[0].get("message", {}).get("content")), "usage": result.get("usage")})

        # Transform reasoning_content
        result = transform_full_response(result, self._cfg.think_mode, model)

        _debug_log("client_response", {"choices": len(result.get("choices", []))})

        # Logging + pretty console summary
        usage_data = result.get("usage")
        summary.usage = usage_data
        summary.finish()
        print_summary(summary, self._cfg.console_enabled)

        self._usage.log(model, usage_data, None, total_ms, 1, messages)
        self._metrics.log(model, None, total_ms, 200, 1)

        return web.json_response(result)
