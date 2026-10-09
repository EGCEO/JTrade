# Base44 Setup Notes

## What this project is

A **Python console trading bot** (not a web app). It imports a compiled Cython
extension (`JTrade.so`) that monitors BSC whale swaps and auto-trades via
PancakeSwap. Entry point is `run.py` → `JTrade.main()` then an infinite loop.

There is **no web server and no port-3000 listener**. The browser preview will
not show a web page — the bot's output is visible via `docker compose logs -f bot`.

## Runtime requirements

- **Python 3.12** — `JTrade.so` was compiled with CPython 3.12.1 (ABI-compatible
  across 3.12.x). Do not use Python 3.13+.
- Python packages: `web3`, `python-dotenv`, `requests` (installed in the
  `Dockerfile.base44` image).
- `pancake_router_abi.json` must be present in the working directory (read by
  the compiled module at runtime).

## Stdin / menu selection

`JTrade.main()` presents an interactive menu (`1: Test buy + sell, 2: Auto trade`)
and calls `input()`. A background thread also calls `input()`. The compose command
pipes `echo 2` to stdin to auto-select "Auto trade" mode non-interactively.

## Env vars (read by the compiled module via `os.getenv`)

The compiled module reads these env var names — note they differ from the
repo's `.env` file (which uses older names like `SC_NODE_URL`, `AMOUNT_TO_BUY`,
`PROFIT_TARGET`):

| Env var             | Description                        | Default in .so                  |
|---------------------|------------------------------------|---------------------------------|
| `BSC_MAINNET_RPC`   | BSC RPC URL                        | `https://bsc-dataseed.binance.org/` |
| `PRIVATE_KEY`       | Wallet private key (secret)        | —                               |
| `WALLET_ADDRESS`    | Wallet address (secret)            | —                               |
| `PANCAKE_ROUTER`    | PancakeSwap router address         | `0x10ED43C7...256024E`          |
| `BUY_AMOUNT_BNB`    | BNB to spend per trade             | —                               |
| `MIN_TX_AMOUNT_BNB` | Min whale tx value (USD)           | —                               |
| `SLIPPAGE`          | Max slippage (%)                   | —                               |
| `TAKE_PROFIT`       | Profit target (%)                  | —                               |
| `STOP_LOSS`         | Stop loss (%)                      | —                               |
| `GAS_PRICE`         | Gas price (fetched on-chain if unset) | —                           |
| `TOKEN_ADDRESSES`   | Tokens to monitor                  | Hardcoded defaults in .so       |
| `ABI_FILE`          | ABI JSON filename                  | `pancake_router_abi.json`       |

Non-secret defaults are in `.env.base44-defaults` (compose `env_file`, first entry).
Secrets (`PRIVATE_KEY`, `WALLET_ADDRESS`) are delivered via `/run/base44/app.env`
(compose `env_file`, last entry — always wins).

## Telegram notifications

The bot sends Telegram notifications via a **hardcoded bot token** baked into
`JTrade.so`. The token is invalid (returns 401 Unauthorized). This cannot be
fixed without recompiling the module. The bot continues working despite the
notification failure.

## Secrets required for trading

Without real `PRIVATE_KEY` and `WALLET_ADDRESS` the bot starts and monitors
transactions but **cannot execute trades** (it will fail when trying to sign
transactions). Add real values from the Secrets page in the Base44 dashboard.

## How to verify

```bash
docker compose -f docker-compose.base44.yml up -d --build
docker compose -f docker-compose.base44.yml logs -f bot
```

Look for "JTrade module loaded successfully!" and "✅ Successfully connected to
BSC!" followed by transaction monitoring output. The container healthcheck
verifies the main process is alive.

## Web Dashboard (Arbitrage Gods)

A FastAPI web app (`app/main.py`) serves the dashboard on port 3000. It
provides a full SPA frontend (`app/static/`) for monitoring opportunities,
executing trades, and comparing paper vs real performance.

### Services in docker-compose.base44.yml

- **web** — FastAPI + uvicorn (port 3000, live reload). Serves the dashboard
  and all API endpoints.
- **bot** — Legacy BSC JTrade bot (compiled Cython). Runs `run.py` with
  `echo 2` piped to stdin for auto-trade mode.
- **scanner** — Base DEX Scanner Bot (`app/scanner_bot.py`). Connects to
  Base mainnet (chain ID 8453), scans V2-compatible DEX routers for cross-DEX
  and triangular arbitrage, and pushes opportunities to the dashboard via
  webhook. Runs every 15 seconds. Only 1 router (Aerodrome) is configured by
  default; add more via `SCANNER_ROUTERS=Name:0xaddr,...` env var.

### Real Execution Engine

`app/execution.py` provides `ExecutionEngine` which signs and broadcasts
real DEX trades on Base using `PRIVATE_KEY` and `WALLET_ADDRESS` from secrets.
The engine status is available at `GET /api/execution/status`. Real trades
require a mandatory 3-step confirmation flow (`POST /api/opportunities/{id}/execute`).

### Key API Endpoints

- `GET /api/performance` — Side-by-side paper vs real performance data
- `GET /api/summary` — Detailed P&L summary for paper and real trades
- `GET /api/execution/status` — Real execution engine status
- `POST /api/opportunities/{id}/execute` — Execute with 3-step confirmation
