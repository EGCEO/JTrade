"""Webhook endpoints for external bots (Scanner, Calculator, Execution).

The dashboard never holds private keys or signs transactions. External bots
push opportunities, heartbeats, and results here, and read the current mode /
thresholds / unlocked networks. A shared API key (WEBHOOK_API_KEY env) gates
these endpoints when set; in dev it is open.
"""
import os
from datetime import datetime
from fastapi import APIRouter, Request, Depends, Header, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import (
    User, Config, Opportunity, TradeLog, BotHeartbeat, AccountSnapshot,
    TierProgress, InsightLog, OppStatus, BotName, BotState, TradeMode, StrategyStyle,
)
from app.schemas import (
    OpportunityPush, TradeResultPush, HeartbeatPush, BalanceUpdate, InsightPush,
)
from app.prioritization import calculate_net_profit, get_current_thresholds, is_network_unlocked
from app.routers.auth import ensure_config

router = APIRouter(prefix="/webhook")

WEBHOOK_KEY = os.environ.get("WEBHOOK_API_KEY", "")


def check_key(x_api_key: str = Header(default="")):
    if WEBHOOK_KEY and x_api_key != WEBHOOK_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


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


@router.get("/status")
def webhook_status(db: Session = Depends(get_db)):
    """External bots read current mode, thresholds, risk limits, unlocked networks."""
    cfg = first_config(db)
    balance = cfg.current_balance_paper if not cfg.is_real_execution else cfg.current_balance_real
    t = get_current_thresholds(balance, cfg.is_aggressive)
    return {
        "mode": "real" if cfg.is_real_execution else "paper",
        "is_aggressive": cfg.is_aggressive,
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
    }


@router.post("/opportunities")
def push_opportunity(payload: OpportunityPush, db: Session = Depends(get_db), _=Depends(check_key)):
    cfg = first_config(db)
    balance = cfg.current_balance_paper if not cfg.is_real_execution else cfg.current_balance_real
    # Reject opportunities on locked networks
    if not is_network_unlocked(payload.network, balance):
        raise HTTPException(status_code=403, detail=f"Network '{payload.network}' not unlocked yet")
    net = calculate_net_profit(
        payload.sell_proceeds, payload.buy_cost, payload.cex_fees, payload.dex_fees,
        payload.estimated_gas, payload.slippage_estimate, payload.transfer_costs, payload.flashloan_fee,
    )
    t = get_current_thresholds(balance, cfg.is_aggressive)
    eligible = net >= t.min_profit and payload.hops <= t.max_hops
    confidence = payload.confidence
    score = net * 1000 + (confidence * 10) - (payload.hops * 5)
    opp = Opportunity(
        pair=payload.pair, network=payload.network,
        style=StrategyStyle(payload.style),
        buy_cost=payload.buy_cost, sell_proceeds=payload.sell_proceeds,
        cex_fees=payload.cex_fees, dex_fees=payload.dex_fees,
        estimated_gas=payload.estimated_gas, slippage_estimate=payload.slippage_estimate,
        transfer_costs=payload.transfer_costs, flashloan_fee=payload.flashloan_fee,
        net_profit=net, hops=payload.hops, confidence=confidence, score=score,
        trade_size=payload.trade_size, source=payload.source,
        status=OppStatus.approved if eligible else OppStatus.skipped,
    )
    db.add(opp)
    db.commit()
    db.refresh(opp)
    return {"ok": True, "id": opp.id, "net_profit": net, "eligible": eligible, "score": score}


@router.post("/heartbeats")
def push_heartbeat(payload: HeartbeatPush, db: Session = Depends(get_db), _=Depends(check_key)):
    b = db.query(BotHeartbeat).filter(BotHeartbeat.bot == BotName(payload.bot)).first()
    if not b:
        b = BotHeartbeat(bot=BotName(payload.bot), paused=False)
        db.add(b)
    b.state = BotState(payload.state)
    b.last_heartbeat = datetime.utcnow()
    b.last_action = payload.last_action
    b.last_error = payload.last_error
    db.commit()
    return {"ok": True}


@router.post("/trades")
def push_trade(payload: TradeResultPush, db: Session = Depends(get_db), _=Depends(check_key)):
    cfg = first_config(db)
    trade = TradeLog(
        opportunity_id=payload.opportunity_id,
        mode=TradeMode(payload.mode), style=StrategyStyle(payload.style),
        network=payload.network, pair=payload.pair,
        expected_profit=payload.expected_profit, actual_profit=payload.actual_profit,
        trade_size=payload.trade_size, status=payload.status, detail=payload.detail,
    )
    db.add(trade)
    # Update balances
    if payload.mode == "paper":
        cfg.current_balance_paper += payload.actual_profit
    else:
        cfg.current_balance_real += payload.actual_profit
    # Update tier progress
    tp = db.query(TierProgress).first()
    bal = cfg.current_balance_paper if not cfg.is_real_execution else cfg.current_balance_real
    if not tp:
        tp = TierProgress(current_tier=1, highest_balance=bal, networks_unlocked="base")
        db.add(tp)
    tp.highest_balance = max(tp.highest_balance, bal)
    db.commit()
    return {"ok": True, "balance_paper": cfg.current_balance_paper, "balance_real": cfg.current_balance_real}


@router.post("/balance")
def update_balance(payload: BalanceUpdate, db: Session = Depends(get_db), _=Depends(check_key)):
    cfg = first_config(db)
    if payload.balance_paper is not None:
        cfg.current_balance_paper = payload.balance_paper
    if payload.balance_real is not None:
        cfg.current_balance_real = payload.balance_real
    db.commit()
    return {"ok": True}


@router.post("/insights")
def push_insight(payload: InsightPush, db: Session = Depends(get_db), _=Depends(check_key)):
    ins = InsightLog(
        category=payload.category, label=payload.label, metric=payload.metric,
        value=payload.value, sample_count=payload.sample_count, observation=payload.observation,
    )
    db.add(ins)
    db.commit()
    return {"ok": True}
