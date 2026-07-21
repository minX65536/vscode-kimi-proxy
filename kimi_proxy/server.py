# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 BESTNYPRO INC
# Licensed under the Business Source License 1.1 — see LICENSE file

"""aiohttp HTTP server (application entry point)."""

from __future__ import annotations

import aiohttp
from aiohttp import web

from .config import ProxyConfig
from .controller import ProxyController
from .logging_svc import MetricsLogger, UsageLogger


async def create_app(cfg: ProxyConfig) -> web.Application:
    """Create an aiohttp application with configured routes."""
    # Shared client session for all requests (connection pooling)
    timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=300)
    session = aiohttp.ClientSession(timeout=timeout)

    usage_logger = UsageLogger(cfg)
    metrics_logger = MetricsLogger(cfg)
    controller = ProxyController(cfg, session, usage_logger, metrics_logger)

    app = web.Application()
    app.router.add_get("/v1/models", controller.handle_models)
    app.router.add_post("/v1/chat/completions", controller.handle_chat_completions)

    # Health check
    async def health(request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "version": "9.0"})

    app.router.add_get("/health", health)

    # Cleanup
    async def on_cleanup(app: web.Application) -> None:
        await session.close()

    app.on_cleanup.append(on_cleanup)

    return app


def run_server(cfg: ProxyConfig) -> None:
    """Start the server (blocking call)."""
    app = create_app(cfg)
    web.run_app(
        app,
        host=cfg.listen_host,
        port=cfg.listen_port,
        print=None,  # Suppress default aiohttp banner
    )
