import json
import os
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc, text

from app.database import engine, get_db, Base, SessionLocal
from app.models import (User, Config, Opportunity, TradeLog, BotHeartbeat,
                        AccountSnapshot, TierProgress, InsightLog, BotLog,
                        Notification, CapitalTransaction, PerformanceSnapshot)
from app.auth import (hash_password, verify_password, create_token,
                      get_current_user, verify_webhook_key)
from app.prioritization import (get_tier, get_next_tier, get_unlocked_networks,
                                get_current_thresholds, calculate_priority_score,
                                passes_risk_checks, TIERS)
from app.execution import ExecutionEngine, BASE_TOKENS, BASE_ROUTERS
from app.learning import pattern_engine
from app.scoring import calculate_score, ScoreInput

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
    "is_running": True,
    "wallet_address": os.environ.get("WALLET_ADDRESS", ""),
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
        for name in ["scanner", "quant", "guardian", "execution"]:
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


def run_migrations():
    """Add new columns to existing tables (SQLite ALTER TABLE)."""
    with engine.connect() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(opportunities)"))]
        if "source" not in cols:
            conn.execute(text("ALTER TABLE opportunities ADD COLUMN source TEXT DEFAULT ''"))
        if "external_id" not in cols:
            conn.execute(text("ALTER TABLE opportunities ADD COLUMN external_id TEXT DEFAULT ''"))
        if "ev_score" not in cols:
            conn.execute(text("ALTER TABLE opportunities ADD COLUMN ev_score REAL DEFAULT 0"))
        if "execution_probability" not in cols:
            conn.execute(text("ALTER TABLE opportunities ADD COLUMN execution_probability REAL DEFAULT 0"))
        if "risk_passed" not in cols:
            conn.execute(text("ALTER TABLE opportunities ADD COLUMN risk_passed INTEGER DEFAULT 1"))
        if "risk_reason" not in cols:
            conn.execute(text("ALTER TABLE opportunities ADD COLUMN risk_reason TEXT DEFAULT ''"))
        conn.commit()


run_migrations()

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


class TestTradeRequest(BaseModel):
    router: str = "UniswapV2"
    token_in: str = "WETH"
    token_out: str = "USDC"
    amount: float = 0.001  # tiny amount (0.001 WETH ≈ $2-3)


# ── V2 Bot Integration Guide schemas ──────────────────────────────────────────
class HeartbeatPushV2(BaseModel):
    bot: str
    status: str = "running"  # running | paused | error | offline
    message: str = ""
    timestamp: Optional[int] = None
    meta: Optional[dict] = {}


class LogPush(BaseModel):
    bot: str
    level: str = "info"  # info | warning | error
    message: str
    meta: Optional[dict] = {}


class OpportunityPushV2(BaseModel):
    """New-schema opportunity push from external bots."""
    id: Optional[str] = None
    type: Optional[str] = None  # crossdex | flashloan | triangular | multihop
    network: str
    path: Optional[list[str]] = None
    amountIn: Optional[str] = None
    expectedAmountOut: Optional[str] = None
    netProfit: Optional[str] = None
    netProfitUsd: Optional[float] = None
    score: Optional[float] = None
    status: Optional[str] = None
    source: Optional[str] = None
    timestamp: Optional[int] = None


class TradeLogPushV2(BaseModel):
    """New-schema trade result push from external bots."""
    opportunityId: Optional[str] = None
    mode: str = "paper"  # paper | real
    status: str = "success"  # success | failed
    network: str = "base"
    txHash: Optional[str] = None
    amountIn: Optional[str] = None
    amountOut: Optional[str] = None
    netProfit: Optional[str] = None
    netProfitUsd: Optional[float] = None
    gasUsed: Optional[str] = None
    notes: str = ""
    timestamp: Optional[int] = None


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


# ── Bot Auth Helper ──────────────────────────────────────────────────────────
def verify_bot_auth(request: Request, db: Session) -> bool:
    """Verify bot authentication via Bearer token or X-API-Key (backward compat)."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return verify_webhook_key(auth[7:], db)
    api_key = request.headers.get("X-API-Key", "")
    return verify_webhook_key(api_key, db)


# ── Health ───────────────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# ── Bot Integration Guide endpoints ──────────────────────────────────────────
@app.get("/api/test")
def api_test(request: Request, db: Session = Depends(get_db)):
    """Connectivity test for external bots. Requires bot auth."""
    if not verify_bot_auth(request, db):
        raise HTTPException(status_code=401, detail="Invalid bot secret")
    return {"status": "ok", "message": "Arbitrage Gods API reachable"}


@app.get("/api/status")
def api_status(request: Request, db: Session = Depends(get_db)):
    """Full system status for external bots. Requires bot auth."""
    if not verify_bot_auth(request, db):
        raise HTTPException(status_code=401, detail="Invalid bot secret")
    c = cfg_all(db)
    is_paper = c.get("paper_mode", True)
    is_real = c.get("real_mode", False)
    is_aggressive = c.get("aggressive_mode", False)
    balance = c.get("current_paper_balance", 0) if is_paper else c.get("current_real_balance", 0)
    min_profit, max_size_pct, max_hops, allow_more = get_current_thresholds(balance, is_aggressive)
    return {
        "mode": "real" if is_real else "paper",
        "is_running": c.get("is_running", True),
        "is_aggressive": is_aggressive,
        "compounding_mode": c.get("compounding_mode", True),
        "account_balance": balance,
        "thresholds": {
            "min_profit": min_profit,
            "max_size_percent": max_size_pct,
            "max_hops": max_hops,
            "allow_more_pairs": allow_more,
        },
        "risk_limits": {
            "max_risk_percent": c.get("max_risk_aggressive" if is_aggressive else "max_risk_normal", 0.12),
            "daily_loss_limit": c.get("daily_loss_limit", 0.05),
            "max_open_exposure": c.get("max_open_exposure", 0.30),
            "slippage_pct": c.get("slippage_pct", 0.005),
            "estimated_gas_usd": c.get("estimated_gas_usd", 5),
        },
        "unlocked_networks": get_unlocked_networks(balance),
        "routers": {
            "base": c.get("base_router"),
            "ethereum": c.get("eth_router"),
        },
        "wallet_address": c.get("wallet_address", ""),
        "network_config": {
            "chain_id": c.get("base_chain_id", 8453),
            "rpc_url": c.get("base_rpc_url", "https://mainnet.base.org"),
        },
    }


@app.post("/api/heartbeats")
def push_heartbeat_v2(hb: HeartbeatPushV2, request: Request, db: Session = Depends(get_db)):
    """Unified heartbeat endpoint. Bot name in body. Requires bot auth."""
    if not verify_bot_auth(request, db):
        raise HTTPException(status_code=401, detail="Invalid bot secret")
    bot = db.query(BotHeartbeat).filter(BotHeartbeat.bot_name == hb.bot).first()
    if not bot:
        bot = BotHeartbeat(bot_name=hb.bot)
        db.add(bot)
    bot.status = hb.status
    bot.last_heartbeat = datetime.now(timezone.utc)
    bot.last_action = hb.message
    bot.error_message = hb.error_message if hb.status == "error" else ""
    db.commit()
    return {"status": "ok", "bot": hb.bot}


@app.post("/api/logs")
def push_log(log: LogPush, request: Request, db: Session = Depends(get_db)):
    """Receive a log entry from an external bot. Error logs create a notification."""
    if not verify_bot_auth(request, db):
        raise HTTPException(status_code=401, detail="Invalid bot secret")
    row = BotLog(
        bot=log.bot,
        level=log.level,
        message=log.message,
        meta=json.dumps(log.meta) if log.meta else "",
    )
    db.add(row)
    # Create notification for error logs
    if log.level == "error":
        db.add(Notification(
            type="error", title=f"{log.bot.title()} Bot Error",
            message=log.message,
        ))
    db.commit()
    return {"status": "logged", "id": row.id}


@app.get("/api/logs")
def get_logs(bot: Optional[str] = None, level: Optional[str] = None, limit: int = 100,
             db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Retrieve bot log entries (admin only)."""
    q = db.query(BotLog).order_by(desc(BotLog.timestamp))
    if bot:
        q = q.filter(BotLog.bot == bot)
    if level:
        q = q.filter(BotLog.level == level)
    logs = q.limit(limit).all()
    return [{"id": l.id, "bot": l.bot, "level": l.level, "message": l.message,
             "meta": json.loads(l.meta) if l.meta else {}, "timestamp": l.timestamp.isoformat() if l.timestamp else None}
            for l in logs]


@app.post("/api/mode/running")
def toggle_running(req: ModeToggle, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """Toggle the global is_running flag (admin only)."""
    cfg_set(db, "is_running", req.enabled)
    return {"is_running": req.enabled}


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


@app.get("/api/performance/winrate")
def get_winrate_chart(db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    """Return rolling win-rate and learning-progress series for the dashboard chart."""
    trades = db.query(TradeLog).filter(
        TradeLog.status.in_(["success", "failed"])
    ).order_by(TradeLog.created_at).all()

    paper_trades = [t for t in trades if t.mode == "paper"]
    real_trades = [t for t in trades if t.mode == "real"]

    def _winrate_series(trade_list):
        wins = 0
        total = 0
        points = []
        for i, t in enumerate(trade_list):
            total += 1
            if t.status == "success" and t.net_result > 0:
                wins += 1
            wr = (wins / total * 100) if total else 0
            points.append({
                "index": i + 1,
                "timestamp": t.created_at.isoformat() if t.created_at else None,
                "win_rate": round(wr, 1),
                "cumulative_pnl": round(
                    sum(tt.net_result for tt in trade_list[:i + 1]
                        if tt.status == "success"), 4),
            })
        return points

    # Learning progress: cumulative pattern count over time from InsightLog
    insights = db.query(InsightLog).order_by(InsightLog.timestamp).all()
    pattern_points = []
    seen_keys = set()
    for ins in insights:
        key = f"{ins.insight_type}:{ins.pair}:{ins.network}:{ins.metric}"
        if key not in seen_keys:
            seen_keys.add(key)
        pattern_points.append({
            "timestamp": ins.timestamp.isoformat() if ins.timestamp else None,
            "patterns_learned": len(seen_keys),
        })

    return {
        "paper": _winrate_series(paper_trades),
        "real": _winrate_series(real_trades),
        "learning": pattern_points,
        "paper_count": len(paper_trades),
        "real_count": len(real_trades),
        "patterns_total": len(seen_keys),
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
async def push_opportunity(request: Request, db: Session = Depends(get_db)):
    """Webhook endpoint for bots to push discovered opportunities.
    Accepts both V1 (OpportunityPush) and V2 (OpportunityPushV2) schemas."""
    if not verify_bot_auth(request, db):
        raise HTTPException(status_code=401, detail="Invalid bot secret or API key")
    body = await request.json()
    if not body or not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Empty or invalid request body")
    c = cfg_all(db)
    balance = c.get("current_paper_balance", 0) if c.get("paper_mode", True) else c.get("current_real_balance", 0)
    is_aggressive = c.get("aggressive_mode", False)
    min_profit, _, max_hops, _ = get_current_thresholds(balance, is_aggressive)
    unlocked = get_unlocked_networks(balance)

    # Detect V2 schema (has 'type' or 'path' or 'netProfitUsd')
    if "type" in body or "path" in body or "netProfitUsd" in body or "amountIn" in body:
        try:
            opp = OpportunityPushV2(**body)
        except Exception as e:
            raise HTTPException(status_code=400,
                                detail=f"Invalid V2 opportunity payload: {e}")
        # Reject opportunities on locked networks
        if opp.network not in unlocked:
            raise HTTPException(status_code=403, detail=f"Network '{opp.network}' is not unlocked")
        # Map V2 fields to model
        type_map = {"flashloan": "flash_loan", "crossdex": "inventory",
                    "triangular": "inventory", "multihop": "inventory"}
        style = type_map.get(opp.type or "", "inventory")
        pair = " → ".join(opp.path) if opp.path else ""
        net_profit = opp.netProfitUsd if opp.netProfitUsd is not None else 0
        score = opp.score if opp.score is not None else calculate_priority_score(net_profit, 80, 1)
        status_val = opp.status if opp.status in ("pending", "approved") else "pending"
        hops_val = len(opp.path or [1])
        # Apply learned pattern adjustments to confidence and priority
        learned = pattern_engine.score_opportunity(
            db, pair=pair, network=opp.network, style=style,
            net_profit=net_profit, base_confidence=80, hops=hops_val)
        adjusted_confidence = learned["confidence"]
        score += learned["priority_boost"]
        row = Opportunity(
            pair=pair, network=opp.network, style=style,
            buy_venue=opp.source or "", sell_venue="",
            buy_price=float(opp.amountIn or 0), sell_price=float(opp.expectedAmountOut or 0),
            gross_profit=0, estimated_costs=0,
            net_profit=net_profit, confidence=adjusted_confidence, hops=hops_val,
            status=status_val, priority_score=score,
            source=opp.source or "", external_id=opp.id or "",
        )
    else:
        # V1 schema (backward compat)
        try:
            opp = OpportunityPush(**body)
        except Exception as e:
            raise HTTPException(status_code=400,
                                detail=f"Invalid opportunity payload: {e}")
        if opp.network not in unlocked:
            raise HTTPException(status_code=403, detail=f"Network '{opp.network}' is not unlocked")
        status_val = "pending"
        # Apply learned pattern adjustments to confidence and priority
        learned = pattern_engine.score_opportunity(
            db, pair=opp.pair, network=opp.network, style=opp.style,
            net_profit=opp.net_profit, base_confidence=opp.confidence, hops=opp.hops)
        adjusted_confidence = learned["confidence"]
        score = calculate_priority_score(opp.net_profit, adjusted_confidence, opp.hops)
        score += learned["priority_boost"]
        row = Opportunity(
            pair=opp.pair, network=opp.network, style=opp.style,
            buy_venue=opp.buy_venue, sell_venue=opp.sell_venue,
            buy_price=opp.buy_price, sell_price=opp.sell_price,
            gross_profit=opp.gross_profit, estimated_costs=opp.estimated_costs,
            net_profit=opp.net_profit, confidence=adjusted_confidence, hops=opp.hops,
            status=status_val, priority_score=score,
        )
    # ── EV-based scoring ──
    gas_cost = c.get("estimated_gas_usd", 5)
    slippage_bps = c.get("slippage_pct", 0.005) * 10000
    recent_rate = None
    learn_summary = pattern_engine.analyze(db).get("summary", {})
    if learn_summary.get("total_trades_analyzed", 0) >= 3:
        recent_rate = learn_summary.get("baseline_win_rate", 0) / 100

    score_inp = ScoreInput(
        net_profit_usd=row.net_profit,
        gas_cost_usd=gas_cost,
        hops=row.hops,
        slippage_bps=slippage_bps,
        recent_success_rate=recent_rate,
    )
    score_result = calculate_score(score_inp)
    row.ev_score = score_result.final_score
    row.execution_probability = score_result.execution_probability
    # Boost priority with EV score
    row.priority_score += score_result.final_score * 10

    # ── Automatic risk validation ──
    trade_size = row.net_profit
    daily_loss = 0  # computed below
    today = datetime.now(timezone.utc) - timedelta(days=1)
    today_trades = db.query(TradeLog).filter(
        TradeLog.created_at >= today,
    ).all()
    daily_loss = sum(abs(t.net_result) for t in today_trades
                     if t.status == "success" and t.net_result < 0)

    risk_passed, risk_reason = passes_risk_checks(
        row.net_profit, trade_size, balance, is_aggressive, daily_loss, c)
    row.risk_passed = 1 if risk_passed else 0
    row.risk_reason = risk_reason if not risk_passed else ""

    if not risk_passed:
        row.status = "rejected"
    elif not score_result.approved and row.net_profit > 0:
        # Score says not worth executing — keep pending but flag low EV
        row.confidence = min(row.confidence, 30)

    db.add(row)
    db.commit()
    return {
        "id": row.id, "status": row.status,
        "priority_score": row.priority_score,
        "ev_score": row.ev_score,
        "execution_probability": row.execution_probability,
        "risk_passed": row.risk_passed,
        "risk_reason": row.risk_reason,
    }


def _opp_dict(o: Opportunity) -> dict:
    return {
        "id": o.id, "pair": o.pair, "network": o.network, "style": o.style,
        "buy_venue": o.buy_venue, "sell_venue": o.sell_venue,
        "buy_price": o.buy_price, "sell_price": o.sell_price,
        "gross_profit": o.gross_profit, "estimated_costs": o.estimated_costs,
        "net_profit": o.net_profit, "confidence": o.confidence, "hops": o.hops,
        "status": o.status, "priority_score": o.priority_score,
        "source": o.source if hasattr(o, "source") else "",
        "external_id": o.external_id if hasattr(o, "external_id") else "",
        "ev_score": o.ev_score if hasattr(o, "ev_score") else 0,
        "execution_probability": o.execution_probability if hasattr(o, "execution_probability") else 0,
        "risk_passed": bool(o.risk_passed) if hasattr(o, "risk_passed") else True,
        "risk_reason": o.risk_reason if hasattr(o, "risk_reason") else "",
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
async def log_trade(request: Request, db: Session = Depends(get_db)):
    """Webhook endpoint for Execution Bot to log results.
    Accepts both V1 (TradeLogPush) and V2 (TradeLogPushV2) schemas."""
    if not verify_bot_auth(request, db):
        raise HTTPException(status_code=401, detail="Invalid bot secret or API key")
    body = await request.json()
    if not body or not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Empty or invalid request body")
    # Detect V2 schema (has 'opportunityId' or 'txHash' or 'netProfitUsd')
    if "opportunityId" in body or "txHash" in body or "netProfitUsd" in body or "gasUsed" in body:
        trade = TradeLogPushV2(**body)
        net_result = trade.netProfitUsd if trade.netProfitUsd is not None else 0
        gas = float(trade.gasUsed or 0)
        notes = trade.notes
        if trade.txHash:
            notes = f"{notes} | tx: {trade.txHash}" if notes else f"tx: {trade.txHash}"
        # Try to find opportunity by external_id or numeric id
        opp = None
        if trade.opportunityId:
            opp = db.query(Opportunity).filter(Opportunity.external_id == trade.opportunityId).first()
            if not opp:
                try:
                    opp = db.query(Opportunity).filter(Opportunity.id == int(trade.opportunityId)).first()
                except (ValueError, TypeError):
                    pass
        row = TradeLog(
            opportunity_id=opp.id if opp else None,
            mode=trade.mode, style="flash_loan" if "flash" in (notes or "").lower() else "inventory",
            network=trade.network, pair=opp.pair if opp else "",
            expected_profit=net_result, actual_profit=net_result,
            status=trade.status, buy_cost=float(trade.amountIn or 0),
            sell_proceeds=float(trade.amountOut or 0),
            fees=0, gas=gas, slippage=0,
            net_result=net_result, notes=notes,
        )
    else:
        # V1 schema (backward compat)
        trade = TradeLogPush(**body)
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
    mode = row.mode
    net = row.net_result
    if row.status == "success" and net != 0:
        balance_key = "current_paper_balance" if mode == "paper" else "current_real_balance"
        current = cfg_get(db, balance_key, 0)
        cfg_set(db, balance_key, current + net)
        db.add(AccountSnapshot(
            mode=mode,
            balance=current + net,
            starting_capital=cfg_get(db, "starting_capital", 50),
        ))
    # Mark opportunity as executed
    if row.opportunity_id:
        opp = db.query(Opportunity).filter(Opportunity.id == row.opportunity_id).first()
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
    """Webhook endpoint for bots to push heartbeats (backward compat — use POST /api/heartbeats)."""
    if not verify_bot_auth(request, db):
        raise HTTPException(status_code=401, detail="Invalid bot secret or API key")
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
    if not verify_bot_auth(request, db):
        raise HTTPException(status_code=401, detail="Invalid bot secret or API key")
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

    mode_str = "real" if is_real else "paper"

    # ── Kill switch check ──
    if not c.get("is_running", True):
        raise HTTPException(status_code=400, detail="Kill switch active — trading is stopped")

    # ── Compute daily loss from today's trades ──
    today_cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    today_trades = db.query(TradeLog).filter(
        TradeLog.created_at >= today_cutoff,
        TradeLog.mode == mode_str,
    ).all()
    daily_loss = sum(abs(t.net_result) for t in today_trades
                     if t.status == "success" and t.net_result < 0)

    # ── Open exposure check ──
    open_opps = db.query(Opportunity).filter(
        Opportunity.status.in_(["pending", "approved"]),
        Opportunity.id != opp_id,
    ).all()
    total_exposure = sum(o.net_profit for o in open_opps)
    max_exposure_pct = c.get("max_open_exposure", 0.30)
    if total_exposure + opp.net_profit > balance * max_exposure_pct:
        raise HTTPException(status_code=400,
                            detail=f"Open exposure limit exceeded: "
                                   f"${total_exposure:.2f} + ${opp.net_profit:.2f} > "
                                   f"{max_exposure_pct*100:.0f}% of ${balance:.2f}")

    # ── Risk gate — validate against safety thresholds ──
    max_risk_pct = c.get("max_risk_aggressive" if is_aggressive else "max_risk_normal", 0.12)
    trade_size = balance * max_risk_pct  # actual capital at risk
    passed, reason = passes_risk_checks(
        opp.net_profit, trade_size, balance, is_aggressive, daily_loss, c)
    if not passed:
        raise HTTPException(status_code=400, detail=f"Risk check failed: {reason}")

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


# ── Test Trade (live execution verification) ─────────────────────────────────
@app.post("/api/execution/test-trade")
def test_trade(req: TestTradeRequest, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    """Execute a small test swap to verify execution engine, risk validation,
    and chain communication all work in harmony."""
    c = cfg_all(db)

    # Kill switch check
    if not c.get("is_running", True):
        raise HTTPException(status_code=400, detail="Kill switch active — cannot test trade")

    # Wallet configuration check
    if not _executor.is_configured():
        raise HTTPException(status_code=400,
                            detail="Wallet not configured. Set PRIVATE_KEY and WALLET_ADDRESS in Secrets.")

    is_aggressive = c.get("aggressive_mode", False)
    on_chain_status = _executor.get_status()
    on_chain_balance_eth = on_chain_status.get("balance", 0)
    eth_price_usd = 2500  # approximate ETH price for risk estimation
    on_chain_balance_usd = on_chain_balance_eth * eth_price_usd

    # ── Risk validation ──
    today_cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    today_trades = db.query(TradeLog).filter(
        TradeLog.created_at >= today_cutoff,
        TradeLog.mode == "real",
    ).all()
    daily_loss = sum(abs(t.net_result) for t in today_trades
                     if t.status == "success" and t.net_result < 0)

    trade_value_usd = req.amount * eth_price_usd
    risk_passed, risk_reason = passes_risk_checks(
        trade_value_usd, trade_value_usd,
        max(on_chain_balance_usd, 1), is_aggressive, daily_loss, c)

    risk_check = {
        "passed": risk_passed,
        "reason": risk_reason,
        "trade_value_usd": round(trade_value_usd, 2),
        "on_chain_balance_eth": on_chain_balance_eth,
        "on_chain_balance_usd_est": round(on_chain_balance_usd, 2),
        "daily_loss_so_far": round(daily_loss, 4),
        "is_running": c.get("is_running", True),
    }

    if not risk_passed:
        return {
            "success": False,
            "error": f"Risk check failed: {risk_reason}",
            "risk_check": risk_check,
        }

    # ── Execute test swap ──
    result = _executor.test_swap(
        router_name=req.router,
        token_in_name=req.token_in,
        token_out_name=req.token_out,
        amount_in_human=req.amount,
    )

    # ── Log the trade ──
    status_str = "success" if result.get("success") else "failed"
    row = TradeLog(
        mode="real", style="inventory", network="base",
        pair=f"{req.token_in}/{req.token_out}",
        expected_profit=0, actual_profit=0,
        status=status_str,
        buy_cost=req.amount, sell_proceeds=0,
        fees=0, gas=result.get("gas_used", 0),
        slippage=0, net_result=0,
        notes=f"Test trade | risk: {risk_reason} | {json.dumps(result)}",
    )
    db.add(row)
    db.add(Notification(
        type="success" if result.get("success") else "error",
        title="Test Trade " + ("Executed" if result.get("success") else "Failed"),
        message=(f"{req.token_in}→{req.token_out} on {req.router}: "
                 f"{'✅ tx ' + result.get('tx_hash', '') if result.get('success') else '❌ ' + result.get('error', 'failed')}"),
    ))
    db.commit()

    return {
        "success": result.get("success", False),
        "risk_check": risk_check,
        "execution_result": result,
        "trade_id": row.id,
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

    # Drawdown calculation
    def _drawdown(trade_list, starting):
        peak = starting
        max_dd = 0
        running = starting
        for t in trade_list:
            running += t.net_result
            if running > peak:
                peak = running
            dd = (peak - running) / peak * 100 if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        current_dd = (peak - running) / peak * 100 if peak > 0 else 0
        return {"max_drawdown": round(max_dd, 2), "current_drawdown": round(current_dd, 2)}

    starting_cap = cfg_get(db, "starting_capital", 50)
    paper["drawdown"] = _drawdown([t for t in trades if t.mode == "paper"], starting_cap)
    real["drawdown"] = _drawdown([t for t in trades if t.mode == "real"], starting_cap)

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


# ── Learning Engine ───────────────────────────────────────────────────────────
@app.get("/api/learning/patterns")
def get_learned_patterns(db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    """Return learned patterns from the most recent analysis."""
    return pattern_engine.get_cached_patterns(db)


@app.post("/api/learning/analyze")
def run_learning_analysis(db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    """Trigger a full re-analysis of trade history. Returns patterns + recommendations."""
    return pattern_engine.analyze(db)


@app.get("/api/learning/recommendations")
def get_learned_recommendations(db: Session = Depends(get_db),
                                user: User = Depends(get_current_user)):
    """Return actionable recommendations derived from learned patterns."""
    return pattern_engine.get_cached_recommendations(db)


@app.get("/api/learning/status")
def get_learning_status(db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    """Quick summary of the learning engine state."""
    patterns = pattern_engine.get_cached_patterns(db)
    recs = pattern_engine.get_cached_recommendations(db)
    trades = db.query(TradeLog).filter(TradeLog.status.in_(["success", "failed"])).count()
    return {
        "total_trades_analyzed": trades,
        "patterns_cached": len(patterns),
        "recommendations_cached": len(recs),
        "min_sample_for_reliability": 3,
        "learning_active": trades >= 3,
    }


# ── Kill Switch ──────────────────────────────────────────────────────────────
@app.post("/api/kill-switch")
def kill_switch(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Emergency stop — immediately sets is_running = false and real_mode = false."""
    cfg_set(db, "is_running", False)
    cfg_set(db, "real_mode", False)
    cfg_set(db, "paper_mode", True)
    # Pause all bots
    for bot in db.query(BotHeartbeat).all():
        bot.status = "paused"
    db.add(Notification(
        type="error", title="KILL SWITCH ACTIVATED",
        message="All trading stopped. Real mode disabled. All bots paused.",
    ))
    db.commit()
    return {"status": "killed", "is_running": False, "real_mode": False}


# ── Master Controls ──────────────────────────────────────────────────────────
@app.post("/api/master/start")
def master_start(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Start all bots and set is_running = true."""
    cfg_set(db, "is_running", True)
    for bot in db.query(BotHeartbeat).all():
        if bot.status == "paused":
            bot.status = "running"
    db.add(Notification(type="success", title="System Started", message="All bots resumed. Trading active."))
    db.commit()
    return {"is_running": True}


@app.post("/api/master/pause")
def master_pause(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Pause all bots but keep is_running config for resume."""
    for bot in db.query(BotHeartbeat).all():
        bot.status = "paused"
    db.add(Notification(type="warning", title="System Paused", message="All bots paused. No new trades."))
    db.commit()
    return {"is_running": cfg_get(db, "is_running", True)}


@app.post("/api/master/stop")
def master_stop(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Full stop — is_running = false, all bots paused."""
    cfg_set(db, "is_running", False)
    for bot in db.query(BotHeartbeat).all():
        bot.status = "paused"
    db.add(Notification(type="warning", title="System Stopped", message="Trading stopped. All bots paused."))
    db.commit()
    return {"is_running": False}


# ── Capital & Withdraw / Compound ─────────────────────────────────────────────
@app.get("/api/capital/transactions")
def get_capital_transactions(mode: Optional[str] = None, limit: int = 50,
                             db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(CapitalTransaction).order_by(desc(CapitalTransaction.created_at))
    if mode:
        q = q.filter(CapitalTransaction.mode == mode)
    txns = q.limit(limit).all()
    return [{"id": t.id, "type": t.type, "mode": t.mode, "amount": t.amount,
             "balance_after": t.balance_after, "notes": t.notes,
             "created_at": t.created_at.isoformat() if t.created_at else None} for t in txns]


@app.post("/api/capital/withdraw")
def withdraw_capital(req: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Withdraw capital from paper or real balance."""
    mode = req.get("mode", "paper")
    amount = float(req.get("amount", 0))
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Withdrawal amount must be positive")
    balance_key = "current_paper_balance" if mode == "paper" else "current_real_balance"
    current = cfg_get(db, balance_key, 0)
    if amount > current:
        raise HTTPException(status_code=400, detail=f"Insufficient balance (${current:.2f})")
    new_balance = current - amount
    cfg_set(db, balance_key, new_balance)
    txn = CapitalTransaction(type="withdraw", mode=mode, amount=-amount,
                             balance_after=new_balance, notes=req.get("notes", "Manual withdrawal"))
    db.add(txn)
    db.add(AccountSnapshot(mode=mode, balance=new_balance,
                           starting_capital=cfg_get(db, "starting_capital", 50)))
    db.add(Notification(type="info", title="Withdrawal Processed",
                        message=f"Withdrew ${amount:.2f} from {mode} balance. New balance: ${new_balance:.2f}"))
    db.commit()
    return {"status": "ok", "mode": mode, "amount": amount, "new_balance": new_balance}


@app.post("/api/capital/compound")
def manual_compound(req: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Manually compound profits — move realized profit into trading balance."""
    mode = req.get("mode", "paper")
    amount = float(req.get("amount", 0))
    balance_key = "current_paper_balance" if mode == "paper" else "current_real_balance"
    current = cfg_get(db, balance_key, 0)
    if amount <= 0:
        # Auto-compound all available profit above starting capital
        starting = cfg_get(db, "starting_capital", 50)
        amount = max(0, current - starting)
        if amount == 0:
            raise HTTPException(status_code=400, detail="No profit available to compound")
    # In this system, compounding means the profit stays in the balance (it already does).
    # This records the action and ensures compounding_mode is on.
    cfg_set(db, "compounding_mode", True)
    txn = CapitalTransaction(type="compound", mode=mode, amount=amount,
                             balance_after=current, notes="Manual compound — profit reinvested")
    db.add(txn)
    db.add(Notification(type="success", title="Profit Compounded",
                        message=f"Compounded ${amount:.2f} in {mode} balance. Total balance: ${current:.2f}"))
    db.commit()
    return {"status": "ok", "mode": mode, "amount": amount, "balance": current}


@app.post("/api/capital/deposit")
def deposit_capital(req: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Add capital to paper or real balance."""
    mode = req.get("mode", "paper")
    amount = float(req.get("amount", 0))
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Deposit amount must be positive")
    balance_key = "current_paper_balance" if mode == "paper" else "current_real_balance"
    current = cfg_get(db, balance_key, 0)
    new_balance = current + amount
    cfg_set(db, balance_key, new_balance)
    txn = CapitalTransaction(type="deposit", mode=mode, amount=amount,
                             balance_after=new_balance, notes=req.get("notes", "Manual deposit"))
    db.add(txn)
    db.add(AccountSnapshot(mode=mode, balance=new_balance,
                           starting_capital=cfg_get(db, "starting_capital", 50)))
    db.add(Notification(type="success", title="Capital Added",
                        message=f"Deposited ${amount:.2f} to {mode} balance. New balance: ${new_balance:.2f}"))
    db.commit()
    return {"status": "ok", "mode": mode, "amount": amount, "new_balance": new_balance}


# ── Notifications ─────────────────────────────────────────────────────────────
@app.get("/api/notifications")
def get_notifications(unread_only: bool = False, limit: int = 50,
                      db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = db.query(Notification).order_by(desc(Notification.created_at))
    if unread_only:
        q = q.filter(Notification.read == 0)
    notifs = q.limit(limit).all()
    return [{"id": n.id, "type": n.type, "title": n.title, "message": n.message,
             "read": bool(n.read), "created_at": n.created_at.isoformat() if n.created_at else None}
            for n in notifs]


@app.post("/api/notifications/{nid}/read")
def mark_notification_read(nid: int, db: Session = Depends(get_db),
                            user: User = Depends(get_current_user)):
    n = db.query(Notification).filter(Notification.id == nid).first()
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    n.read = 1
    db.commit()
    return {"status": "read", "id": nid}


@app.post("/api/notifications/read-all")
def mark_all_notifications_read(db: Session = Depends(get_db),
                                 user: User = Depends(get_current_user)):
    db.query(Notification).filter(Notification.read == 0).update({"read": 1})
    db.commit()
    return {"status": "all_read"}


@app.get("/api/notifications/unread-count")
def get_unread_count(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    count = db.query(Notification).filter(Notification.read == 0).count()
    return {"unread": count}


# ── Regenerate BOT_SECRET ─────────────────────────────────────────────────────
@app.post("/api/regenerate-secret")
def regenerate_bot_secret(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Generate a new BOT_SECRET (webhook_api_key). Admin only."""
    import secrets as _secrets
    new_key = _secrets.token_urlsafe(32)
    cfg_set(db, "webhook_api_key", new_key)
    db.add(Notification(type="warning", title="BOT_SECRET Regenerated",
                        message="The bot API secret has been rotated. Update all external bots with the new key."))
    db.commit()
    return {"status": "ok", "webhook_api_key": new_key}


# ── Risk Monitor ──────────────────────────────────────────────────────────────
@app.get("/api/risk-monitor")
def get_risk_monitor(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Live risk metrics: current exposure, daily P&L, drawdown, kill switch status."""
    c = cfg_all(db)
    is_real = c.get("real_mode", False)
    is_aggressive = c.get("aggressive_mode", False)
    mode = "real" if is_real else "paper"
    balance = c.get("current_real_balance", 0) if is_real else c.get("current_paper_balance", 0)
    starting = c.get("starting_capital", 50)

    # Today's trades
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)
    today_trades = db.query(TradeLog).filter(
        TradeLog.mode == mode,
        TradeLog.created_at >= day_ago,
    ).all()

    today_pnl = sum(t.net_result for t in today_trades if t.status == "success")
    today_losses = sum(abs(t.net_result) for t in today_trades
                       if t.status == "success" and t.net_result < 0)

    # Drawdown calculation
    all_trades = db.query(TradeLog).filter(
        TradeLog.mode == mode, TradeLog.status == "success"
    ).order_by(TradeLog.created_at).all()

    peak = starting
    max_dd = 0
    current_dd = 0
    running = starting
    for t in all_trades:
        running += t.net_result
        if running > peak:
            peak = running
        dd = (peak - running) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
        current_dd = (peak - running) / peak * 100 if peak > 0 else 0

    # Current exposure (pending + approved opportunities)
    open_opps = db.query(Opportunity).filter(
        Opportunity.status.in_(["pending", "approved"])
    ).all()
    total_exposure = sum(o.net_profit for o in open_opps)
    max_risk_pct = c.get("max_risk_aggressive" if is_aggressive else "max_risk_normal", 0.12)
    daily_limit_pct = c.get("daily_loss_limit", 0.05)
    max_exposure_pct = c.get("max_open_exposure", 0.30)

    # Risk limits
    daily_loss_limit_usd = balance * daily_limit_pct
    max_exposure_usd = balance * max_exposure_pct
    max_risk_usd = balance * max_risk_pct

    # Check if daily loss limit hit
    daily_loss_hit = today_losses >= daily_loss_limit_usd
    exposure_hit = total_exposure >= max_exposure_usd

    return {
        "mode": mode,
        "is_running": c.get("is_running", True),
        "balance": balance,
        "starting_capital": starting,
        "today_pnl": round(today_pnl, 4),
        "today_losses": round(today_losses, 4),
        "today_trades": len(today_trades),
        "current_drawdown": round(current_dd, 2),
        "max_drawdown": round(max_dd, 2),
        "open_exposure": round(total_exposure, 4),
        "open_opportunities": len(open_opps),
        "risk_limits": {
            "max_risk_per_trade_usd": round(max_risk_usd, 2),
            "max_risk_per_trade_pct": max_risk_pct * 100,
            "daily_loss_limit_usd": round(daily_loss_limit_usd, 2),
            "daily_loss_limit_pct": daily_limit_pct * 100,
            "max_open_exposure_usd": round(max_exposure_usd, 2),
            "max_open_exposure_pct": max_exposure_pct * 100,
        },
        "alerts": {
            "daily_loss_limit_hit": daily_loss_hit,
            "exposure_limit_hit": exposure_hit,
            "kill_switch_active": not c.get("is_running", True),
        },
        "is_aggressive": is_aggressive,
    }


# ── Onboarding Checklist ─────────────────────────────────────────────────────
@app.get("/api/onboarding")
def get_onboarding_status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Return onboarding checklist status."""
    c = cfg_all(db)
    bots = db.query(BotHeartbeat).all()
    active_bots = [b for b in bots if b.status == "running"]
    exec_status = _executor.get_status()

    steps = [
        {
            "id": "login", "label": "Login to dashboard", "done": True,
            "detail": "You are logged in.",
        },
        {
            "id": "review_settings", "label": "Review trading settings",
            "done": True,  # they're seeing the dashboard
            "detail": "Check min profit, risk limits, and fee estimates in Settings.",
        },
        {
            "id": "set_secret", "label": "Review BOT_SECRET",
            "done": True,
            "detail": "Find your bot API secret in Security Settings. Share it with external bots.",
        },
        {
            "id": "connect_bots", "label": "Connect external bots",
            "done": len(active_bots) > 0,
            "detail": f"{len(active_bots)}/4 bots reporting heartbeats. See Bot Integration Guide.",
        },
        {
            "id": "verify_heartbeats", "label": "Verify bot heartbeats",
            "done": any(b.last_heartbeat for b in bots),
            "detail": "Bots should push heartbeats every 15–30 seconds.",
        },
        {
            "id": "paper_trade", "label": "Run paper trades",
            "done": db.query(TradeLog).filter(TradeLog.mode == "paper").count() > 0,
            "detail": "Execute at least one paper trade to validate the pipeline.",
        },
        {
            "id": "review_performance", "label": "Review performance",
            "done": db.query(TradeLog).filter(TradeLog.status == "success").count() >= 3,
            "detail": "Check Performance & Analytics after a few trades.",
        },
        {
            "id": "wallet_setup", "label": "Configure wallet (for real mode)",
            "done": exec_status.get("configured", False),
            "detail": "Set PRIVATE_KEY and WALLET_ADDRESS in Secrets for real execution.",
        },
    ]
    completed = sum(1 for s in steps if s["done"])
    return {"steps": steps, "completed": completed, "total": len(steps),
            "pct": round(completed / len(steps) * 100)}


# ── Performance Snapshots / Trend Charts ──────────────────────────────────────
@app.get("/api/performance/trends")
def get_performance_trends(period: str = "7d", db: Session = Depends(get_db),
                           user: User = Depends(get_current_user)):
    """Return daily P&L series for trend charts (24h, 7d, 30d)."""
    now = datetime.now(timezone.utc)
    if period == "24h":
        start = now - timedelta(hours=24)
        bucket = timedelta(hours=1)
        fmt = "%H:00"
    elif period == "30d":
        start = now - timedelta(days=30)
        bucket = timedelta(days=1)
        fmt = "%m-%d"
    else:
        start = now - timedelta(days=7)
        bucket = timedelta(days=1)
        fmt = "%m-%d"

    trades = db.query(TradeLog).filter(
        TradeLog.status == "success",
        TradeLog.created_at >= start,
    ).order_by(TradeLog.created_at).all()

    # Build daily buckets
    buckets = {}
    current = start
    while current <= now:
        key = current.strftime(fmt)
        buckets[key] = {"paper": 0, "real": 0, "paper_count": 0, "real_count": 0}
        current += bucket

    for t in trades:
        key = t.created_at.replace(tzinfo=timezone.utc).strftime(fmt)
        if key in buckets:
            if t.mode in buckets[key]:
                buckets[key][t.mode] += t.net_result
                buckets[key][f"{t.mode}_count"] += 1

    labels = list(buckets.keys())
    return {
        "labels": labels,
        "paper": [buckets[l]["paper"] for l in labels],
        "real": [buckets[l]["real"] for l in labels],
        "paper_counts": [buckets[l]["paper_count"] for l in labels],
        "real_counts": [buckets[l]["real_count"] for l in labels],
        "period": period,
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
