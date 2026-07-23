# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 BESTNYPRO INC
# Licensed under the Business Source License 1.1 — see LICENSE file

"""Thinking/reasoning markers and display modes."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Think-block markers (open/close)
THINK_OPEN = "\n\n<think>\n"
THINK_CLOSE = "\n</think>\n\n"
DETAILS_OPEN = "\n\n<details><summary>💭 thinking</summary>\n\n"
DETAILS_CLOSE = "\n\n</details>\n\n"

# Used by strip_think_from_history: removes both styles
_THINK_RE = re.compile(
    r"<think>.*?</think>"
    r"|<details><summary>Thinking…</summary>.*?</details>",
    re.DOTALL,
)


def strip_think(text: str) -> str:
    """Remove think/details blocks from text."""
    return _THINK_RE.sub("", text)


@dataclass(frozen=True)
class ThinkMarkers:
    """Markers for a specific display mode."""

    open: str
    close: str

    @classmethod
    def for_mode(cls, mode: str) -> "ThinkMarkers":
        """Return markers by mode name."""
        if mode == "details":
            return cls(open=DETAILS_OPEN, close=DETAILS_CLOSE)
        if mode == "native":
            # native: reasoning_content stays as-is, no markers
            return cls(open="", close="")
        # inline (default)
        return cls(open=THINK_OPEN, close=THINK_CLOSE)


class ThinkingState:
    """Think-block state per choice.index within a stream."""

    def __init__(self) -> None:
        self.open: set[int] = set()

    def reset(self) -> None:
        self.open.clear()
