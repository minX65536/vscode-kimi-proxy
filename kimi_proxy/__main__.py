# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 BESTNYPRO INC
# Licensed under the Business Source License 1.1 — see LICENSE file

"""Dependency composition and proxy startup."""

from __future__ import annotations

import argparse

from . import __version__
from . import console as c
from .config import ProxyConfig
from .server import run_server


def _on_off(flag: bool) -> str:
    """Colored on/off label."""
    return c.colorize(f"{c.icon('✅')} on", c.MINT) if flag else c.colorize(f"{c.icon('❌')} off", c.GRAY)


def main() -> None:
    """Entry point: load config, print banner, start server."""
    parser = argparse.ArgumentParser(prog="kimi-proxy", description="Kimi/Moonshot proxy for VS Code")
    parser.add_argument("--config", metavar="PATH", default=None, help="Path to kimi-proxy.json config file")
    args = parser.parse_args()

    cfg = ProxyConfig.load(config_path=args.config)
    c.set_emoji_mode(cfg.emoji)

    title = c.colorize(f"{c.icon('🌙')} KIMI PROXY v{__version__}", c.CORAL, bold=True)
    lines = [
        title + c.colorize("  · async · kimi in your VS Code chat", c.GRAY),
        "",
        f"{c.SKY}{c.icon('🎧')} Listening{c.RESET}   http://{cfg.listen_host}:{cfg.listen_port}",
        f"{c.MINT}{c.icon('🌐')} Upstream{c.RESET}    {cfg.upstream_base}",
        f"{c.LILAC}{c.icon('💭')} Think mode{c.RESET} {c.think_chip(cfg.think_mode)}"
        f"   {c.GRAY}breakdown:{c.RESET} {_on_off(cfg.usage_breakdown)}",
        f"{c.SUNNY}{c.icon('🔁')} Retry{c.RESET}      {cfg.retry_attempts} attempts"
        f"   {c.GRAY}console:{c.RESET} {_on_off(cfg.console_enabled)}",
        f"{c.PEACH}{c.icon('📝')} Instructions{c.RESET} {'custom ' + c.icon('✅') if cfg.custom_instructions else 'default'}"
        f"   {c.GRAY}logging:{c.RESET} {_on_off(cfg.logging_enabled)}",
        f"{c.SKY}{c.icon('🗜️')} RTK{c.RESET}        {_on_off(cfg.rtk.enabled)}"
        + (f"   {c.GRAY}path:{c.RESET} {cfg.rtk.path}" if cfg.rtk.enabled else ""),
    ]
    print()
    print(c.boxed(lines, width=60), flush=True)
    print()

    if not cfg.api_key:
        print(c.colorize(c.icon('⚠️') + " WARNING: API key not set! Set MOONSHOT_API_KEY env var or api_key in config.", c.PINK, bold=True), flush=True)

    run_server(cfg)


if __name__ == "__main__":
    main()
