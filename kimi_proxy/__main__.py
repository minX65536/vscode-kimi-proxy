# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 BESTNYPRO INC
# Licensed under the Business Source License 1.1 — see LICENSE file

"""Dependency composition and proxy startup."""

from __future__ import annotations

import asyncio
import sys

from .config import ProxyConfig
from .server import run_server
from . import console as c


def _on_off(flag: bool) -> str:
    """Colored on/off label."""
    return c.colorize("✅ on", c.MINT) if flag else c.colorize("❌ off", c.GRAY)


def main() -> None:
    """Entry point: load config, print banner, start server."""
    cfg = ProxyConfig.load()

    title = c.colorize("🌙  KIMI PROXY V9", c.CORAL, bold=True)
    lines = [
        title + c.colorize("  · async · kimi in your VS Code chat", c.GRAY),
        "",
        f"{c.SKY}🎧 Listening{c.RESET}   http://{cfg.listen_host}:{cfg.listen_port}",
        f"{c.MINT}🌐 Upstream{c.RESET}    {cfg.upstream_base}",
        f"{c.LILAC}💭 Think mode{c.RESET} {c.think_chip(cfg.think_mode)}"
        f"   {c.GRAY}breakdown:{c.RESET} {_on_off(cfg.usage_breakdown)}",
        f"{c.SUNNY}🔁 Retry{c.RESET}      {cfg.retry_attempts} attempts"
        f"   {c.GRAY}console:{c.RESET} {_on_off(cfg.console_enabled)}",
        f"{c.PEACH}📝 Instructions{c.RESET} {'custom ✅' if cfg.custom_instructions else 'default'}"
        f"   {c.GRAY}logging:{c.RESET} {_on_off(cfg.logging_enabled)}",
    ]
    print()
    print(c.boxed(lines, width=60), flush=True)
    print()

    if not cfg.api_key:
        print(c.colorize("⚠️  WARNING: API key not set! Set MOONSHOT_API_KEY env var or api_key in config.", c.PINK, bold=True), flush=True)

    run_server(cfg)


if __name__ == "__main__":
    main()
