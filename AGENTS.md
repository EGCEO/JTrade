# Arbitrage Command Center – Hybrid Engine (Base44 dev environment)

## What this app is
A FastAPI + SQLite web dashboard / control plane for a hybrid crypto arbitrage
system (inventory + atomic flash-loan style). It is **not** a trading bot — it
never holds private keys or signs transactions. External bots (Scanner,
Calculator, Execution) push data via webhooks; the dashboard prioritizes,
scores, tracks compounding/tiers, and reflects state.

Default login: **admin / admin123** (change after first login).

## Stack
- Backend: FastAPI + SQLAlchemy + SQLite (`app/`)
- Frontend: Jinja2 templates (`app/templates/`) + vanilla JS/CSS (`app/static/`)
- DB file: `data/arbitrage.db` (auto-created on startup)

## Run
```
docker compose -f docker-compose.base44.yml up -d
```
- Service `web`: `python:3.12-slim`, repo bind-mounted at `/app`, installs
  `requirements.txt` on start, runs `uvicorn app.main:app --host 0.0.0.0 --port 3000 --reload`.
- Healthcheck probes `http://localhost:3000/health`.
- Live reload is on — edits to `app/` reload automatically.

## Key implementation notes
- **Auth**: stdlib `pbkdf2` hashing (not passlib — passlib+bcrypt>=4 crashes on
  `detect_wrap_bug`). JWT sessions via `python-jose`.
- **Templates**: Starlette 1.7 requires `TemplateResponse(request, name, context)`
  (request first, NOT the old `TemplateResponse(name, context)`).
- **`/health`** is registered BEFORE the pages router, otherwise the pages
  catch-all `/{page}` shadows it.
- **Prioritization engine** (`app/prioritization.py`): faithful to the spec —
  net profit after all costs, account-balance-scaled thresholds, aggressive
  mode (×0.4 profit floor, ×1.8 size, 4 hops), scoring `net*1000 + conf*10 - hops*5`,
  sorted descending. Risk checks enforce min-profit, max-risk-%, daily-loss-limit.
- **Tiers/levels**: account levels 1–4 by balance; network tiers Base → Arbitrum
  → Optimism → Polygon → Ethereum (last). Opportunities on locked networks are
  rejected by the webhook.

## Webhook endpoints (for external bots)
- `GET  /webhook/status` — read mode, thresholds, risk limits, unlocked networks, routers
- `POST /webhook/opportunities` — push opportunity (auto-scored & filtered by network/threshold)
- `POST /webhook/heartbeats` — push bot heartbeat/state
- `POST /webhook/trades` — push execution result (updates balances)
- `POST /webhook/balance` — update paper/real balance
- `POST /webhook/insights` — push insight
Set `WEBHOOK_API_KEY` env to require `X-API-Key` on POST endpoints.

## ⚠️ Security
The user exposed a real MetaMask private key in chat. The app NEVER stores
private keys. The dashboard only manages mode flags, thresholds, and logs.
Keys live only in the external Execution Bot.

## Verify
```
docker compose -f docker-compose.base44.yml ps                 # (healthy)
curl -s http://localhost:3000/health                           # {"status":"ok"}
curl -s -X POST http://localhost:3000/login ...                 # admin/admin123
curl -s -b jar http://localhost:3000/api/config | python3 -m json.tool
curl -s -X POST http://localhost:3000/webhook/opportunities ... # push opp
```

## Legacy files
`run.py`, `JTrade.so`, `start.sh`, `status_server.py`, `.env` are from the
original AutoTrade bot and are NOT used by this app. They remain in the repo
for reference.
