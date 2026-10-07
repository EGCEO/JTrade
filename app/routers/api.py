from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from app.database import get_db
from app.models import (
    User, Config, Opportunity, TradeLog, BotHeartbeat, AccountSnapshot,
    TierProgress, InsightLog, OppStatus, BotName, BotState, TradeMode, StrategyStyle,
)
from app.auth import get_current_user, require_user
from app.routers.auth import ensure_config
from app.schemas import ConfigUpdate
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


@router.get("/config")
def read_config(request: Request, db: Session = Depends(get_db)):
    cfg = get_cfg(db, request)
    d = cfg_to_dict(cfg)
    # attach computed thresholds
    balance = cfg.current_balance_paper if not cfg.is_real_execution else cfg.current_balance_real
    t = get_current_thresholds(balance, cfg.is_aggressive)
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


@router.post("/config/real")
def toggle_real(request: Request, db: Session = Depends(get_db), confirm: bool = False):
    """Real Execution toggle requires explicit confirmation."""
    cfg = get_cfg(db, request)
    if not cfg.is_real_execution and not confirm:
        raise HTTPException(status_code=428, detail="Confirmation required to enable Real Execution Mode")
    cfg.is_real_execution = not cfg.is_real_execution
    db.commit()
    db.refresh(cfg)
    return {"is_real_execution": cfg.is_real_execution}


# ---- Opportunities ----

@router.get("/opportunities")
def list_opportunities(request: Request, db: Session = Depends(get_db), limit: int = 100):
    cfg = get_cfg(db, request)
    opps = db.query(Opportunity).order_by(desc(Opportunity.score)).limit(limit).all()
    balance = cfg.current_balance_paper if not cfg.is_real_execution else cfg.current_balance_real
    # Re-score live so the table always reflects current thresholds
    opp_dicts = []
    for o in opps:
        d = {c.name: getattr(o, c.name) for c in o.__table__.columns}
        if isinstance(d.get("style"), StrategyStyle):
            d["style"] = d["style"].value
        if isinstance(d.get("status"), OppStatus):
            d["status"] = d["status"].value
        opp_dicts.append(d)
    scored = prioritize_opportunities(opp_dicts, balance, cfg.is_aggressive)
    return {
        "thresholds": get_current_thresholds(balance, cfg.is_aggressive).__dict__,
        "opportunities": [
            {"score": s.score, "net": s.net, **s.opportunity} for s in scored
        ],
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
    for b in BotName:
        if not db.query(BotHeartbeat).filter(BotHeartbeat.bot == b).first():
            db.add(BotHeartbeat(bot=b, state=BotState.offline, paused=False))
    db.commit()


@router.get("/bots")
def list_bots(request: Request, db: Session = Depends(get_db)):
    get_cfg(db, request)
    default_bots(db)
    bots = db.query(BotHeartbeat).all()
    out = []
    for b in bots:
        d = {c.name: getattr(b, c.name) for c in b.__table__.columns}
        if isinstance(d.get("bot"), BotName):
            d["bot"] = d["bot"].value
        if isinstance(d.get("state"), BotState):
            d["state"] = d["state"].value
        # stale if no heartbeat in 60s
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
    b = db.query(BotHeartbeat).filter(BotHeartbeat.bot == BotName(bot)).first()
    if not b:
        raise HTTPException(status_code=404, detail="Bot not found")
    b.paused = True
    b.state = BotState.paused
    db.commit()
    return {"ok": True, "paused": True}


@router.post("/bots/{bot}/resume")
def resume_bot(bot: str, request: Request, db: Session = Depends(get_db)):
    get_cfg(db, request)
    b = db.query(BotHeartbeat).filter(BotHeartbeat.bot == BotName(bot)).first()
    if not b:
        raise HTTPException(status_code=404, detail="Bot not found")
    b.paused = False
    b.state = BotState.running
    db.commit()
    return {"ok": True, "paused": False}


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
        out.append(d)
    return out


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
    # Performance from trades
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
    balance = cfg.current_balance_paper if not cfg.is_real_execution else cfg.current_balance_real
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

    # Derive simple stats from trade logs
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
