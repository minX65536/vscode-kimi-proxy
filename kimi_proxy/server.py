
# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 BESTNYPRO INC
# Licensed under the Business Source License 1.1 — see LICENSE file

"""aiohttp HTTP server (application entry point)."""

from __future__ import annotations

import asyncio

import aiohttp
from aiohttp import web

from . import __version__
from .config import ProxyConfig
from .controller import ProxyController
from .logging_svc import MetricsLogger, UsageLogger


def _silence_aiohttp_ctrl_c_noise(loop: asyncio.AbstractEventLoop, context: dict) -> None:
    """Suppress known aiohttp Windows Ctrl+C noise (InvalidStateError in _handle_request)."""
    exc = context.get("exception")
    if isinstance(exc, asyncio.InvalidStateError):
        return  # aiohttp bug on Ctrl+C, harmless
    loop.default_exception_handler(context)


async def create_app(cfg: ProxyConfig) -> web.Application:
    """Create an aiohttp application with configured routes."""
    # Shared client session for all requests (connection pooling)
    # total=600s (10 min) max for full request, sock_read=120s between chunks
    timeout = aiohttp.ClientTimeout(total=600, connect=30, sock_read=120)
    session = aiohttp.ClientSession(timeout=timeout)

    usage_logger = UsageLogger(cfg)
    metrics_logger = MetricsLogger(cfg)
    controller = ProxyController(cfg, session, usage_logger, metrics_logger)

    loop = asyncio.get_event_loop()
    loop.set_exception_handler(_silence_aiohttp_ctrl_c_noise)

    app = web.Application(client_max_size=cfg.client_max_size)
    app.router.add_get("/v1/models", controller.handle_models)
    app.router.add_post("/v1/chat/completions", controller.handle_chat_completions)
    app.router.add_get("/stats", controller.handle_stats)

    # Health check
    async def health(request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "version": __version__})

    app.router.add_get("/health", health)

    # Cleanup
    async def on_cleanup(app: web.Application) -> None:
        await session.close()

    app.on_cleanup.append(on_cleanup)

    return app


def run_server(cfg: ProxyConfig) -> None:
    """Start the server (blocking call)."""
    import errno
    import sys

    from . import console as c

    app = create_app(cfg)
    try:
        web.run_app(
            app,
            host=cfg.listen_host,
            port=cfg.listen_port,
            print=None,  # Suppress default aiohttp banner
            handler_cancellation=True,  # avoid aiohttp InvalidStateError noise on Ctrl+C
        )
    except KeyboardInterrupt:
        pass  # clean Ctrl+C exit
    except OSError as exc:
        if exc.errno in (errno.EADDRINUSE, 10048):  # 10048 = Windows WSAEADDRINUSE
            print(
                c.colorize(
                    f"\n❌ Port {cfg.listen_port} is already in use!\n"
                    f"   Another instance may be running, or another app occupies the port.\n"
                    f"   Try: netstat -ano | findstr :{cfg.listen_port}\n"
                    f"   Or change listen_port in kimi-proxy.json\n",
                    c.PINK,
                    bold=True,
                ),
                file=sys.stderr,
                flush=True,
            )
            sys.exit(1)
        raise
