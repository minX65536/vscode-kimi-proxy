# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 BESTNYPRO INC
# Licensed under the Business Source License 1.1 — see LICENSE file

"""RTK (Rust Token Killer) connector — compress tool outputs via the rtk CLI.

Uses ``rtk pipe --filter <name>`` as a subprocess to compress tool-call
results in the message history before they are sent upstream.  The proxy
never blocks on rtk: a configurable timeout guards every invocation, and
any failure silently falls back to the original (uncompressed) content.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  Filter mapping: heuristic detection of output format → rtk pipe filter
# ---------------------------------------------------------------------------

# Ordered by specificity — first match wins.
_FORMAT_HINTS: list[tuple[list[str], str]] = [
    # Test frameworks
    (["test result:", "passed;"], "cargo-test"),
    (["=== test session starts"], "pytest"),
    (["PHPUnit ", "by Sebastian Bergmann"], "phpunit"),
    # Go NDJSON test events
    (['"Action"', '"Package"'], "go-test"),
    # Type errors
    ([": error:", ".py:"], "mypy"),
    # Git
    (["diff --git "], "git-diff"),
    # Grep-like: file:line:content (checked as fallback below)
]

# Minimum content length (chars) worth compressing.
_MIN_LEN = 500


@dataclass(frozen=True)
class RtkConfig:
    """RTK connector configuration (immutable)."""

    enabled: bool = False
    path: str = "rtk"  # binary path or name in PATH
    timeout: float = 2.0  # seconds per invocation
    min_length: int = _MIN_LEN  # chars; shorter content passes through
    filters: tuple[str, ...] = ()  # empty = auto-detect only


# ---------------------------------------------------------------------------
#  Availability
# ---------------------------------------------------------------------------

def find_rtk_binary(cfg: RtkConfig) -> str | None:
    """Resolve the rtk binary path.  Returns None when not found."""
    # Explicit path?
    if cfg.path != "rtk":
        if shutil.which(cfg.path):
            return cfg.path
        # Try as-is (absolute or relative path)
        from pathlib import Path
        if Path(cfg.path).is_file():
            return str(Path(cfg.path).resolve())
        return None
    return shutil.which("rtk")


# ---------------------------------------------------------------------------
#  Filter auto-detection
# ---------------------------------------------------------------------------

def _detect_filter(text: str) -> str | None:
    """Pick the best rtk pipe filter for the given text, or None."""
    probe = text[:2048]
    for hints, filter_name in _FORMAT_HINTS:
        if all(h in probe for h in hints):
            return filter_name
    # grep-like: file:line:content pattern in first few lines
    lines = [l for l in probe.split("\n") if l.strip()][:5]
    if lines:
        grep_like = sum(
            1
            for l in lines
            if len(l.split(":", 2)) == 3 and l.split(":")[1].isdigit()
        )
        if grep_like >= 2:
            return "grep"
    return None


# ---------------------------------------------------------------------------
#  Core compression
# ---------------------------------------------------------------------------

def compress_text(
    text: str,
    cfg: RtkConfig,
    rtk_bin: str,
    filter_name: str | None = None,
) -> tuple[str, bool]:
    """Compress *text* via ``rtk pipe``.

    Returns ``(result, was_compressed)``.  On any failure the original
    text is returned unchanged with ``was_compressed=False``.
    """
    if len(text) < cfg.min_length:
        return text, False

    filt = filter_name or _detect_filter(text)
    if filt is None:
        return text, False

    cmd = [rtk_bin, "pipe", "--filter", filt]
    try:
        proc = subprocess.run(
            cmd,
            input=text,
            capture_output=True,
            text=True,
            timeout=cfg.timeout,
        )
        if proc.returncode != 0:
            log.debug("rtk pipe exited %d: %s", proc.returncode, proc.stderr[:200])
            return text, False
        result = proc.stdout
        # Never worse guard: if rtk made it bigger, keep original
        if len(result) >= len(text):
            return text, False
        return result, True
    except subprocess.TimeoutExpired:
        log.debug("rtk pipe timed out after %.1fs", cfg.timeout)
        return text, False
    except FileNotFoundError:
        log.warning("rtk binary not found: %s", rtk_bin)
        return text, False
    except Exception:
        log.debug("rtk pipe failed", exc_info=True)
        return text, False


# ---------------------------------------------------------------------------
#  Message-level integration
# ---------------------------------------------------------------------------

def compress_tool_outputs(
    messages: list[dict],
    cfg: RtkConfig,
    rtk_bin: str,
) -> tuple[list[dict], int]:
    """Walk *messages* and compress tool-role content via rtk.

    Returns ``(new_messages, compressed_count)``.  Messages are not mutated
    in-place; new dicts are created for changed entries.
    """
    if not cfg.enabled:
        return messages, 0

    compressed = 0
    out: list[dict] = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content")

        # tool messages with string content
        if role == "tool" and isinstance(content, str) and content:
            new_content, did = compress_text(content, cfg, rtk_bin)
            if did:
                msg = {**msg, "content": new_content}
                compressed += 1

        # tool messages with list content (multi-part)
        elif role == "tool" and isinstance(content, list):
            new_parts = []
            part_compressed = False
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    new_text, did = compress_text(part["text"], cfg, rtk_bin)
                    if did:
                        part = {**part, "text": new_text}
                        part_compressed = True
                new_parts.append(part)
            if part_compressed:
                msg = {**msg, "content": new_parts}
                compressed += 1

        # assistant tool_calls arguments (JSON strings — try json filter)
        elif role == "assistant":
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                new_tcs = []
                tc_compressed = False
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    args_str = fn.get("arguments", "")
                    if isinstance(args_str, str) and len(args_str) >= cfg.min_length:
                        new_args, did = compress_text(args_str, cfg, rtk_bin, "grep")
                        if did:
                            tc = {**tc, "function": {**fn, "arguments": new_args}}
                            tc_compressed = True
                    new_tcs.append(tc)
                if tc_compressed:
                    msg = {**msg, "tool_calls": new_tcs}
                    compressed += 1

        out.append(msg)

    return out, compressed
