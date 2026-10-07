# Base44 Setup Notes

## What this project is

A **Python console trading bot** (not a web app). It imports a compiled Cython
extension (`JTrade.so`) that monitors BSC whale swaps and auto-trades via
PancakeSwap. Entry point is `run.py` → `JTrade.main()` then an infinite loop.

There is **no web server and no port-3000 listener**. The browser preview will
not show a web page — the bot's output is visible via `docker compose logs bot`.

## Runtime requirements

- **Python 3.12** — `JTrade.so` was compiled with CPython 3.12.1 (ABI-compatible
  across 3.12.x). Do not use Python 3.13+.
- Python packages: `web3`, `python-dotenv`, `requests` (installed in the
  `Dockerfile.base44` image).
- `pancake_router_abi.json` must be present in the working directory (read by
  the compiled module at runtime).

## Configuration

- Non-secret defaults live in `.env.base44-defaults` (compose `env_file`).
- The repo `.env` also has defaults with inline comments; `load_dotenv()` reads
  it at runtime but does **not** override env vars already set by compose.
- **Secrets** (`PRIVATE_KEY`, `WALLET_ADDRESS`) are delivered via
  `/run/base44/app.env` and always win (last `env_file` entry).

## How to verify

```bash
docker compose -f docker-compose.base44.yml up -d --build
docker compose -f docker-compose.base44.yml logs -f bot
```

Look for "JTrade module loaded successfully!" in the logs. Without real
credentials the bot will start but fail when it tries to interact with the
blockchain.
