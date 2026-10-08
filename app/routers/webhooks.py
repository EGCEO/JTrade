"""Webhook + bot API endpoints for external bots (Scanner, Quant, Guardian, Execution).

The dashboard never holds private keys or signs transactions. External bots
push opportunities, heartbeats, trades, and logs here, and read the current
mode / thresholds / unlocked networks.

Authentication: Authorization: Bearer BOT_SECRET (primary).
Backward compat: X-API-Key header matching WEBHOOK_API_KEY env.

Endpoints are exposed under both /webhook/ and /api/ prefixes so bots can
use whichever the integration guide specifies.
"""
import os
import json
import secrets
from datetime import datetime
from fastapi import APIRouter, Request, Depends, Header, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import (
    User, Config, Opportunity, TradeLog, BotHeartbeat, AccountSnapshot,
    TierProgress, InsightLog, Log, Notification, CapitalTransaction,
    OppStatus, OppType, BotName, BotState, TradeMode, StrategyStyle, ACTIVE_BOTS,
)
from app.schemas import (
    OpportunityPush, TradeResultPush, HeartbeatPush, BalanceUpdate, InsightPush, LogPush,
)
from app.prioritization import calculate_net_profit, get_current_thresholds, is_network_unlocked
from app.routers.auth import ensure_config

router = APIRouter()

WEBHOOK_KEY = os.environ.get("WEBHOOK_API_KEY", "")


def _get_bot_secret(db: Session) -> str:
    """Read BOT_SECRET from Config (DB-stored, user-regenerable)."""
    cfg = db.query(Config).first()
    if cfg and cfg.bot_secret:
        return cfg.bot_secret
    # Fall back to env if set
    return os.environ.get("BOT_SECRET", "")


def check_auth(authorization: str = Header(default=""), x_api_key: str = Header(default=""),
               db: Session = Depends(get_db)):
    """Accept Authorization: Bearer BOT_SECRET or X-API-Key (backward compat)."""
    bot_secret = _get_bot_secret(db)
    # Try Bearer token first
    if authorization.startswith("Bearer "):
        token = authorization[7:]
        if bot_secret and token == bot_secret:
            return
        # Also accept WEBHOOK_API_KEY via Bearer for flexibility
        if WEBHOOK_KEY and token == WEBHOOK_KEY:
            return
    # Fall back to X-API-Key
    if WEBHOOK_KEY and x_api_key == WEBHOOK_KEY:
        return
    # If no secret is configured at all, allow open access (dev mode)
    if not bot_secret and not WEBHOOK_KEY:
        return
    raise HTTPException(status_code=401, detail="Invalid bot secret or API key")


def first_config(db: Session) -> Config:
    cfg = db.query(Config).first()
    if not cfg:
        user = db.query(User).first()
        if not user:
            user = User(username="admin", password_hash="x")
            db.add(user)
            db.commit()
            db.refresh(user)
        cfg = ensure_config(db, user)
    return cfg


def _normalize_bot_name(bot: str) -> str:
    """Map legacy 'calculator' to 'quant'."""
    if bot == "calculator":
        return "quant"
    return bot


def _ts_to_dt(ts) -> datetime:
    if ts:
        return datetime.utcfromtimestamp(ts)
    return datetime.utcnow()


# ---- Connection test ----

@router.get("/webhook/test")
@router.get("/api/test")
def webhook_test(db: Session = Depends(get_db), _=Depends(check_auth)):
    return {"ok": True, "authenticated": True}


# ---- Status (bots read mode, thresholds, risk limits, networks) ----

@router.get("/webhook/status")
@router.get("/api/status")
def webhook_status(db: Session = Depends(get_db), _=Depends(check_auth)):
    cfg = first_config(db)
    balance = cfg.current_balance_paper if not cfg.is_real_execution else cfg.current_balance_real
    t = get_current_thresholds(
        balance, cfg.is_aggressive,
        cfg.max_hops_normal, cfg.max_hops_aggressive,
        cfg.min_profit_normal, cfg.min_profit_aggressive,
    )
    return {
        "mode": "real" if cfg.is_real_execution else "paper",
        "is_running": cfg.is_running,
        "is_aggressive": cfg.is_aggressive,
        "auto_compound": cfg.auto_compound,
        "account_balance": balance,
        "thresholds": t.__dict__,
        "risk_limits": {
            "max_risk_per_trade": cfg.max_risk_per_trade_aggressive if cfg.is_aggressive else cfg.max_risk_per_trade,
            "daily_loss_limit": cfg.daily_loss_limit,
            "max_open_exposure": cfg.max_open_exposure,
            "max_flashloan_size": cfg.max_flashloan_size,
        },
        "unlocked_networks": [n for n in __import__("app.prioritization", fromlist=["get_network_tier"]).get_network_tier(balance)["networks"]],
        "routers": {"base": cfg.base_router, "ethereum": cfg.eth_router},
        "cooldown": cfg.cooldown_aggressive if cfg.is_aggressive else cfg.cooldown_normal,
        "wallet_address": cfg.wallet_address,
    }


# ---- Opportunities ----

@router.post("/webhook/opportunities")
@router.post("/api/opportunities")
def push_opportunity(payload: OpportunityPush, db: Session = Depends(get_db), _=Depends(check_auth)):
    cfg = first_config(db)
    balance = cfg.current_balance_paper if not cfg.is_real_execution else cfg.current_balance_real

    # Reject opportunities on locked networks
    if not is_network_unlocked(payload.network, balance):
        raise HTTPException(status_code=403, detail=f"Network '{payload.network}' not unlocked yet")

    # Determine net profit: prefer pre-calculated netProfitUsd, else compute
    if payload.netProfitUsd:
        net = payload.netProfitUsd
    elif payload.netProfit and payload.netProfit != "0":
        # netProfit is in wei — can't convert to USD without price feed, use as-is if it looks like USD
        net = float(payload.netProfit) / 1e18 if len(payload.netProfit) > 12 else float(payload.netProfit)
    else:
        net = calculate_net_profit(
            payload.sell_proceeds, payload.buy_cost, payload.cex_fees, payload.dex_fees,
            payload.estimated_gas, payload.slippage_estimate, payload.transfer_costs,
            payload.flashloan_fee, payload.price_impact_cost, payload.competition_haircut,
        )

    t = get_current_thresholds(
        balance, cfg.is_aggressive,
        cfg.max_hops_normal, cfg.max_hops_aggressive,
        cfg.min_profit_normal, cfg.min_profit_aggressive,
    )
    eligible = net >= t.min_profit and payload.hops <= t.max_hops

    # Determine opp type
    try:
        opp_type = OppType(payload.type) if payload.type else OppType.flashloan
    except ValueError:
        opp_type = OppType.flashloan

    # Determine style (backward compat)
    try:
        style = StrategyStyle(payload.style) if payload.style else (
            StrategyStyle.flashloan if opp_type in (OppType.flashloan, OppType.triangular, OppType.multihop)
            else StrategyStyle.inventory
        )
    except ValueError:
        style = StrategyStyle.inventory

    # Determine pair from path or explicit pair
    pair = payload.pair
    if not pair and payload.path:
        pair = "/".join([p[:6] + "…" for p in payload.path[:2]]) if len(payload.path) >= 2 else (payload.path[0][:10] if payload.path else "")

    # Score: use provided score or compute
    score = payload.score if payload.score else (net * 1000 + (payload.confidence * 10) - (payload.hops * 5))

    # Determine status
    try:
        status = OppStatus(payload.status) if payload.status and payload.status != "approved" else (
            OppStatus.approved if eligible else OppStatus.skipped
        )
    except ValueError:
        status = OppStatus.approved if eligible else OppStatus.skipped

    opp = Opportunity(
        ext_id=payload.id, pair=pair, network=payload.network,
        style=style, opp_type=opp_type,
        path=json.dumps(payload.path),
        amount_in=payload.amountIn, expected_amount_out=payload.expectedAmountOut,
        net_profit_wei=payload.netProfit, net_profit_usd=payload.netProfitUsd or net,
        buy_cost=payload.buy_cost, sell_proceeds=payload.sell_proceeds,
        cex_fees=payload.cex_fees, dex_fees=payload.dex_fees,
        estimated_gas=payload.estimated_gas, slippage_estimate=payload.slippage_estimate,
        transfer_costs=payload.transfer_costs, flashloan_fee=payload.flashloan_fee,
        price_impact_cost=payload.price_impact_cost, competition_haircut=payload.competition_haircut,
        net_profit=net, hops=payload.hops, confidence=payload.confidence, score=score,
        trade_size=payload.trade_size, source=payload.source,
        status=status,
    )
    db.add(opp)
    db.commit()
    db.refresh(opp)
    return {"ok": True, "id": opp.id, "ext_id": opp.ext_id, "net_profit": net, "eligible": eligible, "score": score}


# ---- Heartbeats ----

@router.post("/webhook/heartbeats")
@router.post("/api/heartbeats")
def push_heartbeat(payload: HeartbeatPush, db: Session = Depends(get_db), _=Depends(check_auth)):
    bot_name = _normalize_bot_name(payload.bot)
    try:
        bot_enum = BotName(bot_name)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown bot: {payload.bot}")
    b = db.query(BotHeartbeat).filter(BotHeartbeat.bot == bot_enum).first()
    if not b:
        b = BotHeartbeat(bot=bot_enum, paused=False)
        db.add(b)
    # New format uses 'status', old format uses 'state'
    state_str = payload.status or payload.state or "running"
    try:
        b.state = BotState(state_str)
    except ValueError:
        b.state = BotState.running
    b.last_heartbeat = _ts_to_dt(payload.timestamp)
    b.last_action = payload.message or payload.last_action or ""
    b.last_error = payload.last_error or (payload.meta.get("error", "") if payload.meta else "")
    db.commit()
    return {"ok": True}


# ---- Trades ----

@router.post("/webhook/trades")
@router.post("/api/trades")
def push_trade(payload: TradeResultPush, db: Session = Depends(get_db), _=Depends(check_auth)):
    cfg = first_config(db)

    # Determine actual profit: prefer netProfitUsd, else actual_profit
    actual_profit = payload.netProfitUsd if payload.netProfitUsd else payload.actual_profit

    # Determine style
    try:
        style = StrategyStyle(payload.style) if payload.style else StrategyStyle.inventory
    except ValueError:
        style = StrategyStyle.inventory

    # Determine pair
    pair = payload.pair
    if not pair and payload.opportunityId:
        pair = payload.opportunityId

    # Link to opportunity by ext_id or numeric id
    opp_id = None
    if payload.opportunityId:
        opp = db.query(Opportunity).filter(Opportunity.ext_id == payload.opportunityId).first()
        if opp:
            opp_id = opp.id
            if payload.status == "success":
                opp.status = OppStatus.executed
            elif payload.status == "failed":
                opp.status = OppStatus.failed
    elif payload.opportunity_id:
        opp_id = payload.opportunity_id
        opp = db.query(Opportunity).get(payload.opportunity_id)
        if opp:
            if payload.status in ("success", "filled"):
                opp.status = OppStatus.executed
            elif payload.status == "failed":
                opp.status = OppStatus.failed

    trade = TradeLog(
        opportunity_id=opp_id, ext_opportunity_id=payload.opportunityId,
        mode=TradeMode(payload.mode), style=style,
        network=payload.network, pair=pair,
        expected_profit=payload.expected_profit or actual_profit,
        actual_profit=actual_profit,
        net_profit_usd=payload.netProfitUsd,
        trade_size=payload.trade_size,
        status=payload.status or payload.detail or "filled",
        detail=payload.detail or payload.notes,
        tx_hash=payload.txHash, amount_in=payload.amountIn, amount_out=payload.amountOut,
        net_profit_wei=payload.netProfit, gas_used=payload.gasUsed,
        notes=payload.notes,
    )
    db.add(trade)

    # Update balances
    if payload.mode == "paper":
        cfg.current_balance_paper += actual_profit
    else:
        cfg.current_balance_real += actual_profit

    # Record capital transaction
    ct = CapitalTransaction(
        type="profit" if actual_profit >= 0 else "loss",
        mode=TradeMode(payload.mode), amount=actual_profit,
        balance_after=cfg.current_balance_paper if payload.mode == "paper" else cfg.current_balance_real,
        note=f"Trade: {pair} on {payload.network}",
    )
    db.add(ct)

    # Update tier progress
    tp = db.query(TierProgress).first()
    bal = cfg.current_balance_paper if not cfg.is_real_execution else cfg.current_balance_real
    if not tp:
        tp = TierProgress(current_tier=1, highest_balance=bal, networks_unlocked="base")
        db.add(tp)
    tp.highest_balance = max(tp.highest_balance, bal)

    # Create notification for trade
    notif = Notification(
        type="trade" if payload.status == "success" else "error",
        title=f"{'✅' if payload.status == 'success' else '❌'} Trade {payload.status}",
        message=f"{pair} on {payload.network} — P/L: ${actual_profit:.2f} ({payload.mode})",
    )
    db.add(notif)

    db.commit()
    return {"ok": True, "balance_paper": cfg.current_balance_paper, "balance_real": cfg.current_balance_real}


# ---- Balance ----

@router.post("/webhook/balance")
@router.post("/api/balance")
def update_balance(payload: BalanceUpdate, db: Session = Depends(get_db), _=Depends(check_auth)):
    cfg = first_config(db)
    if payload.balance_paper is not None:
        cfg.current_balance_paper = payload.balance_paper
    if payload.balance_real is not None:
        cfg.current_balance_real = payload.balance_real
    db.commit()
    return {"ok": True}


# ---- Insights ----

@router.post("/webhook/insights")
@router.post("/api/insights")
def push_insight(payload: InsightPush, db: Session = Depends(get_db), _=Depends(check_auth)):
    ins = InsightLog(
        category=payload.category, label=payload.label, metric=payload.metric,
        value=payload.value, sample_count=payload.sample_count, observation=payload.observation,
    )
    db.add(ins)
    db.commit()
    return {"ok": True}


# ---- Logs ----

@router.post("/webhook/logs")
@router.post("/api/logs")
def push_log(payload: LogPush, db: Session = Depends(get_db), _=Depends(check_auth)):
    log = Log(
        bot=_normalize_bot_name(payload.bot),
        level=payload.level,
        message=payload.message,
        meta=json.dumps(payload.meta) if payload.meta else "{}",
    )
    db.add(log)
    # If it's an error, also create a notification
    if payload.level == "error":
        db.add(Notification(
            type="error", title=f"⚠️ {payload.bot} error",
            message=payload.message,
        ))
    db.commit()
    return {"ok": True}
