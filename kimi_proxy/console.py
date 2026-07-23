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

# ---------------------------------------------------------------------------
#  Emoji mode (auto / on / off) with ASCII fallbacks
# ---------------------------------------------------------------------------

_EMOJI: bool = True  # resolved at startup via set_emoji_mode()

# emoji -> ASCII fallback for terminals without emoji glyphs
_FALLBACKS: dict[str, str] = {
    "✨": "*", "🌊": "~", "📦": "#", "💭": "?", "🧩": "?", "🧠": "?", "🙈": "x",
    "📨": ">", "🔀": "->", "🎛️": "*", "🎛": "*", "🕵️": "*", "🕵": "*",
    "✂️": "x", "✂": "x", "🏷️": "#", "🏷": "#", "🗜️": "-", "🗜": "-",
    "⏱️": "T", "⏱": "T", "⚡": "!", "🚀": "^", "🔢": "#", "📊": "=",
    "✔": "+", "✖": "x", "🔁": "@", "🎧": "*", "🌐": "*", "📝": "*",
    "🌙": "*", "⚠️": "!", "⚠": "!", "✅": "+", "❌": "x",
    "👤": "@", "🤖": "R", "🔧": "w", "⚙️": "*", "⚙": "*",
    "Σ": "=", "·": "|", "—": "-",
}


def set_emoji_mode(mode: str) -> None:
    """Set emoji mode: 'on' | 'off' | 'auto' (auto = conservative heuristic)."""
    global _EMOJI
    if mode == "on":
        _EMOJI = True
    elif mode == "off":
        _EMOJI = False
    else:  # auto
        _EMOJI = _detect_emoji_support()


def _detect_emoji_support() -> bool:
    """Heuristic: does this terminal likely render emoji?"""
    # Windows Terminal and modern xterm almost always do
    if os.environ.get("WT_SESSION"):
        return True
    term = (os.environ.get("TERM") or "").lower()
    if "xterm" in term or "kitty" in term or "alacritty" in term or "wezterm" in term:
        return True
    # VS Code integrated terminal: depends on configured font — often lacks emoji
    if os.environ.get("TERM_PROGRAM") == "vscode":
        return False
    # macOS Terminal.app / iTerm
    if os.environ.get("TERM_PROGRAM") in ("Apple_Terminal", "iTerm.app"):
        return True
    # Linux console with UTF-8 locale usually has some emoji font
    if sys.platform != "win32":
        return True
    # Legacy conhost / unknown — be safe
    return False


def icon(emoji: str, fallback: str = "") -> str:
    """Return emoji if enabled, else ASCII fallback (lookup table or given)."""
    if _EMOJI:
        return emoji
    return _FALLBACKS.get(emoji, fallback)


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
    """String display width without ANSI escapes.

    Emoji presentation rules:
    - Variation selectors (FE0E/FE0F) and ZWJ are zero-width.
    - A base char followed by FE0F (emoji presentation) is width 2,
      even if its East Asian width is neutral (⚙️, ✂️, 🏷️…).
    - Wide/fullwidth chars (🤖, 🔧, ⏱…) are width 2.
    """
    import re
    import unicodedata

    plain = re.sub(r"\033\[[0-9;]*m", "", text)
    width = 0
    pending_upgrade = False  # previous char may be upgraded by VS16
    for ch in plain:
        if ch == "\ufe0f":
            if pending_upgrade:
                width += 1  # upgrade previous neutral base to double-width
            pending_upgrade = False
            continue
        if ch in ("\ufe0e", "\u200d"):  # text presentation / ZWJ — zero width
            pending_upgrade = False
            continue
        if unicodedata.combining(ch):
            pending_upgrade = False
            continue
        eaw = unicodedata.east_asian_width(ch)
        if eaw in ("W", "F"):
            width += 2
            pending_upgrade = False
        else:
            width += 1
            # Non-alphanumeric symbols may render as double-width emoji with VS16
            pending_upgrade = not ch.isalnum() and ch not in " \t"
    return width


def _pad(text: str, width: int) -> str:
    """Pad text with spaces to a visible width."""
    return text + " " * max(0, width - _visible_len(text))


def boxed(lines: list[str], width: int = 58, border_color: str = CORAL) -> str:
    """Render lines inside a rounded box with a gradient header/footer.

    The box grows to fit the longest line (never narrower than `width`,
    never wider than the terminal).
    """
    content_w = max((_visible_len(line) for line in lines), default=0)
    width = max(width, content_w + 4)  # "│ " + content + " │"
    term_w = _term_width()
    if width > term_w:
        width = max(20, term_w)
        lines = [_truncate(line, width - 4) for line in lines]
    top = f"{border_color}╭{gradient_line(width - 2)}{border_color}╮{RESET}"
    bottom = f"{border_color}╰{gradient_line(width - 2)}{border_color}╯{RESET}"
    body: list[str] = []
    for line in lines:
        body.append(f"{border_color}│{RESET} {_pad(line, width - 4)} {border_color}│{RESET}")
    return "\n".join([top, *body, bottom])


def _term_width(default: int = 80) -> int:
    """Terminal width in columns (fallback if not a TTY)."""
    try:
        return os.get_terminal_size().columns
    except OSError:
        return default


def _truncate(text: str, max_width: int) -> str:
    """Truncate an ANSI-colored string to a display width, preserving RESET."""
    if _visible_len(text) <= max_width:
        return text
    out: list[str] = []
    width = 0
    i = 0
    import re
    ansi = re.compile(r"\033\[[0-9;]*m")
    # Reserve 1 column for the ellipsis
    limit = max_width - 1
    while i < len(text) and width < limit:
        m = ansi.match(text, i)
        if m:
            out.append(m.group(0))
            i = m.end()
            continue
        ch = text[i]
        w = _visible_len(ch)
        if width + w > limit:
            break
        out.append(ch)
        width += w
        i += 1
    return "".join(out) + "…" + RESET


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
        return colorize(f" {icon('✔')} 200 OK ", MINT, bold=True)
    return colorize(f" {icon('✖')} {status} ", PINK, bold=True)


def think_chip(mode: str) -> str:
    """Colored think-mode label."""
    icons = {"inline": "💭", "details": "🧩", "native": "🧠", "drop": "🙈"}
    ic = icon(icons.get(mode, "💭"))
    colors = {"inline": SKY, "details": LILAC, "native": MINT, "drop": GRAY}
    return colorize(f"{ic} {mode}", colors.get(mode, SKY))
