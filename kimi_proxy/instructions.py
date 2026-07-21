# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 BESTNYPRO INC
# Licensed under the Business Source License 1.1 — see LICENSE file

"""Building and injecting system instructions."""

from __future__ import annotations

from typing import Any

AGENT_INSTRUCTION = (
    "[AGENT]: You are in VS Code Agent Mode. Process tool outputs carefully. "
    "Output your reasoning and final answers clearly."
)


def build_system_content(cfg_instructions: str, existing_system: str) -> str:
    """Build the final system message content.

    Priority order (top = highest):
      1. custom_instructions from config (highest)
      2. AGENT_INSTRUCTION (proxy-level instruction)
      3. Original system prompt from the IDE
    """
    parts: list[str] = []
    if cfg_instructions:
        parts.append(cfg_instructions.strip())
    parts.append(AGENT_INSTRUCTION)
    if existing_system:
        parts.append(existing_system.strip())
    return "\n\n".join(parts)


def inject_instructions(
    messages: list[dict[str, Any]],
    custom_instructions: str,
) -> list[dict[str, Any]]:
    """Insert or update the system message with custom instructions.

    If a system message already exists, its content is rewritten.
    If not, a new system message is inserted at position 0.
    """
    if not messages:
        return messages

    result = list(messages)
    existing_system = ""
    sys_idx = -1

    for i, msg in enumerate(result):
        if msg.get("role") == "system":
            sys_idx = i
            content = msg.get("content", "")
            if isinstance(content, str):
                existing_system = content
            elif isinstance(content, list):
                # content may be a list of parts [{type:"text",text:...}]
                existing_system = " ".join(
                    p.get("text", "") for p in content if isinstance(p, dict)
                )
            break

    new_content = build_system_content(custom_instructions, existing_system)

    if sys_idx >= 0:
        result[sys_idx] = {**result[sys_idx], "content": new_content}
    else:
        result.insert(0, {"role": "system", "content": new_content})

    return result
