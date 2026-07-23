# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 BESTNYPRO INC
# Licensed under the Business Source License 1.1 — see LICENSE file

"""Usage, metrics and breakdown logging + pretty request summaries."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import ProxyConfig
from . import console as c


def _append_jsonl(path: str, record: dict[str, Any]) -> None:
    """Append a JSON line to a file (create directory if needed)."""
    if not path:
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _estimate_chars(messages: list[dict[str, Any]]) -> dict[str, int]:
    """Rough character count estimate by message category."""
    cats: dict[str, int] = {
        "system": 0,
        "user": 0,
        "assistant": 0,
        "tool": 0,
        "tool_args": 0,
    }
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls", [])

        if isinstance(content, str):
            text_len = len(content)
        elif isinstance(content, list):
            text_len = sum(
                len(p.get("text", "")) for p in content if isinstance(p, dict)
            )
        else:
            text_len = 0

        if role in cats:
            cats[role] += text_len

        # tool_calls arguments
        for tc in tool_calls:
            fn = tc.get("function", {})
            args_str = fn.get("arguments", "")
            if isinstance(args_str, str):
                cats["tool_args"] += len(args_str)
            name = fn.get("name", "")
            cats["tool_args"] += len(name)

    return cats


# ---------------------------------------------------------------------------
#  RequestSummary — one request from start to finish
# ---------------------------------------------------------------------------

@dataclass
class RequestSummary:
    """Accumulates everything about a single request for the final summary."""

    model: str = "unknown"
    stream: bool = False
    think_mode: str = "inline"
    t_start: float = field(default_factory=time.monotonic)

    # Pipeline facts
    msg_count: int = 0
    alias_from: str = ""
    forced_params: dict[str, Any] = field(default_factory=dict)
    instructions: str = ""          # which instructions won: custom / agent / ide / none
    stripped_think: int = 0         # assistant messages cleaned of think-blocks
    nulled_tool_content: int = 0    # assistant msgs where content was nulled (tool_calls)
    renamed_tool_calls: int = 0     # assistant msgs with empty tool_call names fixed
    trimmed_msgs: int = 0           # messages dropped by the context budget
    rtk_compressed: int = 0        # tool outputs compressed via rtk

    # Upstream facts
    attempts: int = 1
    retried: bool = False
    ttft_ms: float | None = None
    total_ms: float | None = None
    status: int | str = 200
    usage: dict[str, Any] | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)

    def finish(self) -> None:
        """Stamp the total duration."""
        self.total_ms = (time.monotonic() - self.t_start) * 1000

    # ------------------------------------------------------------------
    #  Rendering
    # ------------------------------------------------------------------

    def render(self) -> str:
        """Render the summary as a pretty box for the console."""
        u = self.usage or {}
        prompt_t = u.get("prompt_tokens")
        completion_t = u.get("completion_tokens")

        mode = f"{c.icon('🌊')} stream" if self.stream else f"{c.icon('📦')} json"
        header = (
            f"{c.colorize(c.icon('✨') + ' REQUEST SUMMARY', c.CORAL, bold=True)}"
            f"  {c.colorize(self.model, c.PEACH, bold=True)}"
            f"  {c.GRAY}{c.icon('·')}{c.RESET} {mode}"
            f"  {c.GRAY}{c.icon('·')}{c.RESET} {c.think_chip(self.think_mode)}"
        )

        # Pipeline line
        pipe_bits = [f"{c.GRAY}{c.icon('📨')} {self.msg_count} msgs{c.RESET}"]
        if self.alias_from:
            pipe_bits.append(f"{c.SKY}{c.icon('🔀')} {self.alias_from} → {self.model}{c.RESET}")
        if self.forced_params:
            fp = " ".join(f"{k}={v}" for k, v in self.forced_params.items())
            pipe_bits.append(f"{c.LILAC}{c.icon('🎛️')} {fp}{c.RESET}")
        instr_icons = {
            "custom": f"{c.icon('📝')} custom",
            "agent": f"{c.icon('🕵️')} agent",
            "ide": f"{c.icon('💻', '#')} ide",
            "none": "—",
        }
        pipe_bits.append(f"{c.MINT}{instr_icons.get(self.instructions, self.instructions)}{c.RESET}")
        if self.stripped_think:
            pipe_bits.append(f"{c.GRAY}{c.icon('✂️')} think ×{self.stripped_think}{c.RESET}")
        if self.nulled_tool_content:
            pipe_bits.append(f"{c.GRAY}{c.icon('🔧')} content→null ×{self.nulled_tool_content}{c.RESET}")
        if self.renamed_tool_calls:
            pipe_bits.append(f"{c.GRAY}{c.icon('🏷️')} name→tool ×{self.renamed_tool_calls}{c.RESET}")
        if self.trimmed_msgs:
            pipe_bits.append(f"{c.SUNNY}{c.icon('🗜️')} -{self.trimmed_msgs} msgs{c.RESET}")
        if self.rtk_compressed:
            pipe_bits.append(f"{c.SKY}{c.icon('🗜️')} rtk ×{self.rtk_compressed}{c.RESET}")

        # Timing line
        speed = c.tok_per_sec(completion_t, self.total_ms)
        retry_note = f"  {c.SUNNY}{c.icon('🔁')} ×{self.attempts}{c.RESET}" if self.retried else ""
        timing = (
            f"{c.SKY}{c.icon('⏱️')} ttft {c.fmt_ms(self.ttft_ms)}{c.RESET}"
            f"  {c.MINT}{c.icon('⚡')} total {c.fmt_ms(self.total_ms)}{c.RESET}"
            f"  {c.LILAC}{c.icon('🚀')} {speed.replace('—', c.icon('—'))}{c.RESET}"
            f"{retry_note}"
            f"  {c.status_chip(self.status)}"
        )

        # Tokens line
        tokens = (
            f"{c.PEACH}{c.icon('🔢')} tokens{c.RESET}  "
            f"{c.GRAY}in{c.RESET} {c.fmt_tokens(prompt_t)}"
            f"  {c.GRAY}out{c.RESET} {c.fmt_tokens(completion_t)}"
            f"  {c.GRAY}{c.icon('Σ', '=')}{c.RESET} {c.fmt_tokens(u.get('total_tokens'))}"
        )

        lines = [header, "", "  ".join(pipe_bits), timing, tokens]

        # Breakdown mini-chart
        breakdown_lines = self._render_breakdown()
        if breakdown_lines:
            lines.append("")
            lines.extend(breakdown_lines)

        return c.boxed(lines, width=62)

    def _render_breakdown(self) -> list[str]:
        """Render the prompt composition as mini bar charts."""
        if not self.messages:
            return []
        cats = _estimate_chars(self.messages)
        total = sum(cats.values())
        if total == 0:
            return []

        out = [f"{c.GRAY}{c.icon('📊')} prompt makeup{c.RESET}"]
        # Estimate token column width for right-alignment
        est = {cat: int(chars / 3) for cat, chars in cats.items() if chars}
        max_tok_w = max((len(f"{t:,}") for t in est.values()), default=1)
        # Sort by size descending for readability
        for cat, chars in sorted(cats.items(), key=lambda kv: kv[1], reverse=True):
            if chars == 0:
                continue
            pct = chars / total * 100
            color = c.CAT_COLORS.get(cat, c.GRAY)
            tok = est[cat]
            label = f"{cat:<10}"
            out.append(
                f"  {color}{label}{c.RESET} {c.bar(pct, width=18, color=color)}"
                f" {c.GRAY}{pct:5.1f}%  ~{tok:>{max_tok_w},} tok{c.RESET}"
            )
        return out


def print_summary(summary: RequestSummary, verbose: bool) -> None:
    """Print the request summary box to the console."""
    if verbose:
        print(summary.render(), flush=True)


class UsageLogger:
    """Usage data logging."""

    def __init__(self, cfg: ProxyConfig) -> None:
        self._cfg = cfg

    def log(
        self,
        model: str,
        usage: dict[str, Any] | None,
        ttft_ms: float | None = None,
        total_ms: float | None = None,
        attempts: int = 1,
        messages: list[dict[str, Any]] | None = None,
    ) -> None:
        """Write a usage record to console and/or jsonl."""
        if not usage:
            return

        record: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "model": model,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "ttft_ms": round(ttft_ms) if ttft_ms else None,
            "total_ms": round(total_ms) if total_ms else None,
            "attempts": attempts,
        }

        # Console output is handled by the RequestSummary box — JSONL only here.
        if self._cfg.logging_enabled and self._cfg.usage_log:
            _append_jsonl(self._cfg.usage_log, record)

        # Breakdown
        if self._cfg.usage_breakdown and messages:
            self._log_breakdown(model, usage, messages)

    def _log_breakdown(
        self,
        model: str,
        usage: dict[str, Any],
        messages: list[dict[str, Any]],
    ) -> None:
        """Log breakdown by message categories."""
        cats = _estimate_chars(messages)
        total_chars = sum(cats.values()) or 1
        # ~3 chars per token (rough heuristic)
        prompt_tokens = usage.get("prompt_tokens", 0)

        parts: list[str] = []
        for cat, chars in cats.items():
            if chars == 0:
                continue
            pct = chars / total_chars * 100
            est_tokens = int(chars / 3)
            parts.append(f"{cat} ~{est_tokens} ({pct:.0f}%)")

        breakdown_str = " | ".join(parts)

        # Console output is handled by the RequestSummary box — JSONL only here.
        if self._cfg.logging_enabled and self._cfg.usage_breakdown_log:
            record: dict[str, Any] = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "model": model,
                "prompt_tokens": prompt_tokens,
                "breakdown": {
                    cat: {
                        "chars": chars,
                        "est_tokens": int(chars / 3),
                        "pct": round(chars / total_chars * 100, 1),
                    }
                    for cat, chars in cats.items()
                    if chars > 0
                },
            }
            _append_jsonl(self._cfg.usage_breakdown_log, record)


class MetricsLogger:
    """Performance metrics logging."""

    def __init__(self, cfg: ProxyConfig) -> None:
        self._cfg = cfg

    def log(
        self,
        model: str,
        ttft_ms: float | None,
        total_ms: float,
        status: int,
        attempts: int,
    ) -> None:
        """Write a metric record to jsonl."""
        if not self._cfg.logging_enabled or not self._cfg.metrics_log:
            return

        record: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "model": model,
            "ttft_ms": round(ttft_ms) if ttft_ms else None,
            "total_ms": round(total_ms),
            "status": status,
            "attempts": attempts,
        }
        _append_jsonl(self._cfg.metrics_log, record)
