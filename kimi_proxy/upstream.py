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
        super().__init__(f"Upstream {status}: {body[:1000]}")


class UpstreamClient:
    """Encapsulates HTTP calls to the Moonshot API.

    - Retry with backoff on 429/5xx
    - Configurable timeouts
    - Returns SSE stream or full JSON
    """

    # Status codes worth retrying (408, 409, 425, 429, or any 5xx)
    _RETRYABLE = {408, 409, 425, 429}

    def __init__(self, cfg: ProxyConfig, session: aiohttp.ClientSession) -> None:
        self._cfg = cfg
        self._session = session

    @staticmethod
    def _is_retryable(status: int) -> bool:
        """Retry rule: 408/409/425/429 or any 5xx."""
        return status in UpstreamClient._RETRYABLE or status >= 500

    def _retry_delay(self, resp: aiohttp.ClientResponse, attempt: int) -> float:
        """Retry delay: Retry-After header takes priority, else backoff."""
        backoff = self._cfg.retry_backoff[min(attempt, len(self._cfg.retry_backoff) - 1)]
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), 60.0)
            except ValueError:
                pass
        return min(float(backoff), 60.0)

    def _headers(self, client_headers: dict[str, str] | None = None) -> dict[str, str]:
        """Build upstream headers.

        If cfg.api_key is set, it overrides the client's Authorization.
        Otherwise, the client's Authorization header is forwarded.
        """
        h: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        if self._cfg.api_key:
            h["Authorization"] = f"Bearer {self._cfg.api_key}"
        elif client_headers:
            # Forward the client's Authorization header (passthrough)
            auth = client_headers.get("Authorization") or client_headers.get("authorization")
            if auth:
                h["Authorization"] = auth
        return h

    async def post_stream(
        self,
        body: dict[str, Any],
        client_headers: dict[str, str] | None = None,
    ) -> tuple[aiohttp.ClientResponse, int]:
        """POST with stream=true. Returns (response, attempts_used).

        Raises UpstreamError on non-retryable error or exhausted attempts.
        """
        last_error: UpstreamError | None = None

        for attempt in range(self._cfg.retry_attempts):
            try:
                resp = await self._session.post(
                    self._cfg.upstream_url,
                    json=body,
                    headers=self._headers(client_headers),
                    timeout=aiohttp.ClientTimeout(total=None, sock_read=300),
                    allow_redirects=False,
                )

                # Detect redirects (usually means wrong upstream_base)
                if 300 <= resp.status < 400:
                    location = resp.headers.get("Location", "")
                    raise UpstreamError(
                        resp.status,
                        f"Redirect {resp.status} -> {location}. "
                        f"Check upstream_base ({self._cfg.upstream_base})",
                    )

                if resp.status == 200:
                    return resp, attempt + 1

                # Read error body
                err_body = await resp.text()
                last_error = UpstreamError(resp.status, err_body)

                if not self._is_retryable(resp.status):
                    raise last_error

                # Retry (Retry-After header takes priority)
                if attempt < self._cfg.retry_attempts - 1:
                    await asyncio.sleep(self._retry_delay(resp, attempt))
                    resp.close()
                    continue
                resp.close()

            except aiohttp.ClientError as exc:
                last_error = UpstreamError(0, str(exc))
                if attempt < self._cfg.retry_attempts - 1:
                    wait = self._cfg.retry_backoff[min(attempt, len(self._cfg.retry_backoff) - 1)]
                    await asyncio.sleep(wait)

        raise last_error or UpstreamError(0, "Unknown error")

    async def post_json(
        self,
        body: dict[str, Any],
        client_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """POST without stream. Returns full JSON response."""
        body_nostream = {**body, "stream": False}

        last_error: UpstreamError | None = None
        for attempt in range(self._cfg.retry_attempts):
            try:
                async with self._session.post(
                    self._cfg.upstream_url,
                    json=body_nostream,
                    headers=self._headers(client_headers),
                    timeout=aiohttp.ClientTimeout(total=120),
                    allow_redirects=False,
                ) as resp:
                    if 300 <= resp.status < 400:
                        location = resp.headers.get("Location", "")
                        raise UpstreamError(
                            resp.status,
                            f"Redirect {resp.status} -> {location}. "
                            f"Check upstream_base ({self._cfg.upstream_base})",
                        )

                    if resp.status == 200:
                        return await resp.json()

                    err_body = await resp.text()
                    last_error = UpstreamError(resp.status, err_body)

                    if not self._is_retryable(resp.status):
                        raise last_error

                    if attempt < self._cfg.retry_attempts - 1:
                        await asyncio.sleep(self._retry_delay(resp, attempt))

            except aiohttp.ClientError as exc:
                last_error = UpstreamError(0, str(exc))
                if attempt < self._cfg.retry_attempts - 1:
                    wait = self._cfg.retry_backoff[min(attempt, len(self._cfg.retry_backoff) - 1)]
                    await asyncio.sleep(wait)

        raise last_error or UpstreamError(0, "Unknown error")
