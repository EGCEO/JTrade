import os
import secrets
import math
import json
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import JSONResponse
from app.database import init_db, SessionLocal
from app.models import (
    User, Config, BotHeartbeat, TierProgress, BotName, BotState, ACTIVE_BOTS,
)
from app.auth import hash_password
from app.routers import auth, pages, api, webhooks, sim


class SafeJSONResponse(JSONResponse):
    """JSON response that converts non-finite floats (inf/nan) to null."""
    def render(self, content):
        def clean(o):
            if isinstance(o, float) and (math.isinf(o) or math.isnan(o)):
                return None
            if isinstance(o, dict):
                return {k: clean(v) for k, v in o.items()}
            if isinstance(o, list):
                return [clean(v) for v in o]
            return o
        return json.dumps(clean(content), ensure_ascii=False).encode("utf-8")


app = FastAPI(title="ArbitrageGods Command Center", default_response_class=SafeJSONResponse)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(webhooks.router)
app.include_router(pages.router)
app.include_router(api.router)
app.include_router(sim.router)


@app.on_event("startup")
def startup():
    init_db()
    db = SessionLocal()
    try:
        # Default admin user
        if not db.query(User).first():
            admin = User(username="admin", password_hash=hash_password("admin123"))
            db.add(admin)
            db.commit()
            db.refresh(admin)
            cfg = Config(user_id=admin.id)
            db.add(cfg)
            db.commit()

        # Ensure every config has a bot_secret
        for cfg in db.query(Config).all():
            if not cfg.bot_secret:
                cfg.bot_secret = secrets.token_urlsafe(32)
            # Ensure scoring config has defaults (new columns may be NULL on existing rows)
            score_defaults = {
                "score_min_net_profit_usd": 0.75,
                "score_min_expected_value_usd": 0.5,
                "score_min_execution_probability": 0.35,
                "score_failure_gas_fraction": 1.0,
                "score_gas_k": 1.8,
                "score_hop_decay": 0.85,
                "score_impact_k": 0.009,
                "score_liquidity_floor": 0.0,
                "score_success_rate_weight": 0.5,
            }
            for k, v in score_defaults.items():
                if getattr(cfg, k) is None:
                    setattr(cfg, k, v)
        db.commit()

        # Migrate legacy 'calculator' bot to 'quant'
        calc = db.query(BotHeartbeat).filter(BotHeartbeat.bot == BotName.calculator).first()
        if calc:
            quant = db.query(BotHeartbeat).filter(BotHeartbeat.bot == BotName.quant).first()
            if not quant:
                calc.bot = BotName.quant
            else:
                db.delete(calc)

        # Default bots — only the 4 active ones
        for b in ACTIVE_BOTS:
            if not db.query(BotHeartbeat).filter(BotHeartbeat.bot == b).first():
                db.add(BotHeartbeat(bot=b, state=BotState.offline, paused=False))

        # Default tier progress
        if not db.query(TierProgress).first():
            db.add(TierProgress(current_tier=1, highest_balance=0.0, networks_unlocked="base"))
        db.commit()
    finally:
        db.close()
    db = SessionLocal()
    try:
        cfg = db.query(Config).first()
        resume_sheets = bool(cfg and cfg.sheets_auto_export)
    finally:
        db.close()
    if resume_sheets:
        from app.sheets_export import start_auto_export
        start_auto_export()
