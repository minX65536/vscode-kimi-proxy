# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 BESTNYPRO INC
# Licensed under the Business Source License 1.1 — see LICENSE file

"""Building and injecting system instructions."""

from __future__ import annotations

from typing import Any

AGENT_INSTRUCTION = (
    "\n[AGENT]: You are in VS Code Agent Mode. Process tool outputs carefully. "
    "Output your reasoning and final answers clearly."
)


def inject_instructions(
    messages: list[dict[str, Any]],
    custom_instructions: str,
) -> list[dict[str, Any]]:
    """Insert or update the system message with custom instructions.

    If a system message already exists, AGENT_INSTRUCTION is appended to it.
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

    if sys_idx >= 0:
        # Prepend custom_instructions if provided and not already present
        if custom_instructions and custom_instructions.strip() not in existing_system:
            existing_system = custom_instructions.strip() + "\n\n" + existing_system
        # Append AGENT_INSTRUCTION if not already present
        existing_content = result[sys_idx].get("content", "")
        if isinstance(existing_content, str):
            if AGENT_INSTRUCTION.strip() not in existing_content:
                result[sys_idx] = {**result[sys_idx], "content": existing_system + AGENT_INSTRUCTION}
            elif custom_instructions:
                # AGENT_INSTRUCTION was already there but custom_instructions was not
                result[sys_idx] = {**result[sys_idx], "content": existing_system}
        elif isinstance(existing_content, list):
            joined = " ".join(
                str(p.get("text", "")) for p in existing_content if isinstance(p, dict)
            )
            if AGENT_INSTRUCTION.strip() not in joined:
                existing_content.append({"type": "text", "text": AGENT_INSTRUCTION})
    else:
        default_content = "You are a helpful coding assistant." + AGENT_INSTRUCTION
        if custom_instructions:
            default_content = custom_instructions.strip() + "\n\n" + default_content
        result.insert(0, {"role": "system", "content": default_content})

    return result
