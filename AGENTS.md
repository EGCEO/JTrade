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

## Legacy files
`run.py`, `JTrade.so`, `start.sh`, `status_server.py`, `.env` are from the
original AutoTrade bot and are NOT used by this app.
