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
- **Retry with backoff** — automatic retry on 429/5xx and network errors (pre-stream only)
- **Usage & metrics logging** — JSONL logs with token counts, TTFT, latency breakdown by message category
- **JSONC config** — human-friendly config with comments
- **Async & concurrent** — handles multiple simultaneous requests via aiohttp

## Quick Start

### 1. Install

```bash
pip install -r requirements.txt
```

### 2. Set your API key

```bash
export MOONSHOT_API_KEY="sk-your-key-here"
```

Or edit `kimi-proxy.json` and set `"api_key"` directly.

### 3. Run

```bash
python kimi-proxy.py
```

The proxy starts on `http://127.0.0.1:8000` by default.

### 4. Point VS Code to the proxy

In VS Code settings, set your OpenAI-compatible endpoint to:

```
http://127.0.0.1:8000/v1
```

Use any model name — the proxy will route it to Kimi.

## Configuration

All settings live in `kimi-proxy.json` (JSONC — comments allowed):

| Key | Default | Description |
|-----|---------|-------------|
| `listen_host` | `127.0.0.1` | Bind address |
| `listen_port` | `8000` | Bind port |
| `upstream_base` | `https://api.moonshot.ai` | Moonshot API base URL |
| `api_key_env` | `MOONSHOT_API_KEY` | Env var name for API key |
| `think_mode` | `inline` | How to render reasoning: `inline`, `details`, `native`, `drop` |
| `strip_think_from_history` | `true` | Remove think-blocks from history before sending |
| `custom_instructions` | `""` | Your system prompt (highest priority) |
| `force_params` | `{temperature: 1, top_p: 0.95}` | Override model params |
| `model_aliases` | `{"kimi-k3": "kimi-k3"}` | Client name → API name mapping |
| `verbose` | `true` | Console output |
| `usage_log` | `kimi-proxy-usage.jsonl` | Token usage log file |
| `metrics_log` | `kimi-proxy-metrics.jsonl` | Latency metrics log file |
| `usage_breakdown` | `true` | Log prompt breakdown by category |
| `retry.max_attempts` | `3` | Retry attempts (1 = disabled) |
| `retry.backoff` | `[2, 4, 8]` | Backoff seconds between retries |
| `context.max_tokens` | `0` | Max context tokens (0 = unlimited) |
| `context.keep_last` | `20` | Recent messages to always keep |

## Think Modes

| Mode | Output | Use case |
|------|--------|----------|
| `inline` | `<think>reasoning</think>` in content | VS Code renders as collapsible block |
| `details` | `<details>💭 thinking</details>` | Rich markdown environments |
| `native` | `reasoning_content` unchanged | Client handles it natively |
| `drop` | Reasoning removed entirely | Save bandwidth, don't need reasoning |

## Project Structure

```
kimi_proxy/
├── __init__.py          # Package init
├── __main__.py          # Entry point, banner
├── config.py            # JSONC config loading
├── thinking.py          # Think markers & state
├── instructions.py      # System prompt building
├── transform.py         # SSE & full-response transformers
├── upstream.py          # Moonshot API client with retry
├── logging_svc.py       # Usage & metrics logging
├── controller.py        # Request orchestration
└── server.py            # aiohttp app & routes
```

## License

This project is licensed under the **Business Source License 1.1**.

- **Free for individuals** and **companies with annual revenue below $10,000 USD**
- **Commercial use** (revenue ≥ $10,000/year) requires a separate license from **BESTNYPRO INC**
- On **2030-07-21**, the license converts to **Apache License 2.0**

See [LICENSE](LICENSE) for the full text.

## Author

[minX65536](https://github.com/minX65536)
