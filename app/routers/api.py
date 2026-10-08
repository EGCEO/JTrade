from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from app.database import get_db
from app.models import (
    User, Config, Opportunity, TradeLog, BotHeartbeat, AccountSnapshot,
    TierProgress, InsightLog, Log, Notification, CapitalTransaction,
    PerformanceSnapshot, OppStatus, OppType, BotName, BotState, TradeMode, StrategyStyle,
    ACTIVE_BOTS,
)
from app.auth import get_current_user, require_user
from app.routers.auth import ensure_config
from app.schemas import ConfigUpdate, RealExecutionConfirm, CapitalAction
from app.prioritization import (
    calculate_net_profit, get_current_thresholds, prioritize_opportunities,
    passes_risk_checks, get_account_level, get_next_level, level_progress_pct,
    get_network_tier, get_next_network_tier, is_network_unlocked,
)
import app.prioritization as pz

router = APIRouter(prefix="/api")


def get_cfg(db: Session, request: Request) -> Config:
    user = require_user(request, db)
    return ensure_config(db, user)


def cfg_to_dict(cfg: Config) -> dict:
    return {c.name: getattr(cfg, c.name) for c in cfg.__table__.columns}


def _balance(cfg: Config) -> float:
    return cfg.current_balance_paper if not cfg.is_real_execution else cfg.current_balance_real


# ---- Config ----

@router.get("/config")
def read_config(request: Request, db: Session = Depends(get_db)):
    cfg = get_cfg(db, request)
    d = cfg_to_dict(cfg)
    balance = _balance(cfg)
    t = get_current_thresholds(balance, cfg.is_aggressive,
                               cfg.max_hops_normal, cfg.max_hops_aggressive,
                               cfg.min_profit_normal, cfg.min_profit_aggressive)
    d["computed_min_profit"] = t.min_profit
    d["computed_max_size_percent"] = t.max_size_percent
    d["computed_max_hops"] = t.max_hops
    d["computed_allow_more_pairs"] = t.allow_more_pairs
    d["account_level"] = get_account_level(balance)
    d["next_level"] = get_next_level(balance)
    d["level_progress_pct"] = level_progress_pct(balance)
    d["network_tier"] = get_network_tier(balance)
    d["next_network_tier"] = get_next_network_tier(balance)
    d["unlocked_networks"] = get_network_tier(balance)["networks"]
    return d


@router.put("/config")
def update_config(payload: ConfigUpdate, request: Request, db: Session = Depends(get_db)):
    cfg = get_cfg(db, request)
    data = payload.dict(exclude_unset=True)
    for k, v in data.items():
        if v is not None and hasattr(cfg, k):
            setattr(cfg, k, v)
    db.commit()
    db.refresh(cfg)
    return read_config(request, db)


@router.post("/config/aggressive")
def toggle_aggressive(request: Request, db: Session = Depends(get_db)):
    cfg = get_cfg(db, request)
    cfg.is_aggressive = not cfg.is_aggressive
    db.commit()
    db.refresh(cfg)
    return {"is_aggressive": cfg.is_aggressive}


@router.post("/config/auto-compound")
def toggle_auto_compound(request: Request, db: Session = Depends(get_db)):
    cfg = get_cfg(db, request)
    cfg.auto_compound = not cfg.auto_compound
    db.commit()
    db.refresh(cfg)
    return {"auto_compound": cfg.auto_compound}


@router.post("/config/real")
def toggle_real(payload: RealExecutionConfirm, request: Request, db: Session = Depends(get_db)):
    cfg = get_cfg(db, request)
    if not cfg.is_real_execution:
        if not payload.confirm:
            raise HTTPException(status_code=428, detail="Confirmation required to enable Real Execution Mode")
        if payload.phrase.strip().upper() != "I UNDERSTAND THE RISKS":
            raise HTTPException(status_code=428, detail="Confirmation phrase does not match")
    cfg.is_real_execution = not cfg.is_real_execution
    db.commit()
    db.refresh(cfg)
    return {"is_real_execution": cfg.is_real_execution}


# ---- Master controls ----

@router.post("/system/start")
def system_start(request: Request, db: Session = Depends(get_db)):
    cfg = get_cfg(db, request)
    cfg.is_running = True
    db.commit()
    db.add(Notification(type="success", title="▶️ System Started",
                        message="Bots are now active. Scanner, Quant, Guardian, and Execution will begin working."))
    db.commit()
    return {"is_running": True}


@router.post("/system/pause")
def system_pause(request: Request, db: Session = Depends(get_db)):
    cfg = get_cfg(db, request)
    cfg.is_running = False
    db.commit()
    db.add(Notification(type="warning", title="⏸️ System Paused", message="All bots paused."))
    db.commit()
    return {"is_running": False}


@router.post("/system/stop")
def system_stop(request: Request, db: Session = Depends(get_db)):
    cfg = get_cfg(db, request)
    cfg.is_running = False
    db.commit()
    db.add(Notification(type="warning", title="⏹️ System Stopped", message="All bots stopped."))
    db.commit()
    return {"is_running": False}


@router.post("/system/kill")
def system_kill(request: Request, db: Session = Depends(get_db)):
    cfg = get_cfg(db, request)
    cfg.is_running = False
    db.commit()
    db.add(Notification(type="error", title="🛑 KILL SWITCH ACTIVATED",
                        message="Emergency stop executed. All trading halted immediately."))
    db.commit()
    return {"is_running": False, "kill_switch": True}


@router.post("/system/emergency-stop")
def emergency_stop(request: Request, db: Session = Depends(get_db)):
    """Instantly pause all four bots and cancel pending transactions across all accounts."""
    cfg = get_cfg(db, request)
    cfg.is_running = False

    # Pause all four bots
    bots = db.query(BotHeartbeat).filter(BotHeartbeat.bot.in_(ACTIVE_BOTS)).all()
    paused_bots = []
    for b in bots:
        b.paused = True
        b.state = BotState.paused
        paused_bots.append(b.bot.value)

    # Cancel all pending/approved opportunities
    cancelled = db.query(Opportunity).filter(
        Opportunity.status.in_([OppStatus.pending, OppStatus.approved])
    ).all()
    cancel_count = 0
    for o in cancelled:
        o.status = OppStatus.skipped
        cancel_count += 1

    db.add(Notification(
        type="error", title="🚨 EMERGENCY STOP ACTIVATED",
        message=f"All bots paused ({', '.join(paused_bots)}). {cancel_count} pending opportunities cancelled. "
                f"System halted immediately across all accounts.",
    ))
    db.commit()
    return {
        "ok": True,
        "is_running": False,
        "paused_bots": paused_bots,
        "cancelled_opportunities": cancel_count,
    }


# ---- Bot Secret ----

@router.get("/bot-secret")
def get_bot_secret(request: Request, db: Session = Depends(get_db)):
    cfg = get_cfg(db, request)
    return {"bot_secret": cfg.bot_secret or "(not set)"}


@router.post("/bot-secret/regenerate")
def regenerate_bot_secret(request: Request, db: Session = Depends(get_db)):
    import secrets as _s
    cfg = get_cfg(db, request)
    cfg.bot_secret = _s.token_urlsafe(32)
    db.commit()
    db.refresh(cfg)
    db.add(Notification(type="warning", title="🔑 BOT_SECRET Regenerated",
                        message="Bot secret changed. All external bots must update their Authorization header."))
    db.commit()
    return {"bot_secret": cfg.bot_secret}


# ---- Opportunities ----

@router.get("/opportunities")
def list_opportunities(request: Request, db: Session = Depends(get_db), limit: int = 100):
    cfg = get_cfg(db, request)
    opps = db.query(Opportunity).order_by(desc(Opportunity.score)).limit(limit).all()
    balance = _balance(cfg)
    opp_dicts = []
    for o in opps:
        d = {c.name: getattr(o, c.name) for c in o.__table__.columns}
        if isinstance(d.get("style"), StrategyStyle):
            d["style"] = d["style"].value
        if isinstance(d.get("opp_type"), OppType):
            d["opp_type"] = d["opp_type"].value
        if isinstance(d.get("status"), OppStatus):
            d["status"] = d["status"].value
        opp_dicts.append(d)
    scored = prioritize_opportunities(opp_dicts, balance, cfg.is_aggressive,
                                      cfg.max_hops_normal, cfg.max_hops_aggressive)
    return {
        "thresholds": get_current_thresholds(balance, cfg.is_aggressive,
                                              cfg.max_hops_normal, cfg.max_hops_aggressive,
                                              cfg.min_profit_normal, cfg.min_profit_aggressive).__dict__,
        "opportunities": [{"score": s.score, "net": s.net, **s.opportunity} for s in scored],
        "total": len(opps),
        "eligible": len(scored),
    }


@router.delete("/opportunities/{opp_id}")
def delete_opportunity(opp_id: int, request: Request, db: Session = Depends(get_db)):
    get_cfg(db, request)
    o = db.query(Opportunity).get(opp_id)
    if not o:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(o)
    db.commit()
    return {"ok": True}


@router.post("/opportunities/clear")
def clear_opportunities(request: Request, db: Session = Depends(get_db)):
    get_cfg(db, request)
    db.query(Opportunity).filter(Opportunity.status == OppStatus.pending).delete(synchronize_session=False)
    db.commit()
    return {"ok": True}


# ---- Bots ----

def default_bots(db: Session):
    for b in ACTIVE_BOTS:
        if not db.query(BotHeartbeat).filter(BotHeartbeat.bot == b).first():
            db.add(BotHeartbeat(bot=b, state=BotState.offline, paused=False))
    db.commit()


@router.get("/bots")
def list_bots(request: Request, db: Session = Depends(get_db)):
    get_cfg(db, request)
    default_bots(db)
    bots = db.query(BotHeartbeat).filter(BotHeartbeat.bot.in_(ACTIVE_BOTS)).all()
    out = []
    for b in bots:
        d = {c.name: getattr(b, c.name) for c in b.__table__.columns}
        if isinstance(d.get("bot"), BotName):
            d["bot"] = d["bot"].value
        if isinstance(d.get("state"), BotState):
            d["state"] = d["state"].value
        if d.get("last_heartbeat"):
            age = (datetime.utcnow() - d["last_heartbeat"]).total_seconds()
            d["stale"] = age > 60
        else:
            d["stale"] = True
        out.append(d)
    return out


@router.post("/bots/{bot}/pause")
def pause_bot(bot: str, request: Request, db: Session = Depends(get_db)):
    get_cfg(db, request)
    bot_name = "quant" if bot == "calculator" else bot
    b = db.query(BotHeartbeat).filter(BotHeartbeat.bot == BotName(bot_name)).first()
    if not b:
        raise HTTPException(status_code=404, detail="Bot not found")
    b.paused = True
    b.state = BotState.paused
    db.commit()
    return {"ok": True, "paused": True}


@router.post("/bots/{bot}/resume")
def resume_bot(bot: str, request: Request, db: Session = Depends(get_db)):
    get_cfg(db, request)
    bot_name = "quant" if bot == "calculator" else bot
    b = db.query(BotHeartbeat).filter(BotHeartbeat.bot == BotName(bot_name)).first()
    if not b:
        raise HTTPException(status_code=404, detail="Bot not found")
    b.paused = False
    b.state = BotState.running
    db.commit()
    return {"ok": True, "paused": False}


@router.post("/bots/{bot}/test")
def test_bot_heartbeat(bot: str, request: Request, db: Session = Depends(get_db)):
    get_cfg(db, request)
    bot_name = "quant" if bot == "calculator" else bot
    b = db.query(BotHeartbeat).filter(BotHeartbeat.bot == BotName(bot_name)).first()
    if not b:
        b = BotHeartbeat(bot=BotName(bot_name), paused=False)
        db.add(b)
    b.state = BotState.running
    b.last_heartbeat = datetime.utcnow()
    b.last_action = "Test heartbeat from dashboard"
    b.last_error = ""
    db.commit()
    return {"ok": True, "bot": bot_name}


# ---- Trades ----

@router.get("/trades")
def list_trades(request: Request, db: Session = Depends(get_db), limit: int = 200,
                mode: str = None, style: str = None, network: str = None):
    get_cfg(db, request)
    q = db.query(TradeLog).order_by(desc(TradeLog.executed_at))
    if mode:
        q = q.filter(TradeLog.mode == TradeMode(mode))
    if style:
        q = q.filter(TradeLog.style == StrategyStyle(style))
    if network:
        q = q.filter(TradeLog.network == network)
    trades = q.limit(limit).all()
    out = []
    for t in trades:
        d = {c.name: getattr(t, c.name) for c in t.__table__.columns}
        if isinstance(d.get("mode"), TradeMode):
            d["mode"] = d["mode"].value
        if isinstance(d.get("style"), StrategyStyle):
            d["style"] = d["style"].value
        # Compute gas cost and slippage for detailed view
        d["gas_cost_usd"] = t.gas_cost_usd or 0.0
        d["slippage_cost"] = t.slippage_cost or 0.0
        # If gas_cost_usd not stored, estimate from gas_used or config
        if not d["gas_cost_usd"] and t.gas_used:
            try:
                d["gas_cost_usd"] = float(t.gas_used) * 0.00002  # rough Gwei estimate
            except (ValueError, TypeError):
                pass
        # If slippage not stored, compute from expected vs actual
        if not d["slippage_cost"] and t.expected_profit:
            d["slippage_cost"] = round(max(0, t.expected_profit - t.actual_profit), 6)
        if d.get("executed_at"):
            d["executed_at"] = d["executed_at"].isoformat()
        out.append(d)
    return out


# ---- Capital ----

@router.get("/capital/transactions")
def list_capital_txns(request: Request, db: Session = Depends(get_db), limit: int = 100):
    get_cfg(db, request)
    rows = db.query(CapitalTransaction).order_by(desc(CapitalTransaction.created_at)).limit(limit).all()
    out = []
    for r in rows:
        d = {c.name: getattr(r, c.name) for c in r.__table__.columns}
        if isinstance(d.get("mode"), TradeMode):
            d["mode"] = d["mode"].value
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        out.append(d)
    return out


@router.post("/capital/withdraw")
def capital_withdraw(payload: CapitalAction, request: Request, db: Session = Depends(get_db)):
    cfg = get_cfg(db, request)
    if payload.mode == "paper":
        cfg.current_balance_paper -= payload.amount
        bal_after = cfg.current_balance_paper
    else:
        cfg.current_balance_real -= payload.amount
        bal_after = cfg.current_balance_real
    db.add(CapitalTransaction(type="withdraw", mode=TradeMode(payload.mode),
                              amount=-payload.amount, balance_after=bal_after, note=payload.note or "Withdrawal"))
    db.add(Notification(type="info", title="💸 Withdrawal",
                        message=f"Withdrew ${payload.amount:.2f} ({payload.mode}). Balance: ${bal_after:.2f}"))
    db.commit()
    return {"ok": True, "balance": bal_after}


@router.post("/capital/compound")
def capital_compound(request: Request, db: Session = Depends(get_db)):
    """Manual compound: move all paper profits into the working balance."""
    cfg = get_cfg(db, request)
    profit = cfg.current_balance_paper - cfg.starting_capital
    if profit <= 0:
        raise HTTPException(status_code=400, detail="No profits to compound")
    cfg.current_balance_paper += 0  # already included; just record it
    bal_after = cfg.current_balance_paper
    db.add(CapitalTransaction(type="compound", mode=TradeMode.paper,
                              amount=profit, balance_after=bal_after, note="Manual compound"))
    db.add(Notification(type="success", title="🔄 Compounded",
                        message=f"Compounded ${profit:.2f} paper profits. Balance: ${bal_after:.2f}"))
    db.commit()
    return {"ok": True, "compounded": profit, "balance": bal_after}


@router.post("/capital/deposit")
def capital_deposit(payload: CapitalAction, request: Request, db: Session = Depends(get_db)):
    cfg = get_cfg(db, request)
    if payload.mode == "paper":
        cfg.current_balance_paper += payload.amount
        bal_after = cfg.current_balance_paper
    else:
        cfg.current_balance_real += payload.amount
        bal_after = cfg.current_balance_real
    db.add(CapitalTransaction(type="deposit", mode=TradeMode(payload.mode),
                              amount=payload.amount, balance_after=bal_after, note=payload.note or "Deposit"))
    db.add(Notification(type="success", title="💰 Deposit",
                        message=f"Deposited ${payload.amount:.2f} ({payload.mode}). Balance: ${bal_after:.2f}"))
    db.commit()
    return {"ok": True, "balance": bal_after}


# ---- Compounding ----

@router.get("/compounding")
def compounding_stats(request: Request, db: Session = Depends(get_db)):
    cfg = get_cfg(db, request)
    snaps = db.query(AccountSnapshot).order_by(AccountSnapshot.timestamp).all()
    series = []
    for s in snaps:
        series.append({
            "timestamp": s.timestamp.isoformat() if s.timestamp else None,
            "balance_paper": s.balance_paper,
            "balance_real": s.balance_real,
        })
    paper_trades = db.query(TradeLog).filter(TradeLog.mode == TradeMode.paper).all()
    real_trades = db.query(TradeLog).filter(TradeLog.mode == TradeMode.real).all()

    def perf(trades):
        if not trades:
            return {"count": 0, "total_pnl": 0.0, "wins": 0, "win_rate": 0.0}
        pnl = sum(t.actual_profit for t in trades)
        wins = sum(1 for t in trades if t.actual_profit > 0)
        return {"count": len(trades), "total_pnl": round(pnl, 4), "wins": wins,
                "win_rate": round(wins / len(trades) * 100, 2)}

    return {
        "starting_capital": cfg.starting_capital,
        "current_balance_paper": cfg.current_balance_paper,
        "current_balance_real": cfg.current_balance_real,
        "return_paper_pct": round((cfg.current_balance_paper - cfg.starting_capital) / cfg.starting_capital * 100, 2) if cfg.starting_capital else 0,
        "return_real_pct": round((cfg.current_balance_real - cfg.starting_capital) / cfg.starting_capital * 100, 2) if cfg.starting_capital else 0,
        "series": series,
        "paper": perf(paper_trades),
        "real": perf(real_trades),
    }


# ---- Tiers / Levels ----

@router.get("/tiers")
def tiers_info(request: Request, db: Session = Depends(get_db)):
    cfg = get_cfg(db, request)
    balance = _balance(cfg)
    tp = db.query(TierProgress).first()
    return {
        "account_level": get_account_level(balance),
        "next_level": get_next_level(balance),
        "level_progress_pct": level_progress_pct(balance),
        "network_tier": get_network_tier(balance),
        "next_network_tier": get_next_network_tier(balance),
        "network_tiers": pz.NETWORK_TIERS,
        "levels": pz.LEVELS,
        "highest_balance": tp.highest_balance if tp else balance,
    }


# ---- Insights ----

@router.get("/insights")
def insights(request: Request, db: Session = Depends(get_db)):
    get_cfg(db, request)
    rows = db.query(InsightLog).order_by(desc(InsightLog.created_at)).limit(50).all()
    out = []
    for r in rows:
        d = {c.name: getattr(r, c.name) for c in r.__table__.columns}
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        out.append(d)
    trades = db.query(TradeLog).all()
    by_pair = {}
    for t in trades:
        key = t.pair or "unknown"
        by_pair.setdefault(key, {"count": 0, "wins": 0, "pnl": 0.0})
        by_pair[key]["count"] += 1
        if t.actual_profit > 0:
            by_pair[key]["wins"] += 1
        by_pair[key]["pnl"] += t.actual_profit
    derived = []
    for pair, st in by_pair.items():
        derived.append({
            "category": "by_pair", "label": pair, "metric": "win_rate",
            "value": round(st["wins"] / st["count"] * 100, 2) if st["count"] else 0,
            "sample_count": st["count"],
            "observation": f"{pair}: {st['count']} trades, {st['wins']} wins, PnL {st['pnl']:.2f}",
        })
    return {"logged": out, "derived": derived, "total_trades": len(trades)}


# ---- Performance & Analytics ----

@router.get("/performance")
def performance(request: Request, db: Session = Depends(get_db)):
    cfg = get_cfg(db, request)
    balance = _balance(cfg)

    paper_trades = db.query(TradeLog).filter(TradeLog.mode == TradeMode.paper).order_by(TradeLog.executed_at).all()
    real_trades = db.query(TradeLog).filter(TradeLog.mode == TradeMode.real).order_by(TradeLog.executed_at).all()

    def calc_stats(trades):
        if not trades:
            return {"count": 0, "total_pnl": 0, "wins": 0, "losses": 0, "win_rate": 0,
                    "avg_profit": 0, "avg_loss": 0, "drawdown": 0, "max_drawdown": 0}
        pnl = sum(t.actual_profit for t in trades)
        wins = [t for t in trades if t.actual_profit > 0]
        losses = [t for t in trades if t.actual_profit <= 0]
        avg_profit = sum(t.actual_profit for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t.actual_profit for t in losses) / len(losses) if losses else 0
        # Drawdown calculation
        cumulative = 0
        peak = 0
        max_dd = 0
        dd = 0
        for t in trades:
            cumulative += t.actual_profit
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd
        return {
            "count": len(trades), "total_pnl": round(pnl, 4),
            "wins": len(wins), "losses": len(losses),
            "win_rate": round(len(wins) / len(trades) * 100, 2),
            "avg_profit": round(avg_profit, 4), "avg_loss": round(avg_loss, 4),
            "drawdown": round(dd, 4), "max_drawdown": round(max_dd, 4),
        }

    # Build cumulative P/L series
    def pnl_series(trades):
        cumulative = 0
        pts = []
        for t in trades:
            cumulative += t.actual_profit
            pts.append({
                "timestamp": t.executed_at.isoformat() if t.executed_at else None,
                "pnl": round(cumulative, 4),
            })
        return pts

    # Daily P/L series
    def daily_pnl(trades):
        by_day = {}
        for t in trades:
            day = t.executed_at.strftime("%Y-%m-%d") if t.executed_at else "unknown"
            by_day.setdefault(day, 0.0)
            by_day[day] += t.actual_profit
        return [{"day": d, "pnl": round(v, 4)} for d, v in sorted(by_day.items())]

    # Period stats
    now = datetime.utcnow()
    def period_stats(trades, hours):
        cutoff = now - timedelta(hours=hours)
        recent = [t for t in trades if t.executed_at and t.executed_at >= cutoff]
        return calc_stats(recent)

    return {
        "balance": balance,
        "starting_capital": cfg.starting_capital,
        "paper": calc_stats(paper_trades),
        "real": calc_stats(real_trades),
        "paper_series": pnl_series(paper_trades),
        "real_series": pnl_series(real_trades),
        "paper_daily": daily_pnl(paper_trades),
        "real_daily": daily_pnl(real_trades),
        "trend": {
            "24h": {"paper": period_stats(paper_trades, 24), "real": period_stats(real_trades, 24)},
            "7d": {"paper": period_stats(paper_trades, 168), "real": period_stats(real_trades, 168)},
            "30d": {"paper": period_stats(paper_trades, 720), "real": period_stats(real_trades, 720)},
        },
    }


# ---- Analytics (30-day charts) ----

@router.get("/analytics")
def analytics(request: Request, db: Session = Depends(get_db)):
    """30-day analytics: net profit growth, gas fee trends, execution success rates."""
    cfg = get_cfg(db, request)
    now = datetime.utcnow()
    cutoff = now - timedelta(days=30)

    trades = db.query(TradeLog).filter(TradeLog.executed_at >= cutoff).order_by(TradeLog.executed_at).all()

    # Group by day
    days = []
    by_day = {}
    for i in range(30):
        day = (now - timedelta(days=29 - i)).strftime("%Y-%m-%d")
        days.append(day)
        by_day[day] = {"trades": [], "pnl": 0.0, "gas": 0.0, "wins": 0, "count": 0}

    for t in trades:
        day = t.executed_at.strftime("%Y-%m-%d") if t.executed_at else None
        if day and day in by_day:
            by_day[day]["trades"].append(t)
            by_day[day]["pnl"] += t.actual_profit or 0
            by_day[day]["gas"] += t.gas_cost_usd or 0
            by_day[day]["count"] += 1
            if (t.actual_profit or 0) > 0:
                by_day[day]["wins"] += 1

    # Build series
    cumulative = 0
    pnl_series = []
    gas_series = []
    success_series = []
    for day in days:
        d = by_day[day]
        cumulative += d["pnl"]
        pnl_series.append(round(cumulative, 4))
        gas_series.append(round(d["gas"], 4))
        success_rate = round(d["wins"] / d["count"] * 100, 1) if d["count"] > 0 else 0
        success_series.append(success_rate)

    # Summary stats
    total_pnl = round(sum(d["pnl"] for d in by_day.values()), 4)
    total_gas = round(sum(d["gas"] for d in by_day.values()), 4)
    total_trades = sum(d["count"] for d in by_day.values())
    total_wins = sum(d["wins"] for d in by_day.values())
    overall_success = round(total_wins / total_trades * 100, 1) if total_trades > 0 else 0

    return {
        "days": days,
        "pnl_cumulative": pnl_series,
        "gas_daily": gas_series,
        "success_rate_daily": success_series,
        "summary": {
            "total_pnl": total_pnl,
            "total_gas": total_gas,
            "total_trades": total_trades,
            "overall_success_rate": overall_success,
            "best_day_pnl": round(max(d["pnl"] for d in by_day.values()), 4) if by_day else 0,
            "worst_day_pnl": round(min(d["pnl"] for d in by_day.values()), 4) if by_day else 0,
        },
    }


# ---- Risk Monitor ----

@router.get("/risk")
def risk_monitor(request: Request, db: Session = Depends(get_db)):
    cfg = get_cfg(db, request)
    balance = _balance(cfg)
    is_aggr = cfg.is_aggressive

    # Daily loss calculation
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    mode = TradeMode.real if cfg.is_real_execution else TradeMode.paper
    today_trades = db.query(TradeLog).filter(
        TradeLog.mode == mode, TradeLog.executed_at >= today_start
    ).all()
    daily_pnl = sum(t.actual_profit for t in today_trades)
    daily_loss = abs(min(0, daily_pnl))

    daily_loss_limit_usd = balance * cfg.daily_loss_limit
    daily_loss_pct = round(daily_loss / daily_loss_limit_usd * 100, 2) if daily_loss_limit_usd > 0 else 0

    max_risk = cfg.max_risk_per_trade_aggressive if is_aggr else cfg.max_risk_per_trade
    max_risk_usd = balance * max_risk

    max_exposure = cfg.max_open_exposure
    max_exposure_usd = balance * max_exposure

    # Count open/approved opportunities as current exposure
    open_opps = db.query(Opportunity).filter(
        Opportunity.status.in_([OppStatus.pending, OppStatus.approved])
    ).all()
    current_exposure = sum(o.trade_size for o in open_opps)
    exposure_pct = round(current_exposure / max_exposure_usd * 100, 2) if max_exposure_usd > 0 else 0

    t = get_current_thresholds(balance, is_aggr,
                               cfg.max_hops_normal, cfg.max_hops_aggressive,
                               cfg.min_profit_normal, cfg.min_profit_aggressive)

    return {
        "balance": balance,
        "is_aggressive": is_aggr,
        "is_running": cfg.is_running,
        "is_real_execution": cfg.is_real_execution,
        "daily_pnl": round(daily_pnl, 4),
        "daily_loss": round(daily_loss, 4),
        "daily_loss_limit_usd": round(daily_loss_limit_usd, 2),
        "daily_loss_pct": daily_loss_pct,
        "daily_loss_limit_pct": cfg.daily_loss_limit,
        "max_risk_per_trade_pct": max_risk,
        "max_risk_per_trade_usd": round(max_risk_usd, 2),
        "max_open_exposure_pct": max_exposure,
        "max_open_exposure_usd": round(max_exposure_usd, 2),
        "current_exposure": round(current_exposure, 2),
        "exposure_pct": exposure_pct,
        "min_profit_threshold": t.min_profit,
        "max_hops": t.max_hops,
        "open_opportunities": len(open_opps),
        "kill_switch_active": not cfg.is_running,
    }


# ---- Per-Bot Risk Status ----

@router.get("/risk/bots")
def risk_per_bot(request: Request, db: Session = Depends(get_db)):
    """Per-bot risk limits and safety threshold status for at-a-glance exposure monitoring."""
    cfg = get_cfg(db, request)
    balance = _balance(cfg)
    is_aggr = cfg.is_aggressive

    # System-wide risk values
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    mode = TradeMode.real if cfg.is_real_execution else TradeMode.paper
    today_trades = db.query(TradeLog).filter(
        TradeLog.mode == mode, TradeLog.executed_at >= today_start
    ).all()
    daily_pnl = sum(t.actual_profit for t in today_trades)
    daily_loss = abs(min(0, daily_pnl))
    daily_loss_limit_usd = balance * cfg.daily_loss_limit
    daily_loss_pct = round(daily_loss / daily_loss_limit_usd * 100, 2) if daily_loss_limit_usd > 0 else 0

    max_risk = cfg.max_risk_per_trade_aggressive if is_aggr else cfg.max_risk_per_trade
    max_risk_usd = round(balance * max_risk, 2)
    max_exposure = cfg.max_open_exposure
    max_exposure_usd = round(balance * max_exposure, 2)

    open_opps = db.query(Opportunity).filter(
        Opportunity.status.in_([OppStatus.pending, OppStatus.approved])
    ).all()
    current_exposure = round(sum(o.trade_size for o in open_opps), 2)
    exposure_pct = round(current_exposure / max_exposure_usd * 100, 2) if max_exposure_usd > 0 else 0

    t = get_current_thresholds(balance, is_aggr,
                               cfg.max_hops_normal, cfg.max_hops_aggressive,
                               cfg.min_profit_normal, cfg.min_profit_aggressive)

    # Per-bot heartbeat data
    default_bots(db)
    bots = db.query(BotHeartbeat).filter(BotHeartbeat.bot.in_(ACTIVE_BOTS)).all()

    bot_meta = {
        "scanner": {"name": "Scanner", "icon": "🔍", "role": "Opportunity Detection",
                     "thresholds": {"Min Net Profit": f"${t.min_profit:.2f}", "Max Hops": str(t.max_hops),
                                    "Networks": ", ".join(get_network_tier(balance)["networks"])}},
        "quant": {"name": "Quant", "icon": "🧮", "role": "Scoring & Filtering",
                   "thresholds": {"Min Score EV": f"${cfg.score_min_expected_value_usd:.2f}",
                                  "Min Exec Prob": f"{cfg.score_min_execution_probability:.0%}",
                                  "Min Net Profit": f"${cfg.score_min_net_profit_usd:.2f}"}},
        "guardian": {"name": "Guardian", "icon": "🛡️", "role": "Risk Gate & Exposure Control",
                      "thresholds": {"Max Risk/Trade": f"{max_risk:.0%} (${max_risk_usd})",
                                     "Daily Loss Limit": f"{cfg.daily_loss_limit:.0%} (${daily_loss_limit_usd:.2f})",
                                     "Max Open Exposure": f"{max_exposure:.0%} (${max_exposure_usd})"}},
        "execution": {"name": "Execution", "icon": "⚡", "role": "Trade Execution",
                       "thresholds": {"Current Exposure": f"${current_exposure} ({exposure_pct}%)",
                                      "Daily Loss Used": f"${daily_loss:.2f} ({daily_loss_pct}%)",
                                      "Kill Switch": "ACTIVE" if not cfg.is_running else "armed"}},
    }

    bot_list = []
    for b in bots:
        bot_name = b.bot.value if hasattr(b.bot, "value") else str(b.bot)
        meta = bot_meta.get(bot_name, {})
        is_active = b.state == BotState.running and not b.paused
        stale = True
        if b.last_heartbeat:
            stale = (datetime.utcnow() - b.last_heartbeat).total_seconds() > 60
        bot_list.append({
            "bot": bot_name,
            "name": meta.get("name", bot_name),
            "icon": meta.get("icon", "🤖"),
            "role": meta.get("role", ""),
            "state": b.state.value if hasattr(b.state, "value") else str(b.state),
            "active": is_active,
            "paused": b.paused,
            "stale": stale,
            "last_action": b.last_action or "—",
            "last_error": b.last_error or "",
            "thresholds": meta.get("thresholds", {}),
        })

    return {
        "balance": round(balance, 2),
        "is_aggressive": is_aggr,
        "is_running": cfg.is_running,
        "daily_loss_pct": daily_loss_pct,
        "daily_loss_limit_pct": cfg.daily_loss_limit,
        "exposure_pct": exposure_pct,
        "current_exposure": current_exposure,
        "max_exposure_usd": max_exposure_usd,
        "bots": bot_list,
    }


# ---- Daily Summary ----

@router.get("/daily-summary")
def daily_summary(request: Request, db: Session = Depends(get_db)):
    """Total daily profit across all active bots, with per-bot breakdown."""
    cfg = get_cfg(db, request)
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    # Today's trades
    today_trades = db.query(TradeLog).filter(TradeLog.executed_at >= today_start).all()
    total_profit = round(sum(t.actual_profit for t in today_trades), 4)
    wins = [t for t in today_trades if t.actual_profit > 0]
    losses = [t for t in today_trades if t.actual_profit <= 0]

    # Per-pair breakdown
    by_pair = {}
    for t in today_trades:
        key = t.pair or "unknown"
        by_pair.setdefault(key, {"count": 0, "pnl": 0.0, "wins": 0})
        by_pair[key]["count"] += 1
        by_pair[key]["pnl"] += t.actual_profit
        if t.actual_profit > 0:
            by_pair[key]["wins"] += 1

    best_pair = max(by_pair.items(), key=lambda x: x[1]["pnl"]) if by_pair else None

    # Today's opportunities by status (pipeline activity)
    today_opps = db.query(Opportunity).filter(Opportunity.created_at >= today_start).all()
    opp_by_status = {}
    for o in today_opps:
        s = o.status.value if hasattr(o.status, "value") else str(o.status)
        opp_by_status[s] = opp_by_status.get(s, 0) + 1

    # Per-bot summary
    bots = db.query(BotHeartbeat).filter(BotHeartbeat.bot.in_(ACTIVE_BOTS)).all()
    bot_summaries = []
    for b in bots:
        bot_name = b.bot.value if hasattr(b.bot, "value") else str(b.bot)
        is_active = b.state == BotState.running and not b.paused
        if bot_name == "scanner":
            activity = f"{len(today_opps)} opportunities found"
        elif bot_name == "quant":
            scored = sum(1 for o in today_opps if o.score and o.score > 0)
            activity = f"{scored} opportunities scored"
        elif bot_name == "guardian":
            approved = opp_by_status.get("approved", 0) + opp_by_status.get("executed", 0)
            activity = f"{approved} risk-checked"
        elif bot_name == "execution":
            activity = f"{len(today_trades)} trades executed"
        else:
            activity = b.last_action or "—"
        bot_summaries.append({
            "bot": bot_name,
            "active": is_active,
            "state": b.state.value if hasattr(b.state, "value") else str(b.state),
            "activity": activity,
        })

    active_bot_count = sum(1 for b in bot_summaries if b["active"])

    return {
        "total_daily_profit": total_profit,
        "trade_count": len(today_trades),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": round(len(wins) / len(today_trades) * 100, 2) if today_trades else 0,
        "best_pair": {"pair": best_pair[0], "pnl": round(best_pair[1]["pnl"], 4)} if best_pair else None,
        "active_bots": active_bot_count,
        "total_bots": len(ACTIVE_BOTS),
        "bots": bot_summaries,
        "by_pair": [{"pair": k, "count": v["count"], "pnl": round(v["pnl"], 4),
                      "wins": v["wins"]} for k, v in sorted(by_pair.items(), key=lambda x: -x[1]["pnl"])],
    }


# ---- Learning Engine ----

@router.get("/learning/patterns")
def learning_patterns(request: Request, db: Session = Depends(get_db)):
    """Return all learned patterns from trade history analysis."""
    get_cfg(db, request)
    from app.learning import get_all_patterns
    return {"patterns": get_all_patterns(db)}


@router.post("/learning/analyze")
def learning_analyze(request: Request, db: Session = Depends(get_db)):
    """Trigger pattern analysis on current trade history and auto-tune Quant thresholds."""
    cfg = get_cfg(db, request)
    from app.learning import analyze_trades, auto_tune_thresholds
    result = analyze_trades(db)
    # Automatically tune Quant thresholds based on discovered patterns
    tune_result = auto_tune_thresholds(db, cfg)
    result["auto_tune"] = tune_result
    return result


@router.get("/learning/recommendations")
def learning_recommendations(request: Request, db: Session = Depends(get_db)):
    """Return actionable, high-confidence recommendations."""
    get_cfg(db, request)
    from app.learning import get_recommendations
    return {"recommendations": get_recommendations(db)}


@router.get("/learning/summary")
def learning_summary(request: Request, db: Session = Depends(get_db)):
    """High-level summary of the learning engine state."""
    get_cfg(db, request)
    from app.learning import get_learning_summary
    return get_learning_summary(db)


@router.post("/learning/auto-tune")
def learning_auto_tune(request: Request, db: Session = Depends(get_db)):
    """Auto-tune Quant bot scoring thresholds based on learned patterns."""
    cfg = get_cfg(db, request)
    from app.learning import auto_tune_thresholds
    return auto_tune_thresholds(db, cfg)


# ---- Google Sheets Export ----

@router.get("/sheets/status")
def sheets_status(request: Request, db: Session = Depends(get_db)):
    """Check Google Sheets export configuration and status."""
    get_cfg(db, request)
    from app.sheets_export import get_export_status
    return get_export_status()


@router.post("/sheets/export")
def sheets_export(request: Request, db: Session = Depends(get_db)):
    """Manually export daily summary to Google Sheets."""
    get_cfg(db, request)
    from app.sheets_export import export_to_sheets
    return export_to_sheets(db)


@router.get("/sheets/test")
def sheets_test(request: Request, db: Session = Depends(get_db)):
    """Test Google Sheets connection."""
    get_cfg(db, request)
    from app.sheets_export import test_sheets_connection
    return test_sheets_connection()


@router.post("/sheets/auto/start")
def sheets_auto_start(request: Request, db: Session = Depends(get_db)):
    """Start automatic daily export to Google Sheets."""
    get_cfg(db, request)
    from app.sheets_export import start_auto_export
    return start_auto_export()


@router.post("/sheets/auto/stop")
def sheets_auto_stop(request: Request, db: Session = Depends(get_db)):
    """Stop automatic daily export."""
    get_cfg(db, request)
    from app.sheets_export import stop_auto_export
    return stop_auto_export()


# ---- Real Execution Safety Gate ----

@router.get("/real-execution/prerequisites")
def real_execution_prerequisites(request: Request, db: Session = Depends(get_db)):
    """Server-side prerequisite check for enabling Real Execution Mode.

    Validates all safety conditions before the 4-step gate can proceed.
    """
    cfg = get_cfg(db, request)

    # Paper trading track record
    paper_trades = db.query(TradeLog).filter(TradeLog.mode == TradeMode.paper).all()
    paper_count = len(paper_trades)
    paper_pnl = sum(t.actual_profit for t in paper_trades)
    paper_wins = sum(1 for t in paper_trades if t.actual_profit > 0)
    paper_win_rate = round(paper_wins / paper_count * 100, 2) if paper_count else 0

    # Bot status
    default_bots(db)
    bots = db.query(BotHeartbeat).filter(BotHeartbeat.bot.in_(ACTIVE_BOTS)).all()
    active_bots = sum(1 for b in bots if b.state == BotState.running and not b.paused)

    checks = [
        {
            "id": "wallet",
            "label": "Wallet address configured",
            "ok": bool(cfg.wallet_address),
            "detail": "Connect your wallet in the Wallet Connect page",
        },
        {
            "id": "real_balance",
            "label": "Real balance set (>$0)",
            "ok": cfg.current_balance_real > 0,
            "detail": f"Current real balance: ${cfg.current_balance_real:.2f} — deposit real capital first",
        },
        {
            "id": "paper_trades",
            "label": "At least 10 paper trades completed",
            "ok": paper_count >= 10,
            "detail": f"{paper_count} paper trades logged — need at least 10",
        },
        {
            "id": "paper_profitable",
            "label": "Paper trading is profitable (positive P/L)",
            "ok": paper_pnl > 0,
            "detail": f"Paper P/L: ${paper_pnl:.2f} — system should be profitable before going live",
        },
        {
            "id": "paper_win_rate",
            "label": "Paper win rate above 40%",
            "ok": paper_win_rate >= 40,
            "detail": f"Paper win rate: {paper_win_rate}% — should be above 40% before real trading",
        },
        {
            "id": "risk_limits",
            "label": "Risk limits configured (daily loss + max risk)",
            "ok": cfg.daily_loss_limit > 0 and cfg.max_risk_per_trade > 0,
            "detail": f"Daily loss limit: {cfg.daily_loss_limit:.0%}, Max risk: {cfg.max_risk_per_trade:.0%}",
        },
        {
            "id": "bots_active",
            "label": "At least 2 bots active (running, not paused)",
            "ok": active_bots >= 2,
            "detail": f"{active_bots}/{len(ACTIVE_BOTS)} bots active — need at least 2",
        },
    ]

    all_pass = all(c["ok"] for c in checks)
    return {
        "all_pass": all_pass,
        "checks": checks,
        "paper_trades": paper_count,
        "paper_pnl": round(paper_pnl, 2),
        "paper_win_rate": paper_win_rate,
        "active_bots": active_bots,
        "real_balance": cfg.current_balance_real,
        "is_real_execution": cfg.is_real_execution,
    }


# ---- Logs ----

@router.get("/logs")
def list_logs(request: Request, db: Session = Depends(get_db), limit: int = 200,
              bot: str = None, level: str = None):
    get_cfg(db, request)
    q = db.query(Log).order_by(desc(Log.created_at))
    if bot:
        bot_name = "quant" if bot == "calculator" else bot
        q = q.filter(Log.bot == bot_name)
    if level:
        q = q.filter(Log.level == level)
    rows = q.limit(limit).all()
    out = []
    for r in rows:
        d = {c.name: getattr(r, c.name) for c in r.__table__.columns}
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        out.append(d)
    return out


# ---- Notifications ----

@router.get("/notifications")
def list_notifications(request: Request, db: Session = Depends(get_db), limit: int = 50):
    get_cfg(db, request)
    rows = db.query(Notification).order_by(desc(Notification.created_at)).limit(limit).all()
    out = []
    for r in rows:
        d = {c.name: getattr(r, c.name) for c in r.__table__.columns}
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        out.append(d)
    unread = db.query(Notification).filter(Notification.read == False).count()
    return {"notifications": out, "unread": unread}


@router.post("/notifications/{nid}/read")
def mark_notification_read(nid: int, request: Request, db: Session = Depends(get_db)):
    get_cfg(db, request)
    n = db.query(Notification).get(nid)
    if n:
        n.read = True
        db.commit()
    return {"ok": True}


@router.post("/notifications/read-all")
def mark_all_read(request: Request, db: Session = Depends(get_db)):
    get_cfg(db, request)
    db.query(Notification).update({Notification.read: True})
    db.commit()
    return {"ok": True}


@router.post("/notifications/clear")
def clear_notifications(request: Request, db: Session = Depends(get_db)):
    get_cfg(db, request)
    db.query(Notification).delete()
    db.commit()
    return {"ok": True}


# ---- Onboarding ----

@router.get("/onboarding")
def onboarding_status(request: Request, db: Session = Depends(get_db)):
    cfg = get_cfg(db, request)
    balance = _balance(cfg)
    bots = db.query(BotHeartbeat).filter(BotHeartbeat.bot.in_(ACTIVE_BOTS)).all()
    active_bots = sum(1 for b in bots if b.state == BotState.running and not b.paused)
    trades = db.query(TradeLog).count()
    opps = db.query(Opportunity).count()

    steps = [
        {"id": "login", "label": "Login to dashboard", "done": True},
        {"id": "wallet", "label": "Connect wallet (MetaMask)", "done": bool(cfg.wallet_address)},
        {"id": "capital", "label": "Set starting capital", "done": cfg.starting_capital > 0},
        {"id": "bots", "label": "Verify all 4 bot heartbeats", "done": active_bots >= 4},
        {"id": "test_opp", "label": "Receive first test opportunity", "done": opps > 0},
        {"id": "first_trade", "label": "Complete first paper trade", "done": trades > 0},
        {"id": "review_risk", "label": "Review risk monitor", "done": False},
        {"id": "review_perf", "label": "Review performance analytics", "done": False},
        {"id": "understand_real", "label": "Understand Real Execution risks", "done": False},
        {"id": "ready", "label": "Hit Start to begin trading", "done": cfg.is_running},
    ]
    done_count = sum(1 for s in steps if s["done"])
    return {"steps": steps, "done": done_count, "total": len(steps),
            "pct": round(done_count / len(steps) * 100, 1)}
