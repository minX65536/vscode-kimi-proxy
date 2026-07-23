# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 BESTNYPRO INC
# Licensed under the Business Source License 1.1 — see LICENSE file

"""kimi_proxy — async proxy between VS Code and Kimi (Moonshot AI).

Modules:
  config         — settings loading and validation
  thinking       — reasoning markers and display modes
  instructions   — system prompt building and injection
  transform      — SSE stream and full-response transformation
  upstream       — async Moonshot API client with retry
  logging_svc    — usage, metrics and breakdown logging
  controller     — request orchestration pipeline
  server         — aiohttp HTTP server setup
  __main__       — composition root and entry point
"""

__version__ = "1.0.1"
