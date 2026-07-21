# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 BESTNYPRO INC
# Licensed under the Business Source License 1.1 — see LICENSE file

"""Loading, validation and storage of proxy configuration."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _load_dotenv() -> None:
    """Load .env file from the project root into os.environ (if not already set)."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

# ---------------------------------------------------------------------------
#  JSONC parser (strips // and /* */ comments)
# ---------------------------------------------------------------------------

def _strip_json_comments(text: str) -> str:
    """Remove single-line and block comments from JSONC text."""
    result: list[str] = []
    i = 0
    in_str = False
    esc = False
    while i < len(text):
        ch = text[i]
        if esc:
            result.append(ch)
            esc = False
        elif ch == "\\" and in_str:
            result.append(ch)
            esc = True
        elif ch == '"':
            result.append(ch)
            in_str = not in_str
        elif not in_str and ch == "/" and i + 1 < len(text) and text[i + 1] == "/":
            # single-line comment
            while i < len(text) and text[i] != "\n":
                i += 1
            continue  # newline will be appended on the next iteration
        elif not in_str and ch == "/" and i + 1 < len(text) and text[i + 1] == "*":
            # block comment
            i += 2
            while i + 1 < len(text) and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        else:
            result.append(ch)
        i += 1
    return "".join(result)


def _load_jsonc(path: Path) -> dict[str, Any]:
    """Load a JSON or JSONC file. Returns {} if the file is not found."""
    if not path.is_file():
        return {}
    raw = path.read_text(encoding="utf-8")
    cleaned = _strip_json_comments(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Error parsing {path}: {exc}") from exc


# ---------------------------------------------------------------------------
#  Default values
# ---------------------------------------------------------------------------

_DEFAULTS: dict[str, Any] = {
    "listen_host": "127.0.0.1",
    "listen_port": 8000,
    "upstream_base": "https://api.moonshot.ai",
    "api_key_env": "MOONSHOT_API_KEY",
    "force_params": {
        "temperature": 0.6,
        "top_p": 0.95,
    },
    "think_mode": "inline",          # inline | details | native | drop
    "strip_think_from_history": True,
    "model_aliases": {},
    "custom_instructions": "",        # highest-priority system instructions
    "usage_log": "",
    "console": True,                  # master switch: pretty console output
    "verbose": True,
    "metrics_log": "",
    "usage_breakdown": True,
    "usage_breakdown_log": "",
    "logging_enabled": True,          # master switch: JSONL file logging
    "retry": {
        "max_attempts": 3,
        "backoff": [2, 4, 8],
    },
    "context": {
        "max_tokens": 0,   # 0 = no limit
        "keep_last": 20,
    },
}


# ---------------------------------------------------------------------------
#  ProxyConfig — single immutable configuration object
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RetryConfig:
    max_attempts: int = 3
    backoff: list[int] = field(default_factory=lambda: [2, 4, 8])


@dataclass(frozen=True)
class ContextConfig:
    max_tokens: int = 0
    keep_last: int = 20


@dataclass(frozen=True)
class ProxyConfig:
    """Immutable proxy configuration."""

    listen_host: str = "127.0.0.1"
    listen_port: int = 8000
    upstream_base: str = "https://api.moonshot.ai"
    api_key: str = ""
    force_params: dict[str, Any] = field(default_factory=dict)
    think_mode: str = "inline"
    strip_think_from_history: bool = True
    model_aliases: dict[str, str] = field(default_factory=dict)
    custom_instructions: str = ""
    usage_log: str = ""
    console: bool = True
    verbose: bool = True
    metrics_log: str = ""
    usage_breakdown: bool = True
    usage_breakdown_log: str = ""
    logging_enabled: bool = True
    retry: RetryConfig = field(default_factory=RetryConfig)
    context: ContextConfig = field(default_factory=ContextConfig)

    # ------------------------------------------------------------------
    #  Factory
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> "ProxyConfig":
        """Load config from a JSONC file + environment variables."""
        path = Path(config_path) if config_path else Path(__file__).resolve().parent.parent / "kimi-proxy.json"
        raw = _load_jsonc(path)
        merged = {**_DEFAULTS, **raw}

        # Nested sections
        retry_raw = merged.get("retry", {})
        retry = RetryConfig(
            max_attempts=int(retry_raw.get("max_attempts", 3)),
            backoff=list(retry_raw.get("backoff", [2, 4, 8])),
        )
        ctx_raw = merged.get("context", {})
        context = ContextConfig(
            max_tokens=int(ctx_raw.get("max_tokens", 0)),
            keep_last=int(ctx_raw.get("keep_last", 20)),
        )

        # API key: config field first, then environment variable
        api_key = str(merged.get("api_key", ""))
        if not api_key:
            env_name = str(merged.get("api_key_env", "MOONSHOT_API_KEY"))
            api_key = os.environ.get(env_name, "")

        return cls(
            listen_host=str(merged["listen_host"]),
            listen_port=int(merged["listen_port"]),
            upstream_base=str(merged["upstream_base"]).rstrip("/"),
            api_key=api_key,
            force_params=dict(merged.get("force_params", {})),
            think_mode=str(merged.get("think_mode", "inline")),
            strip_think_from_history=bool(merged.get("strip_think_from_history", True)),
            model_aliases=dict(merged.get("model_aliases", {})),
            custom_instructions=str(merged.get("custom_instructions", "")),
            usage_log=str(merged.get("usage_log", "")),
            console=bool(merged.get("console", True)),
            verbose=bool(merged.get("verbose", True)),
            metrics_log=str(merged.get("metrics_log", "")),
            usage_breakdown=bool(merged.get("usage_breakdown", True)),
            usage_breakdown_log=str(merged.get("usage_breakdown_log", "")),
            logging_enabled=bool(merged.get("logging_enabled", True)),
            retry=retry,
            context=context,
        )

    # ------------------------------------------------------------------
    #  Convenience properties
    # ------------------------------------------------------------------

    @property
    def upstream_url(self) -> str:
        return f"{self.upstream_base}/v1/chat/completions"

    @property
    def retry_attempts(self) -> int:
        return self.retry.max_attempts

    @property
    def retry_backoff(self) -> list[int]:
        return self.retry.backoff

    @property
    def console_enabled(self) -> bool:
        """Console output is on only when both master switches allow it."""
        return self.console and self.verbose
