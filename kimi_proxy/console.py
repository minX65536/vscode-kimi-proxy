# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 BESTNYPRO INC
# Licensed under the Business Source License 1.1 — see LICENSE file

"""Fun console output: colors, boxes, bars and request summary rendering."""

from __future__ import annotations

import os
import sys

# Enable ANSI escape sequences on Windows 10+
if sys.platform == "win32":
    os.system("")

# ---------------------------------------------------------------------------
#  Color palette (truecolor)
# ---------------------------------------------------------------------------

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

CORAL = "\033[38;5;209m"
PEACH = "\033[38;5;216m"
MINT = "\033[38;5;114m"
SKY = "\033[38;5;111m"
LILAC = "\033[38;5;183m"
SUNNY = "\033[38;5;221m"
GRAY = "\033[38;5;245m"
PINK = "\033[38;5;211m"

GRADIENT = [CORAL, PEACH, SUNNY, MINT, SKY, LILAC]

CAT_COLORS = {
    "system": SKY,
    "user": MINT,
    "assistant": LILAC,
    "tool": SUNNY,
    "tool_args": PEACH,
}

CAT_ICONS = {
    "system": "⚙️ ",
    "user": "👤",
    "assistant": "🤖",
    "tool": "🔧",
    "tool_args": "📦",
}


def colorize(text: str, color: str, bold: bool = False) -> str:
    """Wrap text in an ANSI color."""
    prefix = (BOLD if bold else "") + color
    return f"{prefix}{text}{RESET}"


def gradient_line(width: int, char: str = "─") -> str:
    """A horizontal line painted with a color gradient."""
    if width <= 0:
        return ""
    out: list[str] = []
    for i in range(width):
        c = GRADIENT[int(i / width * len(GRADIENT)) % len(GRADIENT)]
        out.append(f"{c}{char}")
    return "".join(out) + RESET


# ---------------------------------------------------------------------------
#  Box helpers
# ---------------------------------------------------------------------------

def _visible_len(text: str) -> int:
    """String length without ANSI escape sequences."""
    import re
    return len(re.sub(r"\033\[[0-9;]*m", "", text))


def _pad(text: str, width: int) -> str:
    """Pad text with spaces to a visible width."""
    return text + " " * max(0, width - _visible_len(text))


def boxed(lines: list[str], width: int = 58, border_color: str = CORAL) -> str:
    """Render lines inside a rounded box with a gradient header/footer."""
    inner = width - 2  # space for "│ " and " │"... actually "│" on both sides
    top = f"{border_color}╭{gradient_line(width - 2)}{border_color}╮{RESET}"
    bottom = f"{border_color}╰{gradient_line(width - 2)}{border_color}╯{RESET}"
    body: list[str] = []
    for line in lines:
        body.append(f"{border_color}│{RESET} {_pad(line, width - 4)} {border_color}│{RESET}")
    return "\n".join([top, *body, bottom])


def bar(pct: float, width: int = 20, color: str = MINT) -> str:
    """A small unicode bar chart: ██████░░░░."""
    pct = max(0.0, min(100.0, pct))
    filled = round(pct / 100 * width)
    empty = width - filled
    return f"{color}{'█' * filled}{GRAY}{'░' * empty}{RESET}"


# ---------------------------------------------------------------------------
#  Formatting helpers
# ---------------------------------------------------------------------------

def fmt_ms(ms: float | None) -> str:
    """Human-friendly duration: 123ms / 4.2s."""
    if ms is None:
        return "—"
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.2f}s"


def fmt_tokens(n: int | None) -> str:
    """Token count with thousand separators: 12,345."""
    if n is None:
        return "?"
    return f"{n:,}"


def tok_per_sec(completion_tokens: int | None, total_ms: float | None) -> str:
    """Rough generation speed."""
    if not completion_tokens or not total_ms or total_ms <= 0:
        return "—"
    return f"{completion_tokens / (total_ms / 1000):.1f} tok/s"


def status_chip(status: int | str) -> str:
    """Colored status label."""
    if status == 200 or status == "ok":
        return colorize(" ✔ 200 OK ", MINT, bold=True)
    return colorize(f" ✖ {status} ", PINK, bold=True)


def think_chip(mode: str) -> str:
    """Colored think-mode label."""
    icons = {"inline": "💭", "details": "🧩", "native": "🧠", "drop": "🙈"}
    icon = icons.get(mode, "💭")
    colors = {"inline": SKY, "details": LILAC, "native": MINT, "drop": GRAY}
    return colorize(f"{icon} {mode}", colors.get(mode, SKY))
