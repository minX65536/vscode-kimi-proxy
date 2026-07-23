# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 BESTNYPRO INC
# Licensed under the Business Source License 1.1 — see LICENSE file

"""SSE chunk and full-response transformation.

In-place chunk mutation (preserves every upstream field, including
tool_calls ids/index/type), think markers merged into the same delta,
[DONE] and usage-only chunks forwarded verbatim.
"""

from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator

from .thinking import ThinkMarkers, ThinkingState


def _make_chunk(
    template: dict[str, Any],
    idx: int,
    delta: dict[str, Any],
    finish_reason: str | None = None,
) -> dict[str, Any]:
    """Assemble an SSE chunk.

    ``template`` is a dict with upstream ``id``/``created``/``model`` so the
    synthetic chunk inherits the stream identity instead of getting new ones.
    """
    return {
        "id": template.get("id") or "chatcmpl-proxy",
        "object": "chat.completion.chunk",
        "created": template.get("created") or int(time.time()),
        "model": template.get("model") or "kimi-k3",
        "choices": [
            {
                "index": idx,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }


def sse_line(data: dict[str, Any]) -> bytes:
    """Serialize a dict to an SSE line."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")


# ---------------------------------------------------------------------------
#  reasoning_content → visible think-blocks transformation
# ---------------------------------------------------------------------------

class ThinkTransformer:
    """In-place mutation, [DONE]/usage forwarded."""

    def __init__(self, model: str) -> None:
        self.model = model
        self.state = ThinkingState()
        self.template: dict[str, Any] = {}  # id/created/model from the stream

    # -- markers ------------------------------------------------------
    def _open_marker(self) -> str:
        return ""

    def _close_marker(self) -> str:
        return ""

    def _transform_chunk(self, chunk: dict[str, Any]) -> list[dict[str, Any]]:
        """Return chunks to emit (base: passthrough). May add synthetics."""
        return [chunk]

    # -- main entry ----------------------------------------------------
    def transform_line(self, line: bytes) -> list[bytes]:
        """Process one SSE line. Returns lines to forward to the client."""
        text = line.decode("utf-8", errors="replace")
        stripped = text.strip()
        if not stripped.startswith("data:"):
            return [line]

        payload = stripped[5:].strip()
        if payload == "[DONE]":
            # [DONE] is forwarded to the client as-is.
            return [b"data: [DONE]"]
        if not payload:
            return [line]

        try:
            chunk = json.loads(payload)
        except json.JSONDecodeError:
            return [line]

        if not isinstance(chunk, dict):
            return [line]

        # Keep stream identity for potential synthetic chunks
        self.template = {
            k: chunk.get(k) for k in ("id", "created", "model") if chunk.get(k)
        }

        if chunk.get("choices"):
            return [sse_line(c) for c in self._transform_chunk(chunk)]

        # usage-only / error chunks — forward as-is
        return [sse_line(chunk)]


class InlineThinkTransformer(ThinkTransformer):
    """think_mode=inline: reasoning → <think>...</think> merged into delta."""

    def __init__(self, model: str) -> None:
        super().__init__(model)
        self.markers = ThinkMarkers.for_mode("inline")

    def _open_marker(self) -> str:
        return self.markers.open

    def _close_marker(self) -> str:
        return self.markers.close

    def _transform_chunk(self, chunk: dict[str, Any]) -> list[dict[str, Any]]:
        extra: list[dict[str, Any]] = []
        for choice in chunk.get("choices") or []:
            idx = choice.get("index", 0)
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                continue

            reasoning = delta.get("reasoning_content")
            if reasoning:
                prefix = self._open_marker() if idx not in self.state.open else ""
                self.state.open.add(idx)
                new_delta = {k: v for k, v in delta.items() if k != "reasoning_content"}
                new_delta["content"] = prefix + reasoning + (new_delta.get("content") or "")
                choice["delta"] = new_delta
            elif idx in self.state.open and (
                delta.get("content") or delta.get("tool_calls") or choice.get("finish_reason")
            ):
                self.state.open.discard(idx)
                if delta.get("content") is not None:
                    delta["content"] = self._close_marker() + (delta.get("content") or "")
                else:
                    # tool_calls without content — close think via a separate
                    # synthetic chunk so the tool_calls delta stays untouched.
                    extra.append(
                        _make_chunk(self.template, idx, {"content": self._close_marker()})
                    )
        return extra + [chunk]


class DetailsThinkTransformer(InlineThinkTransformer):
    """think_mode=details: reasoning → <details> block."""

    def __init__(self, model: str) -> None:
        super().__init__(model)
        self.markers = ThinkMarkers.for_mode("details")


class NativeThinkTransformer(ThinkTransformer):
    """think_mode=native: reasoning_content stays as-is (no transformation)."""


class DropThinkTransformer(ThinkTransformer):
    """think_mode=drop: reasoning_content is removed."""

    def _transform_chunk(self, chunk: dict[str, Any]) -> list[dict[str, Any]]:
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta")
            if isinstance(delta, dict) and delta.get("reasoning_content"):
                choice["delta"] = {
                    k: v for k, v in delta.items() if k != "reasoning_content"
                }
        return [chunk]


# ---------------------------------------------------------------------------
#  Factory
# ---------------------------------------------------------------------------

_TRANSFORMERS: dict[str, type[ThinkTransformer]] = {
    "inline": InlineThinkTransformer,
    "details": DetailsThinkTransformer,
    "native": NativeThinkTransformer,
    "drop": DropThinkTransformer,
}


def create_transformer(mode: str, model: str) -> ThinkTransformer:
    """Create a transformer by mode name."""
    cls = _TRANSFORMERS.get(mode, InlineThinkTransformer)
    return cls(model)


# ---------------------------------------------------------------------------
#  Full (non-stream) response transformation
# ---------------------------------------------------------------------------

def transform_full_response(body: dict[str, Any], mode: str, model: str) -> dict[str, Any]:
    """Transform a full JSON response (non-SSE)."""
    if mode == "native":
        return body

    markers = ThinkMarkers.for_mode(mode)
    for choice in body.get("choices") or []:
        msg = choice.get("message")
        if isinstance(msg, dict) and msg.get("reasoning_content"):
            reasoning = msg.pop("reasoning_content")
            content = msg.get("content") or ""
            if mode == "drop":
                msg["content"] = content
            else:
                msg["content"] = markers.open + reasoning + markers.close + content

    return body


def full_response_to_sse(body: dict[str, Any], model: str) -> list[bytes]:
    """Convert a full JSON response to an SSE stream.

    The caller is expected to have run transform_full_response() already.
    """
    choices = body.get("choices")
    if not choices:
        return []

    template = {k: body.get(k) for k in ("id", "created", "model") if body.get(k)}
    msg = dict(choices[0].get("message") or {})
    msg.pop("reasoning_content", None)  # already wrapped by transform_full_response
    content = msg.get("content") or ""

    delta: dict[str, Any] = {"role": "assistant", "content": content}
    if msg.get("tool_calls"):
        delta["tool_calls"] = msg["tool_calls"]
    finish = choices[0].get("finish_reason") or "stop"

    return [
        sse_line(_make_chunk(template, 0, delta)),
        sse_line(_make_chunk(template, 0, {}, finish)),
        b"data: [DONE]\n\n",
    ]
