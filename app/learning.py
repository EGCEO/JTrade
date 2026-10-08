"""Pattern recognition & learning engine.

Analyzes historical trade data to identify which conditions (pair, network,
strategy type, hop count, trade-size range, time-of-day) lead to profitable
executions. Stores learned patterns in the database and produces adjustment
factors that feed back into the scoring pipeline so the Quant bot can
weight opportunities based on what actually worked in the past.

The engine is purely statistical — no ML libraries required. It groups
trades by multiple dimensions, computes win-rate / avg-profit / sample-size
for each group, and derives a confidence-weighted adjustment factor that
can nudge the execution probability up or down for future opportunities.

Key functions:
  - analyze_trades(db)         → scans TradeLog, upserts LearnedPattern rows
  - get_pattern_adjustments(db) → returns all active patterns as a dict
  - get_success_rate(db, opp)   → learned success rate for a specific opportunity
  - get_recommendations(db)     → human-readable actionable insights
"""
import math
from datetime import datetime, timedelta
from collections import defaultdict
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models import (
    TradeLog, Opportunity, LearnedPattern, Log, Notification,
    OppType, StrategyStyle, TradeMode,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum sample size before a pattern is considered statistically meaningful.
# Below this, the engine won't generate a strong recommendation.
MIN_SAMPLES = 5

# How much the learned adjustment can move the execution probability.
# The base score from the Quant engine is always preserved; learning only
# nudges within this band so a single bad streak can't permanently kill a pair.
MAX_ADJUSTMENT = 0.20  # ±20% relative nudge

# Confidence grows with sample size (logarithmic) up to 1.0.
# confidence = 1 - exp(-samples / 15)  →  ~15 trades ≈ 63% confidence
CONFIDENCE_K = 15.0


def _confidence(sample_count: int) -> float:
    """Statistical confidence in a pattern based on sample size (0..1)."""
    if sample_count <= 0:
        return 0.0
    return round(1.0 - math.exp(-sample_count / CONFIDENCE_K), 4)


def _win_rate(trades: list) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.actual_profit > 0)
    return round(wins / len(trades), 4)


def _avg_profit(trades: list) -> float:
    if not trades:
        return 0.0
    return round(sum(t.actual_profit for t in trades) / len(trades), 6)


def _avg_loss(trades: list) -> float:
    losses = [t.actual_profit for t in trades if t.actual_profit <= 0]
    if not losses:
        return 0.0
    return round(sum(losses) / len(losses), 6)


def _size_bucket(trade_size: float) -> str:
    """Bucket trade sizes into ranges for pattern grouping."""
    if trade_size < 50:
        return "micro (<$50)"
    elif trade_size < 200:
        return "small ($50-$200)"
    elif trade_size < 1000:
        return "medium ($200-$1k)"
    elif trade_size < 5000:
        return "large ($1k-$5k)"
    else:
        return "whale (>$5k)"


def _time_bucket(dt: datetime) -> str:
    """UTC hour bucket for time-of-day patterns."""
    if not dt:
        return "unknown"
    h = dt.hour
    if 0 <= h < 6:
        return "00-06 UTC"
    elif 6 <= h < 12:
        return "06-12 UTC"
    elif 12 <= h < 18:
        return "12-18 UTC"
    else:
        return "18-24 UTC"


# ---------------------------------------------------------------------------
# Pattern analysis
# ---------------------------------------------------------------------------

def _group_key(dimension: str, trade: TradeLog) -> str | None:
    """Extract the group label for a given dimension from a trade record."""
    if dimension == "pair":
        return trade.pair or "unknown"
    elif dimension == "network":
        return trade.network or "unknown"
    elif dimension == "style":
        return trade.style.value if hasattr(trade.style, "value") else str(trade.style)
    elif dimension == "hops":
        # Hops aren't stored on TradeLog directly; use the linked opportunity
        return None  # handled separately via opportunity join
    elif dimension == "size":
        return _size_bucket(trade.trade_size or 0)
    elif dimension == "time":
        return _time_bucket(trade.executed_at)
    elif dimension == "pair_network":
        return f"{trade.pair or 'unknown'}@{trade.network or 'unknown'}"
    return None


DIMENSIONS = ["pair", "network", "style", "size", "time", "pair_network"]


def analyze_trades(db: Session) -> dict:
    """Scan all TradeLog records, compute patterns per dimension, upsert LearnedPattern rows.

    Returns a summary dict with counts.
    """
    trades = db.query(TradeLog).order_by(TradeLog.executed_at).all()

    if not trades:
        return {"ok": False, "error": "No trades to analyze", "patterns": 0}

    # For hop-based patterns, join with opportunities
    opp_hops = {}
    for t in trades:
        if t.opportunity_id:
            opp = db.query(Opportunity).get(t.opportunity_id)
            if opp:
                opp_hops[t.id] = opp.hops

    # Group trades by each dimension
    groups = defaultdict(lambda: defaultdict(list))  # dim → label → [trades]

    for t in trades:
        for dim in DIMENSIONS:
            key = _group_key(dim, t)
            if key is not None:
                groups[dim][key].append(t)
        # Hops dimension (special)
        h = opp_hops.get(t.id)
        if h is not None:
            groups["hops"][str(h)].append(t)

    all_dims = DIMENSIONS + ["hops"]
    patterns_upserted = 0
    patterns_removed = 0

    # Clear old patterns (full recompute each analysis)
    old_count = db.query(LearnedPattern).count()
    db.query(LearnedPattern).delete()

    for dim in all_dims:
        for label, dim_trades in groups[dim].items():
            sample = len(dim_trades)
            wr = _win_rate(dim_trades)
            ap = _avg_profit(dim_trades)
            al = _avg_loss(dim_trades)
            total_pnl = round(sum(t.actual_profit for t in dim_trades), 4)
            conf = _confidence(sample)

            # Adjustment factor: relative to a 50% baseline win rate.
            # Positive wr > 0.5 → boost; negative wr < 0.5 → penalize.
            # Scaled by confidence and capped at MAX_ADJUSTMENT.
            wr_delta = wr - 0.5
            adjustment = round(wr_delta * conf * 2 * MAX_ADJUSTMENT / MAX_ADJUSTMENT, 4)
            # Simpler: adjustment = clamp(wr_delta * conf * 2, -MAX_ADJUSTMENT, MAX_ADJUSTMENT)
            adjustment = max(-MAX_ADJUSTMENT, min(MAX_ADJUSTMENT, round(wr_delta * conf * 2, 4)))

            # Recommendation text
            if sample < MIN_SAMPLES:
                recommendation = f"Insufficient data ({sample} trades) — no recommendation yet"
                actionable = False
            elif wr >= 0.70 and ap > 0:
                recommendation = f"Strong performer: {wr:.0%} win rate, avg +${ap:.4f}/trade. Prioritize {label} {dim}."
                actionable = True
            elif wr >= 0.55 and ap > 0:
                recommendation = f"Good performer: {wr:.0%} win rate, avg +${ap:.4f}/trade. Slight boost for {label} {dim}."
                actionable = True
            elif wr < 0.40 and ap < 0:
                recommendation = f"Poor performer: {wr:.0%} win rate, avg ${ap:.4f}/trade. Reduce exposure to {label} {dim}."
                actionable = True
            elif wr < 0.50 and ap < 0:
                recommendation = f"Below average: {wr:.0%} win rate. Be cautious with {label} {dim}."
                actionable = True
            else:
                recommendation = f"Neutral: {wr:.0%} win rate, avg ${ap:.4f}/trade for {label} {dim}."
                actionable = False

            p = LearnedPattern(
                dimension=dim,
                label=label,
                win_rate=wr,
                avg_profit=ap,
                avg_loss=al,
                total_pnl=total_pnl,
                sample_count=sample,
                confidence=conf,
                adjustment_factor=adjustment,
                recommendation=recommendation,
                is_actionable=actionable,
            )
            db.add(p)
            patterns_upserted += 1

    db.commit()

    # Log the analysis
    db.add(Log(
        bot="quant",
        level="info",
        message=f"🧠 Learning engine analyzed {len(trades)} trades → {patterns_upserted} patterns across {len(all_dims)} dimensions",
        meta='{"engine": "learning", "trades": %d, "patterns": %d}' % (len(trades), patterns_upserted),
    ))
    db.add(Notification(
        type="info",
        title="🧠 Learning Engine Updated",
        message=f"Analyzed {len(trades)} trades. {patterns_upserted} patterns identified across {len(all_dims)} dimensions.",
    ))
    db.commit()

    return {
        "ok": True,
        "trades_analyzed": len(trades),
        "patterns_identified": patterns_upserted,
        "dimensions": all_dims,
        "previous_patterns_removed": old_count,
    }


# ---------------------------------------------------------------------------
# Query learned patterns
# ---------------------------------------------------------------------------

def get_all_patterns(db: Session) -> list[dict]:
    rows = db.query(LearnedPattern).order_by(
        desc(LearnedPattern.confidence), desc(LearnedPattern.total_pnl)
    ).all()
    out = []
    for r in rows:
        d = {
            "id": r.id,
            "dimension": r.dimension,
            "label": r.label,
            "win_rate": round(r.win_rate * 100, 1),
            "avg_profit": r.avg_profit,
            "avg_loss": r.avg_loss,
            "total_pnl": r.total_pnl,
            "sample_count": r.sample_count,
            "confidence": round(r.confidence * 100, 1),
            "adjustment_factor": r.adjustment_factor,
            "recommendation": r.recommendation,
            "is_actionable": r.is_actionable,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        out.append(d)
    return out


def get_recommendations(db: Session) -> list[dict]:
    """Return only actionable, high-confidence recommendations sorted by impact."""
    rows = db.query(LearnedPattern).filter(
        LearnedPattern.is_actionable == True,
        LearnedPattern.confidence > 0.3,
    ).order_by(desc(LearnedPattern.adjustment_factor)).all()
    out = []
    for r in rows:
        out.append({
            "dimension": r.dimension,
            "label": r.label,
            "win_rate": round(r.win_rate * 100, 1),
            "avg_profit": r.avg_profit,
            "sample_count": r.sample_count,
            "confidence": round(r.confidence * 100, 1),
            "adjustment_factor": r.adjustment_factor,
            "recommendation": r.recommendation,
        })
    return out


def get_pattern_lookup(db: Session) -> dict:
    """Build a fast lookup dict: {dimension: {label: adjustment_factor}}.

    Used by the scoring pipeline to apply learned adjustments.
    """
    rows = db.query(LearnedPattern).all()
    lookup = defaultdict(dict)
    for r in rows:
        if r.confidence > 0.2:  # only use patterns with enough data
            lookup[r.dimension][r.label] = r.adjustment_factor
    return dict(lookup)


def get_success_rate_for_opp(db: Session, pair: str, network: str,
                              style: str, trade_size: float,
                              executed_at: datetime = None) -> float | None:
    """Look up the learned win rate for a specific opportunity profile.

    Combines adjustments from matching patterns across dimensions.
    Returns a value 0..1 (the adjusted success rate), or None if no patterns.
    """
    lookup = get_pattern_lookup(db)
    if not lookup:
        return None

    adjustments = []
    # Pair
    if pair and pair in lookup.get("pair", {}):
        adjustments.append(lookup["pair"][pair])
    # Network
    if network and network in lookup.get("network", {}):
        adjustments.append(lookup["network"][network])
    # Style
    if style and style in lookup.get("style", {}):
        adjustments.append(lookup["style"][style])
    # Size bucket
    sb = _size_bucket(trade_size or 0)
    if sb in lookup.get("size", {}):
        adjustments.append(lookup["size"][sb])
    # Pair+network combo
    pn = f"{pair or 'unknown'}@{network or 'unknown'}"
    if pn in lookup.get("pair_network", {}):
        adjustments.append(lookup["pair_network"][pn])
    # Time bucket
    if executed_at:
        tb = _time_bucket(executed_at)
        if tb in lookup.get("time", {}):
            adjustments.append(lookup["time"][tb])

    if not adjustments:
        return None

    # Average the adjustments and apply to a 0.5 baseline
    avg_adj = sum(adjustments) / len(adjustments)
    learned_rate = 0.5 + avg_adj
    return max(0.05, min(0.95, round(learned_rate, 4)))


def get_learning_summary(db: Session) -> dict:
    """High-level summary of the learning engine state."""
    total = db.query(LearnedPattern).count()
    actionable = db.query(LearnedPattern).filter(LearnedPattern.is_actionable == True).count()
    high_conf = db.query(LearnedPattern).filter(LearnedPattern.confidence > 0.5).count()
    trades = db.query(TradeLog).count()

    # Best and worst patterns
    best = db.query(LearnedPattern).filter(
        LearnedPattern.sample_count >= MIN_SAMPLES
    ).order_by(desc(LearnedPattern.total_pnl)).first()
    worst = db.query(LearnedPattern).filter(
        LearnedPattern.sample_count >= MIN_SAMPLES
    ).order_by(LearnedPattern.total_pnl).first()

    return {
        "total_patterns": total,
        "actionable_patterns": actionable,
        "high_confidence_patterns": high_conf,
        "trades_analyzed": trades,
        "best_pattern": {
            "dimension": best.dimension, "label": best.label,
            "win_rate": round(best.win_rate * 100, 1),
            "total_pnl": best.total_pnl, "sample_count": best.sample_count,
            "recommendation": best.recommendation,
        } if best else None,
        "worst_pattern": {
            "dimension": worst.dimension, "label": worst.label,
            "win_rate": round(worst.win_rate * 100, 1),
            "total_pnl": worst.total_pnl, "sample_count": worst.sample_count,
            "recommendation": worst.recommendation,
        } if worst else None,
    }
