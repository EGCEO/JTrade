# AutoTrade Bot — Base44 dev environment notes

## What this app is
A headless Python bot that monitors BSC/PancakeSwap whale swaps and auto-trades.
The core logic lives in `JTrade.so` — a **Cython-compiled** extension module
built against CPython 3.12. `run.py` imports it and calls `JTrade.main()`.

There is **no web UI**. The Base44 preview is served by `status_server.py`
(stdlib-only HTTP page on port 3000) showing bot liveness + recent logs.

## Why the bot failed to start (root causes)
1. **Missing Python dependencies.** `JTrade.so` runs Python-level imports
   (`web3`, `requests`, `dotenv`) during module init. None were installed, so
   `import JTrade` raised `ModuleNotFoundError: No module named 'requests'`.
   Fix: the compose command installs `web3 python-dotenv requests` at startup.
2. **Interactive menu + closed stdin.** `JTrade.main()` prints a mode menu and
   calls `input()`. In a non-interactive container stdin is closed, so `input()`
   raises `EOFError` and crashes the process. Fix: `start.sh` feeds choice `2`
   (auto trade) over a pipe and keeps stdin open with `tail -f /dev/null` so any
   later prompt blocks instead of hitting EOF.

## How to run
```
docker compose -f docker-compose.base44.yml up -d
```
- Service `bot`: `python:3.12-slim`, repo bind-mounted at `/app`, deps installed
  on each start, then `start.sh` runs the bot in the background + the status
  page in the foreground on port 3000.
- Healthcheck probes `http://localhost:3000/`.

## Secrets
- `PRIVATE_KEY` and `WALLET_ADDRESS` are delivered via `/run/base44/app.env`
  (compose `env_file`, last entry → always wins).
- The committed `.env` contains **placeholder** values (e.g.
  `PRIVATE_KEY=YOUR_METAMASK_PRIVATE_KEY`) plus non-secret config
  (`SC_NODE_URL`, `PANCAKE_ROUTER`, amounts, etc.) which the bot reads via
  `load_dotenv()` (override=False, so env-var secrets take precedence).
- `PRIVATE_KEY` must be valid 64-char hex (optionally `0x`-prefixed). A
  malformed value makes `eth_account.Account.from_key()` throw
  `binascii.Error: Non-hexadecimal digit found` — non-fatal (the bot keeps
  monitoring) but trade signing will fail until a valid key is supplied.

## Known non-fatal runtime warnings
- `Error sending notification: 401 Unauthorized` — the Telegram notification
  call fails (bot token / chat id invalid or missing). Does not stop the bot.

## Verify it works
```
docker compose -f docker-compose.base44.yml ps                 # (healthy)
curl -s http://localhost:3000/ | grep badge                    # RUNNING
docker compose -f docker-compose.base44.yml exec -T bot cat /tmp/bot.log  # auto trade mode + monitoring
```
