# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 BESTNYPRO INC
# Licensed under the Business Source License 1.1 — see LICENSE file

"""Async Moonshot API client with retry logic."""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

import aiohttp

from .config import ProxyConfig


class UpstreamError(Exception):
    """Error from the upstream API."""

    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body
        super().__init__(f"Upstream {status}: {body[:200]}")


class UpstreamClient:
    """Encapsulates HTTP calls to the Moonshot API.

    - Retry with backoff on 429/5xx
    - Configurable timeouts
    - Returns SSE stream or full JSON
    """

    # Status codes worth retrying
    _RETRYABLE = {429, 500, 502, 503, 504}

    def __init__(self, cfg: ProxyConfig, session: aiohttp.ClientSession) -> None:
        self._cfg = cfg
        self._session = session

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        if self._cfg.api_key:
            h["Authorization"] = f"Bearer {self._cfg.api_key}"
        return h

    async def post_stream(self, body: dict[str, Any]) -> tuple[aiohttp.ClientResponse, int]:
        """POST with stream=true. Returns (response, attempts_used).

        Raises UpstreamError on non-retryable error or exhausted attempts.
        """
        last_error: UpstreamError | None = None

        for attempt in range(self._cfg.retry_attempts):
            try:
                resp = await self._session.post(
                    self._cfg.upstream_url,
                    json=body,
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=None, sock_read=300),
                )

                if resp.status == 200:
                    return resp, attempt + 1

                # Read error body
                err_body = await resp.text()
                last_error = UpstreamError(resp.status, err_body)

                if resp.status not in self._RETRYABLE:
                    raise last_error

                # Retry
                if attempt < self._cfg.retry_attempts - 1:
                    wait = self._cfg.retry_backoff[min(attempt, len(self._cfg.retry_backoff) - 1)]
                    await asyncio.sleep(wait)

            except aiohttp.ClientError as exc:
                last_error = UpstreamError(0, str(exc))
                if attempt < self._cfg.retry_attempts - 1:
                    wait = self._cfg.retry_backoff[min(attempt, len(self._cfg.retry_backoff) - 1)]
                    await asyncio.sleep(wait)

        raise last_error or UpstreamError(0, "Unknown error")

    async def post_json(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST without stream. Returns full JSON response."""
        body_nostream = {**body, "stream": False}

        last_error: UpstreamError | None = None
        for attempt in range(self._cfg.retry_attempts):
            try:
                async with self._session.post(
                    self._cfg.upstream_url,
                    json=body_nostream,
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()

                    err_body = await resp.text()
                    last_error = UpstreamError(resp.status, err_body)

                    if resp.status not in self._RETRYABLE:
                        raise last_error

                    if attempt < self._cfg.retry_attempts - 1:
                        wait = self._cfg.retry_backoff[min(attempt, len(self._cfg.retry_backoff) - 1)]
                        await asyncio.sleep(wait)

            except aiohttp.ClientError as exc:
                last_error = UpstreamError(0, str(exc))
                if attempt < self._cfg.retry_attempts - 1:
                    wait = self._cfg.retry_backoff[min(attempt, len(self._cfg.retry_backoff) - 1)]
                    await asyncio.sleep(wait)

        raise last_error or UpstreamError(0, "Unknown error")
