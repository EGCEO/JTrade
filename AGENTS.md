# ArbitrageGods Command Center (Base44 dev environment)

## What this app is
A FastAPI + SQLite web dashboard / control plane for a hybrid crypto arbitrage
system (atomic cross-DEX, flash-loan, triangular & multi-hop). It is **not** a
trading bot — it never holds private keys or signs transactions. Four external
bots (Scanner, Quant, Guardian, Execution) push data via API; the dashboard
prioritizes, scores, tracks compounding/tiers, and reflects state.

Default login: **admin / admin123** (change after first login).

## Stack
- Backend: FastAPI + SQLAlchemy + SQLite (`app/`)
- Frontend: Jinja2 templates (`app/templates/`) + vanilla JS/CSS (`app/static/`)
- Charts: Chart.js via CDN
- DB file: `data/arbitrage.db` (auto-created on startup, auto-migrated)

## Run
```
docker compose -f docker-compose.base44.yml up -d
```
- Service `web`: `python:3.12-slim`, repo bind-mounted at `/app`, installs
  `requirements.txt` on start, runs `uvicorn app.main:app --host 0.0.0.0 --port 3000 --reload`.
- Healthcheck probes `http://localhost:3000/health`.
- Live reload is on — edits to `app/` reload automatically.

## Architecture
- **4 bots**: Scanner (finds opps), Quant (net profit formula + risk), Guardian
  (simulates tx, final risk check), Execution (executes Guardian-approved opps).
- **Master controls**: Start/Pause/Stop, Emergency Kill Switch, Paper/Real toggle,
  Aggressive toggle, Auto-Compound, Withdraw, Manual Compound.
- **Net Profit Formula**: Gross Profit – (DEX fees + Flash-loan fees + Gas +
  Slippage + Price Impact + Competition haircut). Only opps above min threshold pass.
- **Risk limits**: Auto-scale with balance. Small accounts ($50–$100) strictest.
  Daily loss limit & kill switch always active, even in Aggressive Mode.
- **Network progression**: Base → Arbitrum → Optimism → Polygon → Ethereum (last).
  Unlock by real compounded profits. Scanner/execution restricted to unlocked networks.

## Key implementation notes
- **Auth**: stdlib `pbkdf2` hashing (not passlib). JWT sessions via `python-jose`.
- **Bot auth**: `Authorization: Bearer BOT_SECRET` (stored in Config table,
  user-regeneratable via /api/bot-secret/regenerate). X-API-Key backward compat.
- **Templates**: Starlette 1.7 requires `TemplateResponse(request, name, context)`.
- **`/health`** registered BEFORE the pages router catch-all `/{page}`.
- **DB migration**: `migrate_db()` in `database.py` adds missing columns via
  ALTER TABLE — non-destructive schema upgrades.
- **BotName enum**: includes legacy `calculator` (auto-migrated to `quant` on
  startup). Only ACTIVE_BOTS (scanner, quant, guardian, execution) are shown.
- **SafeJSONResponse**: converts inf/nan floats to null for JSON serialization.

## Bot API endpoints (Bearer auth)
- `GET  /api/status` (also `/webhook/status`) — mode, is_running, thresholds, risk limits, networks
- `POST /api/heartbeats` (also `/webhook/heartbeats`) — bot heartbeat
- `POST /api/opportunities` (also `/webhook/opportunities`) — push scored opportunity
- `POST /api/trades` (also `/webhook/trades`) — push trade result (updates balances)
- `POST /api/logs` (also `/webhook/logs`) — push log entry
- `GET  /api/test` — connection test

## Pages (14 total)
Dashboard, Wallet Connect, Capital & Balances, Risk Monitor, Performance,
Bot Team Control, Bot Logs, History & Trades, Compounding & Tiers,
Notifications, Onboarding, Security, Settings, Integration Guide

## Verify
```
docker compose -f docker-compose.base44.yml ps
curl -s http://localhost:3000/health
curl -s -X POST http://localhost:3000/login -H 'Content-Type: application/json' -d '{"username":"admin","password":"admin123"}'
curl -s -b jar http://localhost:3000/api/config | python3 -m json.tool
# Bot pushes with Bearer auth:
SECRET=$(curl -s -b jar http://localhost:3000/api/bot-secret | python3 -c "import sys,json;print(json.load(sys.stdin)['bot_secret'])")
curl -s -H "Authorization: Bearer $SECRET" http://localhost:3000/api/test
```

## Reporting and growth chart
- Daily Sheets uploads summarize the previous UTC calendar day after 00:30 UTC.
  The opt-in flag is persisted in Config and resumed on startup. Credentials are
  optional and only delivered via `/run/base44/app.env`; no wallet key is reused.
  Repeated exports update the existing date row instead of duplicating it.
  This scheduler requires a continuously running backend, not a closed sandbox.
- `/api/portfolio-growth` shows paper account snapshots over a 30-day window.
  New replays save `AccountSnapshot.simulated_at` (the market candle date).
  Legacy snapshots lack market dates and are explicitly labeled execution-time
  data; do not invent historical dates. Balance growth includes capital flows.
- Real activation checks prerequisites on the server and requires a fresh external
  execution heartbeat; simulator heartbeats do not establish live readiness.
  Capital deposit endpoints are ledger entries, not actual fund transfers.

## Base network configuration
- Chain ID 8453, RPC `https://mainnet.base.org` (both stored in Config, editable in Settings)
- Base router: `0x4752ba5dBc23f44D87826276bf6fd6b1C372aD24` (Uniswap V2 Router02 on Base)
- ABI: `base_router_abi.json` (standard IUniswapV2Router02 interface — same as PancakeSwap V2)
- Legacy `pancake_router_abi.json` kept for backward compat; identical interface
- Bots read chain_id + rpc_url from `/api/status` → `network_config`
- Startup auto-fixes legacy 40-char truncated base_router to the correct 42-char address

## Legacy files
`run.py`, `JTrade.so`, `start.sh`, `status_server.py`, `.env`,
`pancake_router_abi.json` are from the original AutoTrade bot and are NOT used
by this app. `base_router_abi.json` is the current ABI file.
