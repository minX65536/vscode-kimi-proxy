# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 BESTNYPRO INC
# Licensed under the Business Source License 1.1 — see LICENSE file

"""SSE chunk and full-response transformation.

Each ThinkTransformer is a strategy for a specific think_mode.
"""

from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator

from .thinking import ThinkMarkers, ThinkingState


def _make_chunk(
    chunk_id: str,
    model: str,
    delta: dict[str, Any],
    finish_reason: str | None = None,
) -> dict[str, Any]:
    """Create an SSE chunk in OpenAI format."""
    return {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
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
    """Base class for reasoning transformers."""

    def __init__(self, model: str) -> None:
        self.model = model
        self.state = ThinkingState()

    def transform_line(self, line: bytes) -> list[bytes]:
        """Process a single SSE line. Returns list of lines to send."""
        raise NotImplementedError

    def flush(self, chunk_id: str) -> list[bytes]:
        """Finalization (close an unclosed think-block)."""
        if self.state.in_think:
            self.state.in_think = False
            chunk = _make_chunk(chunk_id, self.model, {"content": self._close_marker()})
            return [sse_line(chunk)]
        return []

    def _open_marker(self) -> str:
        raise NotImplementedError

    def _close_marker(self) -> str:
        raise NotImplementedError


class InlineThinkTransformer(ThinkTransformer):
    """think_mode=inline: reasoning → <think>...</think> in content."""

    def __init__(self, model: str) -> None:
        super().__init__(model)
        self.markers = ThinkMarkers.for_mode("inline")

    def _open_marker(self) -> str:
        return self.markers.open

    def _close_marker(self) -> str:
        return self.markers.close

    def transform_line(self, line: bytes) -> list[bytes]:
        text = line.decode("utf-8", errors="replace").strip()
        if not text.startswith("data: "):
            return [line]

        payload = text[6:]
        if payload == "[DONE]":
            out: list[bytes] = []
            out.extend(self.flush("done"))
            out.append(b"data: [DONE]\n\n")
            return out

        try:
            chunk = json.loads(payload)
        except json.JSONDecodeError:
            return [line]

        chunk_id = chunk.get("id", "unknown")
        choices = chunk.get("choices", [])
        if not choices:
            return [line]

        delta = choices[0].get("delta", {})
        reasoning = delta.get("reasoning_content", "")
        content = delta.get("content", "")

        out: list[bytes] = []

        # Open think-block on first reasoning token
        if reasoning and not self.state.in_think:
            self.state.in_think = True
            open_chunk = _make_chunk(chunk_id, self.model, {"content": self._open_marker()})
            out.append(sse_line(open_chunk))

        # Proxy reasoning as content inside think-block
        if reasoning:
            rc_chunk = _make_chunk(chunk_id, self.model, {"content": reasoning})
            out.append(sse_line(rc_chunk))

        # Close think-block when regular content appears
        if content and self.state.in_think:
            self.state.in_think = False
            close_chunk = _make_chunk(chunk_id, self.model, {"content": self._close_marker()})
            out.append(sse_line(close_chunk))

        # Proxy content (strip reasoning_content from delta)
        if content or delta.get("role") or choices[0].get("finish_reason"):
            clean_delta = {k: v for k, v in delta.items() if k != "reasoning_content"}
            clean_chunk = _make_chunk(
                chunk_id,
                self.model,
                clean_delta,
                finish_reason=choices[0].get("finish_reason"),
            )
            # Preserve usage if present
            if "usage" in chunk:
                clean_chunk["usage"] = chunk["usage"]
            out.append(sse_line(clean_chunk))

        return out if out else [line]


class DetailsThinkTransformer(InlineThinkTransformer):
    """think_mode=details: reasoning → <details> block."""

    def __init__(self, model: str) -> None:
        super().__init__(model)
        self.markers = ThinkMarkers.for_mode("details")


class NativeThinkTransformer(ThinkTransformer):
    """think_mode=native: reasoning_content stays as-is (no transformation)."""

    def _open_marker(self) -> str:
        return ""

    def _close_marker(self) -> str:
        return ""

    def transform_line(self, line: bytes) -> list[bytes]:
        return [line]


class DropThinkTransformer(ThinkTransformer):
    """think_mode=drop: reasoning_content is removed."""

    def _open_marker(self) -> str:
        return ""

    def _close_marker(self) -> str:
        return ""

    def transform_line(self, line: bytes) -> list[bytes]:
        text = line.decode("utf-8", errors="replace").strip()
        if not text.startswith("data: "):
            return [line]

        payload = text[6:]
        if payload == "[DONE]":
            return [line]

        try:
            chunk = json.loads(payload)
        except json.JSONDecodeError:
            return [line]

        choices = chunk.get("choices", [])
        if not choices:
            return [line]

        delta = choices[0].get("delta", {})
        # Remove reasoning_content
        clean_delta = {k: v for k, v in delta.items() if k != "reasoning_content"}
        if clean_delta or choices[0].get("finish_reason"):
            chunk["choices"][0]["delta"] = clean_delta
            return [sse_line(chunk)]

        return []  # Empty delta — don't send


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
    choices = body.get("choices", [])
    for choice in choices:
        msg = choice.get("message", {})
        reasoning = msg.pop("reasoning_content", "")
        if not reasoning:
            continue

        content = msg.get("content", "")
        if mode == "drop":
            msg["content"] = content
        else:
            think_block = f"{markers.open}{reasoning}{markers.close}"
            msg["content"] = f"{think_block}\n{content}" if content else think_block

    return body


def full_response_to_sse(body: dict[str, Any], model: str) -> list[bytes]:
    """Convert a full JSON response to an SSE stream."""
    chunk_id = body.get("id", "converted")
    out: list[bytes] = []

    choices = body.get("choices", [])
    for i, choice in enumerate(choices):
        msg = choice.get("message", {})
        delta: dict[str, Any] = {}
        if msg.get("role"):
            delta["role"] = msg["role"]
        if msg.get("content"):
            delta["content"] = msg["content"]
        if msg.get("tool_calls"):
            delta["tool_calls"] = msg["tool_calls"]

        finish = choice.get("finish_reason")
        chunk = _make_chunk(chunk_id, model, delta, finish_reason=finish)
        chunk["choices"][0]["index"] = i
        out.append(sse_line(chunk))

    # Usage
    if "usage" in body:
        usage_chunk = _make_chunk(chunk_id, model, {}, finish_reason=None)
        usage_chunk["usage"] = body["usage"]
        usage_chunk["choices"] = []
        out.append(sse_line(usage_chunk))

    out.append(b"data: [DONE]\n\n")
    return out
