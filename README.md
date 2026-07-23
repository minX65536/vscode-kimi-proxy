# vscode-kimi-proxy

Use [Kimi K3](https://platform.moonshot.ai) (Moonshot AI) as your model in **VS Code Copilot Chat** — with visible reasoning, custom instructions, and full control over every request.

An async Python proxy that sits between VS Code and the Kimi API. It transforms `reasoning_content` into visible `<think>` blocks, injects custom instructions, retries on transient errors, and logs token usage — all with zero external dependencies beyond `aiohttp`.

[![License: BSL 1.1](https://img.shields.io/badge/License-BSL%201.1-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)

## Why?

VS Code Copilot Chat supports custom OpenAI-compatible endpoints, but Kimi's reasoning (`reasoning_content`) is invisible by default. This proxy makes it visible and gives you full control:

- **See the model's thinking** — chain-of-thought rendered as `<think>` blocks right in chat
- **Custom instructions** — prepend your own system prompt with highest priority, before IDE instructions
- **Model aliasing** — remap model names without touching VS Code settings
- **Force parameters** — override temperature, top_p, reasoning_effort on every request
- **Context budget** — automatically trim message history to avoid 400 errors
- **Tool output compression** — optional RTK integration compresses tool-call outputs in history (pytest, mypy, git, grep, cargo-test…) saving tokens on long sessions; saved bytes shown in console
- **Retry with backoff** — automatic retry on 429/5xx and network errors (pre-stream only)
- **Usage & metrics logging** — JSONL logs with token counts, TTFT, latency breakdown by message category
- **JSONC config** — human-friendly config with comments
- **Async & concurrent** — handles multiple simultaneous requests via aiohttp

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set your API key

Create a `.env` file in the project root:

```
MOONSHOT_API_KEY=sk-your-key-here
```

Or edit `kimi-proxy.json` and set `"api_key"` directly.

### 3. Run the proxy

```bash
python kimi-proxy.py
```

Or as a module:

```bash
python -m kimi_proxy
```

Or point to a different config file:

```bash
python -m kimi_proxy --config my.json
```

The proxy starts on `http://127.0.0.1:8000` by default. Exposed endpoints:

- `POST /v1/chat/completions` — main chat endpoint (SSE streaming + full responses)
- `GET /v1/models` — model list (for clients that probe it)
- `GET /health` — health check, returns `{"status": "ok"}`

### 4. Configure VS Code

In VS Code, open **Copilot Chat** → click the model picker → **Manage Models** → **Add Models** → **Custom Endpoint**.

Paste this configuration:

```json
[
    {
        "name": "KIMI",
        "vendor": "customendpoint",
        "apiKey": "any-value-proxy-overrides-it",
        "apiType": "chat-completions",
        "models": [
            {
                "id": "kimi-k3",
                "name": "kimi-k3",
                "url": "http://127.0.0.1:8000/v1",
                "maxInputTokens": 120000,
                "maxOutputTokens": 120000,
                "toolCalling": true,
                "vision": true,
                "streaming": true,
                "thinking": true,
                "parameters": {
                    "temperature": 1,
                    "override": true
                }
            }
        ]
    }
]
```

> **Notes:**
> - `apiKey` can be any placeholder — the proxy replaces it with your real key from `.env`
> - `url` must end with `/v1` — the proxy appends `/chat/completions` internally
> - After adding, select **kimi-k3** from the model picker in Copilot Chat

## Configuration

All settings live in `kimi-proxy.json` (JSONC — comments allowed):

| Key | Default | Description |
|-----|---------|-------------|
| `listen_host` | `127.0.0.1` | Bind address |
| `listen_port` | `8000` | Bind port |
| `upstream_base` | `https://api.moonshot.ai` | Moonshot API base URL (`https://api.moonshot.cn` for China) |
| `api_key` | `""` | API key directly (takes priority over env var) |
| `api_key_env` | `MOONSHOT_API_KEY` | Env var name for API key (`""` = don't override client's key) |
| `think_mode` | `inline` | How to render reasoning: `inline`, `details`, `native`, `drop` |
| `strip_think_from_history` | `true` | Remove think-blocks from history before sending |
| `custom_instructions` | `""` | Your system prompt (highest priority) |
| `force_params` | `{temperature: 0.6, top_p: 0.95}` | Override model params (shipped config sets `temperature: 1`) |
| `model_aliases` | `{}` | Client name → API name mapping (shipped config maps `kimi-k3`) |
| `console` | `true` | Master switch for pretty console output |
| `verbose` | `true` | Second console switch — output shows only when **both** are true |
| `emoji` | `auto` | Emoji in console: `auto`, `on`, `off` (auto detects VS Code terminal → off) |
| `logging_enabled` | `true` | Master switch for all JSONL file logging |
| `debug_dump_body` | `false` | Dump outgoing upstream request body to `kimi-proxy-debug.jsonl` |
| `usage_log` | `""` (off) | Token usage log file (shipped config: `kimi-proxy-usage.jsonl`) |
| `metrics_log` | `""` (off) | Latency metrics log file (shipped config: `kimi-proxy-metrics.jsonl`) |
| `usage_breakdown` | `true` | Log prompt breakdown by category |
| `usage_breakdown_log` | `""` | Separate file for breakdown (`""` = same file as `usage_log`) |
| `retry.max_attempts` | `3` | Retry attempts (1 = disabled) |
| `retry.backoff` | `[2, 4, 8]` | Backoff seconds between retries (Retry-After takes priority) |
| `context.max_tokens` | `0` | Max context tokens (0 = unlimited) |
| `context.keep_last` | `20` | Recent messages to always keep |
| `rtk.enabled` | `false` | Enable RTK tool output compression |
| `rtk.path` | `bin/rtk.exe` | Path to rtk binary (or name in PATH) |
| `rtk.timeout` | `2.0` | Seconds per rtk invocation (fallback to original on timeout) |
| `rtk.min_length` | `500` | Chars; shorter tool outputs pass through unchanged |

## Tool Output Compression (RTK)

Long tool outputs (test results, compiler errors, `grep` output) accumulate in
message history and eat tokens on every subsequent request. The proxy can
compress them via [RTK](https://github.com/rtk-ai/rtk) — a Rust CLI that
specialises in exactly this.

**How it works:**

1. Before sending upstream, the proxy walks `role: "tool"` messages
2. Each string content ≥ `rtk.min_length` chars is piped through `rtk pipe`
3. The best filter is auto-detected (pytest, mypy, git-diff, grep, cargo-test…)
4. If rtk fails, times out, or makes output bigger — the original is kept

**Setup:**

A pre-built Windows binary (`rtk v0.43.0`) is included in `bin/rtk.exe`.
To enable, edit `kimi-proxy.json`:

```jsonc
"rtk": {
  "enabled": true,          // ← flip this
  "path": "bin/rtk.exe",   // already correct
  "timeout": 2.0,
  "min_length": 500
}
```

**Console display:**

When RTK is enabled, the startup banner shows its status and binary path:

```
🗜️ RTK        ✅ on   path: bin/rtk.exe
```

Each request summary shows the number of compressed outputs and bytes saved:

```
🗜️ rtk ×3  (12.4 KB saved)
```

For other platforms, download from [RTK releases](https://github.com/rtk-ai/rtk/releases)
and point `rtk.path` at the binary.

**About RTK:**

- **Author:** Patrick Szymkowiak / [rtk-ai](https://github.com/rtk-ai)
- **License:** [Apache License 2.0](https://github.com/rtk-ai/rtk/blob/develop/LICENSE) — free for any use including commercial
- **Bundled binary:** `bin/rtk.exe` (v0.43.0, x86_64-pc-windows-msvc, SHA-256 verified)
- **Source:** [github.com/rtk-ai/rtk](https://github.com/rtk-ai/rtk)

RTK is used as an external subprocess (stdin/stdout pipe) — no code from RTK
is compiled into or linked with this project. The Apache 2.0 license permits
this use without additional requirements.

## Think Modes

| Mode | Output | Use case |
|------|--------|----------|
| `inline` | `<think>reasoning</think>` in content | VS Code renders as collapsible block |
| `details` | `<details>💭 thinking</details>` | Rich markdown environments |
| `native` | `reasoning_content` unchanged | Client handles it natively |
| `drop` | Reasoning removed entirely | Save bandwidth, don't need reasoning |

## Project Structure

```
kimi-proxy.py            # Launcher (supports --config)
kimi_proxy/
├── __init__.py          # Package init
├── __main__.py          # Entry point, banner
├── config.py            # JSONC config loading (+ .env reader)
├── console.py           # Colored console output helpers
├── thinking.py          # Think markers & state
├── instructions.py      # System prompt building
├── transform.py         # SSE & full-response transformers
├── upstream.py          # Moonshot API client with retry
├── logging_svc.py       # Usage & metrics logging
├── rtk.py               # RTK connector (tool output compression)
├── controller.py        # Request orchestration
└── server.py            # aiohttp app & routes (/v1/chat/completions, /v1/models, /health)
```

## License

This project is licensed under the **Business Source License 1.1**.

- **Free for individuals** and **companies with annual revenue below $10,000 USD**
- **Commercial use** (revenue ≥ $10,000/year) requires a separate license from **BESTNYPRO INC**
- On **2030-07-21**, the license converts to **Apache License 2.0**

See [LICENSE](LICENSE) for the full text.

## Author

[minX65536](https://github.com/minX65536)
