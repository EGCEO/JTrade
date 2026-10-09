import json
import os
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database import engine, get_db, Base, SessionLocal
from app.models import (User, Config, Opportunity, TradeLog, BotHeartbeat,
                        AccountSnapshot, TierProgress, InsightLog)
from app.auth import (hash_password, verify_password, create_token,
                      get_current_user, verify_webhook_key)
from app.prioritization import (get_tier, get_next_tier, get_unlocked_networks,
                                get_current_thresholds, calculate_priority_score,
                                passes_risk_checks, TIERS)
from app.execution import ExecutionEngine

# ── Tables ──────────────────────────────────────────────────────────────────
Base.metadata.create_all(bind=engine)

DEFAULT_CONFIG = {
    "starting_capital": 50,
    "current_paper_balance": 50,
    "current_real_balance": 0,
    "paper_mode": True,
    "real_mode": False,
    "aggressive_mode": False,
    "compounding_mode": True,
    "min_profit_normal": 0.75,
    "min_profit_aggressive": 0.30,
    "max_risk_normal": 0.12,
    "max_risk_aggressive": 0.20,
    "daily_loss_limit": 0.05,
    "max_open_exposure": 0.30,
    "base_router": "0xd6145b2D3F379919E8CdEda7B97e37c4b2Ca9c40",
    "eth_router": "0x23617e59A592549b2A4Bf75d73ff6711cD0b29De85",
    "cex_fee_pct": 0.001,
    "dex_fee_pct": 0.003,
    "estimated_gas_usd": 5,
    "slippage_pct": 0.005,
    "flash_loan_fee_pct": 0.0009,
    "transfer_cost_usd": 1,
    "webhook_api_key": os.environ.get("WEBHOOK_API_KEY", "dev-webhook-key"),
    "session_token": "",
    "base_rpc_url": os.environ.get("BASE_RPC_URL", "https://mainnet.base.org"),
    "base_chain_id": 8453,
}


def seed_db():
    db = SessionLocal()
    try:
        # Seed config
        for key, val in DEFAULT_CONFIG.items():
            if not db.query(Config).filter(Config.key == key).first():
                db.add(Config(key=key, value=json.dumps(val)))
        # Seed/sync admin user
        admin_username = os.environ.get("ADMIN_USERNAME", "admin")
        admin_pw = os.environ.get("ADMIN_PASSWORD", "admin123")
        existing = db.query(User).first()
        if not existing:
            db.add(User(username=admin_username, hashed_password=hash_password(admin_pw)))
        else:
            existing.username = admin_username
            existing.hashed_password = hash_password(admin_pw)
        # Seed bots
        for name in ["scanner", "calculator", "executor"]:
            if not db.query(BotHeartbeat).filter(BotHeartbeat.bot_name == name).first():
                db.add(BotHeartbeat(bot_name=name, status="offline"))
        # Seed tier progress
        if not db.query(TierProgress).first():
            db.add(TierProgress(current_tier=0, paper_balance=50, real_balance=0))
        # Seed account snapshot
        if not db.query(AccountSnapshot).first():
            db.add(AccountSnapshot(mode="paper", balance=50, starting_capital=50))
        db.commit()
    finally:
        db.close()


seed_db()

# ── Pydantic Schemas ─────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str


class ConfigUpdate(BaseModel):
    settings: dict


class ModeToggle(BaseModel):
    enabled: bool
    confirmation: Optional[str] = None  # required for real mode


class OpportunityPush(BaseModel):
    pair: str
    network: str
    style: str = "inventory"
    buy_venue: str
    sell_venue: str
    buy_price: float = 0
    sell_price: float = 0
    gross_profit: float = 0
    estimated_costs: float = 0
    net_profit: float = 0
    confidence: float = 50
    hops: int = 1


class TradeLogPush(BaseModel):
    opportunity_id: Optional[int] = None
    mode: str = "paper"
    style: str = "inventory"
    network: str = "base"
    pair: str = ""
    expected_profit: float = 0
    actual_profit: float = 0
    status: str = "success"
    buy_cost: float = 0
    sell_proceeds: float = 0
    fees: float = 0
    gas: float = 0
    slippage: float = 0
    net_result: float = 0
    notes: str = ""


class HeartbeatPush(BaseModel):
    status: str = "running"
    last_action: str = ""
    error_message: str = ""


class BulkActionRequest(BaseModel):
    ids: list[int]


class BalanceUpdate(BaseModel):
    mode: str = "paper"
    balance: float = 0


class ExecuteRequest(BaseModel):
    confirmation_step1: bool = False  # Reviewed trade details
    confirmation_step2: bool = False  # Acknowledged risks
    confirmation_text: str = ""       # Must type "EXECUTE"


# ── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="Arbitrage Gods")

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def cfg_get(db: Session, key: str, default=None):
    row = db.query(Config).filter(Config.key == key).first()
    if not row:
        return default
    try:
        return json.loads(row.value)
    except (json.JSONDecodeError, TypeError):
        return row.value


def cfg_set(db: Session, key: str, value):
    row = db.query(Config).filter(Config.key == key).first()
    if row:
        row.value = json.dumps(value)
    else:
        db.add(Config(key=key, value=json.dumps(value)))
    db.commit()


def cfg_all(db: Session) -> dict:
    rows = db.query(Config).all()
    out = {}
    for r in rows:
        try:
            out[r.key] = json.loads(r.value)
        except (json.JSONDecodeError, TypeError):
            out[r.key] = r.value
    return out


# ── Health ───────────────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# ── Auth ─────────────────────────────────────────────────────────────────────
@app.post("/api/auth/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username).first()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token()
    cfg_set(db, "session_token", token)
    return {"token": token, "username": user.username}


@app.get("/api/auth/me")
def me(user: User = Depends(get_current_user)):
    return {"username": user.username}


# ── Config ────────────────────────────────────────────────────────────────────
@app.get("/api/config")
def get_config(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return cfg_all(db)


@app.put("/api/config")
def update_config(req: ConfigUpdate, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    for key, val in req.settings.items():
        # Never allow writing session_token or webhook_api_key via this endpoint
        if key in ("session_token", "webhook_api_key"):
            continue
        cfg_set(db, key, val)
    return {"status": "updated", "config": cfg_all(db)}


# ── Mode (for external bots) ─────────────────────────────────────────────────
@app.get("/api/mode")
def get_mode(db: Session = Depends(get_db)):
    """Public endpoint for external bots to read current mode and thresholds."""
    c = cfg_all(db)
    balance = c.get("current_paper_balance", 0) if c.get("paper_mode", True) else c.get("current_real_balance", 0)
    is_aggressive = c.get("aggressive_mode", False)
    min_profit, max_size_pct, max_hops, allow_more = get_current_thresholds(balance, is_aggressive)
    tier = get_tier(balance)
    return {
        "paper_mode": c.get("paper_mode", True),
        "real_mode": c.get("real_mode", False),
        "aggressive_mode": is_aggressive,
        "compounding_mode": c.get("compounding_mode", True),
        "account_balance": balance,
        "tier": tier["level"],
        "unlocked_networks": get_unlocked_networks(balance),
        "thresholds": {
            "min_profit": min_profit,
            "max_size_percent": max_size_pct,
            "max_hops": max_hops,
            "allow_more_pairs": allow_more,
            "daily_loss_limit": c.get("daily_loss_limit", 0.05),
            "max_open_exposure": c.get("max_open_exposure", 0.30),
        },
        "routers": {
            "base": c.get("base_router"),
            "ethereum": c.get("eth_router"),
        },
    }


@app.post("/api/mode/aggressive")
def toggle_aggressive(req: ModeToggle, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    cfg_set(db, "aggressive_mode", req.enabled)
    return {"aggressive_mode": req.enabled}


@app.post("/api/mode/compounding")
def toggle_compounding(req: ModeToggle, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    cfg_set(db, "compounding_mode", req.enabled)
    return {"compounding_mode": req.enabled}


@app.post("/api/mode/real")
def toggle_real(req: ModeToggle, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    if req.enabled and req.confirmation != "I UNDERSTAND THE RISKS":
        raise HTTPException(status_code=400,
                            detail="Real mode requires confirmation: 'I UNDERSTAND THE RISKS'")
    cfg_set(db, "real_mode", req.enabled)
    if req.enabled:
        cfg_set(db, "paper_mode", False)
    else:
        cfg_set(db, "paper_mode", True)
    return {"real_mode": req.enabled, "paper_mode": not req.enabled}


# ── Active Trades Board ───────────────────────────────────────────────────────
@app.get("/api/active")
def get_active_board(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Return active trades, pending opportunities, and confirmation queue."""
    # Pending opportunities (not yet evaluated by the system)
    pending_opps = db.query(Opportunity).filter(
        Opportunity.status == "pending"
    ).order_by(desc(Opportunity.priority_score)).all()

    # Approved opportunities (waiting for confirmation / execution)
    waiting_opps = db.query(Opportunity).filter(
        Opportunity.status == "approved"
    ).order_by(desc(Opportunity.priority_score)).all()

    # Active trades (in-progress, not yet completed)
    active_trades = db.query(TradeLog).filter(
        TradeLog.status == "pending"
    ).order_by(desc(TradeLog.created_at)).all()

    return {
        "active_trades": [_trade_dict(t) for t in active_trades],
        "pending_opportunities": [_opp_dict(o) for o in pending_opps],
        "waiting_confirmation": [_opp_dict(o) for o in waiting_opps],
        "counts": {
            "active_trades": len(active_trades),
            "pending_opportunities": len(pending_opps),
            "waiting_confirmation": len(waiting_opps),
        },
    }


# ── Chart Data (real-time profit & activity) ──────────────────────────────────
@app.get("/api/chart-data")
def get_chart_data(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Return time-series P&L and trade activity for the real-time chart."""
    trades = db.query(TradeLog).filter(
        TradeLog.status == "success"
    ).order_by(TradeLog.created_at).all()

    paper_trades = [t for t in trades if t.mode == "paper"]
    real_trades = [t for t in trades if t.mode == "real"]

    def _build_series(trade_list):
        cumulative = 0
        points = []
        for i, t in enumerate(trade_list):
            cumulative += t.net_result
            points.append({
                "index": i + 1,
                "timestamp": t.created_at.isoformat() if t.created_at else None,
                "cumulative_pnl": round(cumulative, 4),
                "net_result": round(t.net_result, 4),
                "pair": t.pair,
                "network": t.network,
            })
        return points

    return {
        "paper": _build_series(paper_trades),
        "real": _build_series(real_trades),
        "paper_count": len(paper_trades),
        "real_count": len(real_trades),
    }


# ── Opportunities ─────────────────────────────────────────────────────────────
@app.get("/api/opportunities")
def list_opportunities(status: Optional[str] = None, limit: int = 100,
                       db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(Opportunity).order_by(desc(Opportunity.priority_score))
    if status:
        q = q.filter(Opportunity.status == status)
    opps = q.limit(limit).all()
    return [_opp_dict(o) for o in opps]


@app.post("/api/opportunities")
def push_opportunity(opp: OpportunityPush, request: Request,
                     db: Session = Depends(get_db)):
    """Webhook endpoint for Scanner Bot to push discovered opportunities."""
    api_key = request.headers.get("X-API-Key", "")
    if not verify_webhook_key(api_key, db):
        raise HTTPException(status_code=401, detail="Invalid API key")
    c = cfg_all(db)
    balance = c.get("current_paper_balance", 0) if c.get("paper_mode", True) else c.get("current_real_balance", 0)
    is_aggressive = c.get("aggressive_mode", False)
    min_profit, _, max_hops, _ = get_current_thresholds(balance, is_aggressive)
    # Keep as pending for manual review via dashboard
    status_val = "pending"
    score = calculate_priority_score(opp.net_profit, opp.confidence, opp.hops)
    row = Opportunity(
        pair=opp.pair, network=opp.network, style=opp.style,
        buy_venue=opp.buy_venue, sell_venue=opp.sell_venue,
        buy_price=opp.buy_price, sell_price=opp.sell_price,
        gross_profit=opp.gross_profit, estimated_costs=opp.estimated_costs,
        net_profit=opp.net_profit, confidence=opp.confidence, hops=opp.hops,
        status=status_val, priority_score=score,
    )
    db.add(row)
    db.commit()
    return {"id": row.id, "status": status_val, "priority_score": score}


def _opp_dict(o: Opportunity) -> dict:
    return {
        "id": o.id, "pair": o.pair, "network": o.network, "style": o.style,
        "buy_venue": o.buy_venue, "sell_venue": o.sell_venue,
        "buy_price": o.buy_price, "sell_price": o.sell_price,
        "gross_profit": o.gross_profit, "estimated_costs": o.estimated_costs,
        "net_profit": o.net_profit, "confidence": o.confidence, "hops": o.hops,
        "status": o.status, "priority_score": o.priority_score,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "executed_at": o.executed_at.isoformat() if o.executed_at else None,
    }


# ── Bulk Opportunity Actions ──────────────────────────────────────────────────
@app.post("/api/opportunities/bulk-approve")
def bulk_approve_opportunities(req: BulkActionRequest, db: Session = Depends(get_db),
                               user: User = Depends(get_current_user)):
    updated = 0
    for oid in req.ids:
        opp = db.query(Opportunity).filter(Opportunity.id == oid).first()
        if opp and opp.status == "pending":
            opp.status = "approved"
            updated += 1
    db.commit()
    return {"approved": updated}


@app.post("/api/opportunities/bulk-reject")
def bulk_reject_opportunities(req: BulkActionRequest, db: Session = Depends(get_db),
                              user: User = Depends(get_current_user)):
    updated = 0
    for oid in req.ids:
        opp = db.query(Opportunity).filter(Opportunity.id == oid).first()
        if opp and opp.status == "pending":
            opp.status = "rejected"
            updated += 1
    db.commit()
    return {"rejected": updated}


# ── Trades ────────────────────────────────────────────────────────────────────
@app.get("/api/trades")
def list_trades(mode: Optional[str] = None, status: Optional[str] = None, limit: int = 100,
                db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(TradeLog).order_by(desc(TradeLog.created_at))
    if mode:
        q = q.filter(TradeLog.mode == mode)
    if status:
        q = q.filter(TradeLog.status == status)
    trades = q.limit(limit).all()
    return [_trade_dict(t) for t in trades]


@app.post("/api/trades")
def log_trade(trade: TradeLogPush, request: Request, db: Session = Depends(get_db)):
    """Webhook endpoint for Execution Bot to log results."""
    api_key = request.headers.get("X-API-Key", "")
    if not verify_webhook_key(api_key, db):
        raise HTTPException(status_code=401, detail="Invalid API key")
    row = TradeLog(
        opportunity_id=trade.opportunity_id, mode=trade.mode, style=trade.style,
        network=trade.network, pair=trade.pair,
        expected_profit=trade.expected_profit, actual_profit=trade.actual_profit,
        status=trade.status, buy_cost=trade.buy_cost, sell_proceeds=trade.sell_proceeds,
        fees=trade.fees, gas=trade.gas, slippage=trade.slippage,
        net_result=trade.net_result, notes=trade.notes,
    )
    db.add(row)
    # Update balance
    if trade.status == "success" and trade.net_result != 0:
        balance_key = "current_paper_balance" if trade.mode == "paper" else "current_real_balance"
        current = cfg_get(db, balance_key, 0)
        cfg_set(db, balance_key, current + trade.net_result)
        db.add(AccountSnapshot(
            mode=trade.mode,
            balance=current + trade.net_result,
            starting_capital=cfg_get(db, "starting_capital", 50),
        ))
    # Mark opportunity as executed
    if trade.opportunity_id:
        opp = db.query(Opportunity).filter(Opportunity.id == trade.opportunity_id).first()
        if opp:
            opp.status = "executed"
            opp.executed_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": row.id, "status": "logged"}


def _trade_dict(t: TradeLog) -> dict:
    return {
        "id": t.id, "opportunity_id": t.opportunity_id, "mode": t.mode,
        "style": t.style, "network": t.network, "pair": t.pair,
        "expected_profit": t.expected_profit, "actual_profit": t.actual_profit,
        "status": t.status, "buy_cost": t.buy_cost, "sell_proceeds": t.sell_proceeds,
        "fees": t.fees, "gas": t.gas, "slippage": t.slippage,
        "net_result": t.net_result, "notes": t.notes,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


# ── Bots ──────────────────────────────────────────────────────────────────────
@app.get("/api/bots")
def get_bots(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    bots = db.query(BotHeartbeat).all()
    now = datetime.now(timezone.utc)
    result = []
    for b in bots:
        is_stale = (b.last_heartbeat and
                    (now - b.last_heartbeat.replace(tzinfo=timezone.utc)).total_seconds() > 60)
        display_status = "offline" if is_stale and b.status == "running" else b.status
        result.append({
            "bot_name": b.bot_name, "status": display_status,
            "last_heartbeat": b.last_heartbeat.isoformat() if b.last_heartbeat else None,
            "last_action": b.last_action, "error_message": b.error_message,
        })
    return result


@app.post("/api/bots/{name}/heartbeat")
def push_heartbeat(name: str, hb: HeartbeatPush, request: Request,
                   db: Session = Depends(get_db)):
    """Webhook endpoint for bots to push heartbeats."""
    api_key = request.headers.get("X-API-Key", "")
    if not verify_webhook_key(api_key, db):
        raise HTTPException(status_code=401, detail="Invalid API key")
    bot = db.query(BotHeartbeat).filter(BotHeartbeat.bot_name == name).first()
    if not bot:
        bot = BotHeartbeat(bot_name=name)
        db.add(bot)
    bot.status = hb.status
    bot.last_heartbeat = datetime.now(timezone.utc)
    bot.last_action = hb.last_action
    bot.error_message = hb.error_message
    db.commit()
    return {"status": "ok"}


@app.post("/api/bots/{name}/test-heartbeat")
def test_heartbeat(name: str, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """Send a test heartbeat to check if a bot is reachable. Authenticated (admin only)."""
    bot = db.query(BotHeartbeat).filter(BotHeartbeat.bot_name == name).first()
    if not bot:
        bot = BotHeartbeat(bot_name=name)
        db.add(bot)
    bot.status = "running"
    bot.last_heartbeat = datetime.now(timezone.utc)
    bot.last_action = "Test heartbeat from dashboard"
    bot.error_message = ""
    db.commit()
    return {"bot_name": name, "status": "running", "message": "Test heartbeat sent"}


@app.post("/api/bots/{name}/pause")
def pause_bot(name: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    bot = db.query(BotHeartbeat).filter(BotHeartbeat.bot_name == name).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    bot.status = "paused"
    db.commit()
    return {"bot_name": name, "status": "paused"}


@app.post("/api/bots/{name}/resume")
def resume_bot(name: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    bot = db.query(BotHeartbeat).filter(BotHeartbeat.bot_name == name).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    bot.status = "running"
    db.commit()
    return {"bot_name": name, "status": "running"}


# ── Account ───────────────────────────────────────────────────────────────────
@app.get("/api/account")
def get_account(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = cfg_all(db)
    paper_balance = c.get("current_paper_balance", 0)
    real_balance = c.get("current_real_balance", 0)
    starting = c.get("starting_capital", 50)

    # Compounding stats
    paper_return = ((paper_balance - starting) / starting * 100) if starting else 0
    real_return = ((real_balance - starting) / starting * 100) if starting else 0

    # Daily/weekly stats from trade logs
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)

    paper_trades = db.query(TradeLog).filter(TradeLog.mode == "paper").all()
    real_trades = db.query(TradeLog).filter(TradeLog.mode == "real").all()

    def _stats(trades, since=None):
        if since:
            trades = [t for t in trades if t.created_at and t.created_at.replace(tzinfo=timezone.utc) >= since]
        wins = [t for t in trades if t.status == "success" and t.net_result > 0]
        losses = [t for t in trades if t.status == "success" and t.net_result < 0]
        total_pnl = sum(t.net_result for t in trades if t.status == "success")
        win_rate = (len(wins) / len(trades) * 100) if trades else 0
        return {"total_trades": len(trades), "wins": len(wins), "losses": len(losses),
                "total_pnl": total_pnl, "win_rate": win_rate}

    return {
        "starting_capital": starting,
        "paper_balance": paper_balance,
        "real_balance": real_balance,
        "paper_return_pct": paper_return,
        "real_return_pct": real_return,
        "paper_stats": {
            "all": _stats(paper_trades),
            "daily": _stats(paper_trades, day_ago),
            "weekly": _stats(paper_trades, week_ago),
        },
        "real_stats": {
            "all": _stats(real_trades),
            "daily": _stats(real_trades, day_ago),
            "weekly": _stats(real_trades, week_ago),
        },
    }


@app.post("/api/account/balance")
def update_balance(req: BalanceUpdate, request: Request, db: Session = Depends(get_db)):
    """Webhook endpoint to update balance."""
    api_key = request.headers.get("X-API-Key", "")
    if not verify_webhook_key(api_key, db):
        raise HTTPException(status_code=401, detail="Invalid API key")
    key = "current_paper_balance" if req.mode == "paper" else "current_real_balance"
    cfg_set(db, key, req.balance)
    db.add(AccountSnapshot(mode=req.mode, balance=req.balance,
                            starting_capital=cfg_get(db, "starting_capital", 50)))
    db.commit()
    return {"status": "updated", "mode": req.mode, "balance": req.balance}


@app.get("/api/account/snapshots")
def get_snapshots(mode: Optional[str] = None, limit: int = 50,
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(AccountSnapshot).order_by(desc(AccountSnapshot.timestamp))
    if mode:
        q = q.filter(AccountSnapshot.mode == mode)
    snaps = q.limit(limit).all()
    return [{"id": s.id, "mode": s.mode, "balance": s.balance,
             "starting_capital": s.starting_capital,
             "timestamp": s.timestamp.isoformat() if s.timestamp else None}
            for s in snaps]


# ── Tiers ─────────────────────────────────────────────────────────────────────
@app.get("/api/tiers")
def get_tiers(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = cfg_all(db)
    paper_balance = c.get("current_paper_balance", 0)
    real_balance = c.get("current_real_balance", 0)
    # Use paper balance for tier determination (or real if in real mode)
    balance = real_balance if c.get("real_mode", False) else paper_balance
    current = get_tier(balance)
    nxt = get_next_tier(balance)
    return {
        "current_tier": current["level"],
        "current_tier_name": current["name"],
        "current_tier_description": current["description"],
        "unlocked_networks": get_unlocked_networks(balance),
        "balance": balance,
        "next_tier": nxt["name"] if nxt else None,
        "next_tier_requirement": f"Reach ${nxt['min_balance']} balance" if nxt else "Maximum tier reached",
        "progress_to_next": min(100, (balance / nxt["min_balance"] * 100)) if nxt else 100,
        "all_tiers": TIERS,
    }


# ── Insights ──────────────────────────────────────────────────────────────────
@app.get("/api/insights")
def get_insights(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    trades = db.query(TradeLog).filter(TradeLog.status == "success").all()
    insights = []

    # Win rate by pair
    pair_stats = {}
    for t in trades:
        if t.pair not in pair_stats:
            pair_stats[t.pair] = {"wins": 0, "losses": 0, "total_pnl": 0}
        if t.net_result > 0:
            pair_stats[t.pair]["wins"] += 1
        else:
            pair_stats[t.pair]["losses"] += 1
        pair_stats[t.pair]["total_pnl"] += t.net_result

    for pair, stats in sorted(pair_stats.items(), key=lambda x: x[1]["total_pnl"], reverse=True):
        total = stats["wins"] + stats["losses"]
        insights.append({
            "insight_type": "pair_performance",
            "pair": pair,
            "metric": "win_rate",
            "value": (stats["wins"] / total * 100) if total else 0,
            "notes": f"Total P&L: ${stats['total_pnl']:.2f} across {total} trades",
        })

    # Average slippage
    slippages = [t.slippage for t in trades if t.slippage != 0]
    if slippages:
        insights.append({
            "insight_type": "slippage",
            "metric": "average_slippage",
            "value": sum(slippages) / len(slippages),
            "notes": f"Across {len(slippages)} trades with slippage data",
        })

    # Best performing network
    network_stats = {}
    for t in trades:
        if t.network not in network_stats:
            network_stats[t.network] = {"count": 0, "pnl": 0}
        network_stats[t.network]["count"] += 1
        network_stats[t.network]["pnl"] += t.net_result
    for net, stats in sorted(network_stats.items(), key=lambda x: x[1]["pnl"], reverse=True):
        insights.append({
            "insight_type": "network_performance",
            "network": net,
            "metric": "total_pnl",
            "value": stats["pnl"],
            "notes": f"{stats['count']} trades on {net}",
        })

    # Style comparison
    style_stats = {}
    for t in trades:
        if t.style not in style_stats:
            style_stats[t.style] = {"count": 0, "pnl": 0}
        style_stats[t.style]["count"] += 1
        style_stats[t.style]["pnl"] += t.net_result
    for style, stats in style_stats.items():
        insights.append({
            "insight_type": "style_comparison",
            "metric": "total_pnl",
            "value": stats["pnl"],
            "notes": f"{style}: {stats['count']} trades, ${stats['pnl']:.2f} P&L",
        })

    return insights


# ── Execution Engine ──────────────────────────────────────────────────────────
_executor = ExecutionEngine()


@app.get("/api/execution/status")
def get_execution_status(user: User = Depends(get_current_user)):
    """Return real execution engine status (wallet, connection, balance)."""
    return _executor.get_status()


# ── Execute Opportunity (3-step confirmation) ────────────────────────────────
@app.post("/api/opportunities/{opp_id}/execute")
def execute_opportunity(opp_id: int, req: ExecuteRequest,
                        db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    """Execute an approved opportunity. Requires 3-step confirmation for real trades."""
    # ── Step 1: Review ──
    if not req.confirmation_step1:
        raise HTTPException(status_code=400,
                            detail="Step 1 incomplete: Review the trade details first.")
    # ── Step 2: Risk acknowledgment ──
    if not req.confirmation_step2:
        raise HTTPException(status_code=400,
                            detail="Step 2 incomplete: Acknowledge the risks first.")
    # ── Step 3: Typed confirmation ──
    if req.confirmation_text != "EXECUTE":
        raise HTTPException(status_code=400,
                            detail="Step 3 incomplete: Type EXECUTE to confirm.")

    opp = db.query(Opportunity).filter(Opportunity.id == opp_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    if opp.status not in ("approved", "pending"):
        raise HTTPException(status_code=400,
                            detail=f"Opportunity is {opp.status}, cannot execute.")

    c = cfg_all(db)
    is_real = c.get("real_mode", False)
    is_aggressive = c.get("aggressive_mode", False)
    balance = c.get("current_real_balance", 0) if is_real else c.get("current_paper_balance", 0)

    # ── Risk gate ──
    trade_size = opp.net_profit  # use net profit as proxy for trade size
    passed, reason = passes_risk_checks(
        opp.net_profit, trade_size, balance, is_aggressive, 0, c)
    if not passed:
        raise HTTPException(status_code=400, detail=f"Risk check failed: {reason}")

    mode_str = "real" if is_real else "paper"

    if is_real:
        # ── Real execution via on-chain engine ──
        if not _executor.is_configured():
            raise HTTPException(status_code=400,
                                detail="Real execution not configured. "
                                       "Set PRIVATE_KEY and WALLET_ADDRESS in Secrets.")
        result = _executor.execute_arbitrage(opp, c)
        status = "success" if result.get("success") else "failed"
        net = result.get("net_result", 0) if result.get("success") else 0
        gas = result.get("gas_cost_usd", 0) if result.get("success") else 0
        notes = json.dumps(result) if not result.get("success") else \
                f"tx: {result.get('legs', [{}])[0].get('tx_hash', 'n/a')}"
    else:
        # ── Paper execution (simulated) ──
        net = opp.net_profit
        gas = c.get("estimated_gas_usd", 5)
        fees = opp.estimated_costs
        status = "success"
        notes = "Paper execution — simulated"

    # Log the trade
    row = TradeLog(
        opportunity_id=opp.id, mode=mode_str, style=opp.style,
        network=opp.network, pair=opp.pair,
        expected_profit=opp.net_profit, actual_profit=net,
        status=status, buy_cost=opp.buy_price, sell_proceeds=opp.sell_price,
        fees=opp.estimated_costs, gas=gas, slippage=0,
        net_result=net, notes=notes,
    )
    db.add(row)

    # Update balance
    if status == "success" and net != 0:
        balance_key = "current_real_balance" if is_real else "current_paper_balance"
        current = cfg_get(db, balance_key, 0)
        cfg_set(db, balance_key, current + net)
        db.add(AccountSnapshot(
            mode=mode_str, balance=current + net,
            starting_capital=cfg_get(db, "starting_capital", 50),
        ))

    # Mark opportunity as executed
    opp.status = "executed"
    opp.executed_at = datetime.now(timezone.utc)
    db.commit()

    return {
        "id": row.id, "status": status, "mode": mode_str,
        "net_result": net, "gas": gas,
        "execution_result": result if is_real else None,
    }


# ── Performance (side-by-side paper vs real) ──────────────────────────────────
@app.get("/api/performance")
def get_performance(db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    """Return side-by-side performance data for paper and real trading."""
    trades = db.query(TradeLog).filter(TradeLog.status == "success") \
        .order_by(TradeLog.created_at).all()

    def _build(trade_list):
        cumulative = 0
        series = []
        for i, t in enumerate(trade_list):
            cumulative += t.net_result
            series.append({
                "index": i + 1,
                "timestamp": t.created_at.isoformat() if t.created_at else None,
                "cumulative_pnl": round(cumulative, 4),
                "net_result": round(t.net_result, 4),
                "pair": t.pair,
            })
        wins = [t for t in trade_list if t.net_result > 0]
        losses = [t for t in trade_list if t.net_result < 0]
        pnl = sum(t.net_result for t in trade_list)
        return {
            "series": series,
            "stats": {
                "total_trades": len(trade_list),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": round(len(wins) / len(trade_list) * 100, 1) if trade_list else 0,
                "total_pnl": round(pnl, 4),
                "best_trade": round(max((t.net_result for t in trade_list), default=0), 4),
                "worst_trade": round(min((t.net_result for t in trade_list), default=0), 4),
                "avg_profit": round(pnl / len(trade_list), 4) if trade_list else 0,
            },
        }

    paper = _build([t for t in trades if t.mode == "paper"])
    real = _build([t for t in trades if t.mode == "real"])

    return {"paper": paper, "real": real}


# ── Summary (overall P&L) ──────────────────────────────────────────────────────
@app.get("/api/summary")
def get_summary(db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    """Return detailed P&L summary for paper and real trades."""
    c = cfg_all(db)
    starting = c.get("starting_capital", 50)
    paper_balance = c.get("current_paper_balance", 0)
    real_balance = c.get("current_real_balance", 0)

    all_trades = db.query(TradeLog).order_by(TradeLog.created_at).all()

    def _summary(trade_list, balance, starting_cap):
        successful = [t for t in trade_list if t.status == "success"]
        wins = [t for t in successful if t.net_result > 0]
        losses = [t for t in successful if t.net_result < 0]
        total_pnl = sum(t.net_result for t in successful)
        total_fees = sum(t.fees for t in successful)
        total_gas = sum(t.gas for t in successful)
        best = max(successful, key=lambda t: t.net_result, default=None)
        worst = min(successful, key=lambda t: t.net_result, default=None)
        return {
            "total_pnl": round(total_pnl, 4),
            "total_trades": len(successful),
            "total_all_trades": len(trade_list),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(successful) * 100, 1) if successful else 0,
            "best_trade": {"pair": best.pair, "profit": round(best.net_result, 4),
                           "network": best.network} if best else None,
            "worst_trade": {"pair": worst.pair, "profit": round(worst.net_result, 4),
                           "network": worst.network} if worst else None,
            "avg_profit": round(total_pnl / len(successful), 4) if successful else 0,
            "total_fees": round(total_fees, 4),
            "total_gas": round(total_gas, 4),
            "starting_capital": starting_cap,
            "current_balance": round(balance, 4),
            "return_pct": round((balance - starting_cap) / starting_cap * 100, 2) if starting_cap else 0,
        }

    paper = _summary([t for t in all_trades if t.mode == "paper"], paper_balance, starting)
    real = _summary([t for t in all_trades if t.mode == "real"], real_balance, starting)

    return {
        "paper": paper,
        "real": real,
        "combined": {
            "total_pnl": round(paper["total_pnl"] + real["total_pnl"], 4),
            "total_trades": paper["total_trades"] + real["total_trades"],
            "total_fees": round(paper["total_fees"] + real["total_fees"], 4),
            "total_gas": round(paper["total_gas"] + real["total_gas"], 4),
        },
    }


# ── SPA fallback ──────────────────────────────────────────────────────────────
def _serve_html():
    with open(os.path.join(STATIC_DIR, "index.html")) as f:
        html = f.read()
    ga_id = os.environ.get("GA_MEASUREMENT_ID", "")
    if ga_id:
        ga_script = (
            '<script async src="https://www.googletagmanager.com/gtag/js?id={id}"></script>'
            '<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments)}}'
            'gtag("js",new Date());gtag("config","{id}");</script>'
        ).format(id=ga_id)
        html = html.replace("<!--GA_PLACEHOLDER-->", ga_script)
    return html


@app.get("/", response_class=HTMLResponse)
def index():
    return _serve_html()


@app.get("/{full_path:path}", response_class=HTMLResponse)
def spa_fallback(full_path: str):
    # Serve index.html for any non-API route (SPA routing)
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    return _serve_html()
