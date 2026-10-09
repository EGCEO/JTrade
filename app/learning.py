"""Pattern Learning Engine — statistical analysis of historical trades.

Analyzes completed trade outcomes across multiple dimensions (pair, network,
DEX venue, time-of-day, hop count, trade size, style) to identify which
conditions correlate with profitable executions.  Produces learned
confidence multipliers that adjust how new opportunities are scored, plus
human-readable recommendations.

The engine is purely statistical — no external ML libraries.  It improves
as more trades are logged.
"""

import json
import math
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models import TradeLog, Opportunity, InsightLog


# Minimum sample size before a pattern is considered statistically meaningful.
# Below this, the engine falls back to neutral (1.0 multiplier).
MIN_SAMPLE = 3

# How strongly learned patterns influence confidence (0 = ignore, 1 = full).
# A multiplier of 0.5 means the learned adjustment is blended 50/50 with neutral.
LEARNING_WEIGHT = 0.5

# Cap how much a single dimension can adjust confidence (e.g. ±40%).
MAX_ADJUSTMENT = 0.40


class PatternEngine:
    """Analyse trade history and produce learned patterns + scoring adjustments."""

    # ── Public API ────────────────────────────────────────────────────────────

    def analyze(self, db: Session) -> dict:
        """Run full pattern analysis on all completed trades.

        Returns a dict with patterns, recommendations, and summary stats.
        Also persists key patterns as InsightLog rows.
        """
        trades = db.query(TradeLog).filter(
            TradeLog.status.in_(["success", "failed"])
        ).order_by(TradeLog.created_at).all()

        if not trades:
            return {
                "patterns": [],
                "recommendations": [],
                "summary": {
                    "total_trades_analyzed": 0,
                    "dimensions": 0,
                    "patterns_found": 0,
                    "last_analyzed": datetime.now(timezone.utc).isoformat(),
                },
            }

        # ── Baseline stats ──
        wins = [t for t in trades if t.status == "success" and t.net_result > 0]
        losses = [t for t in trades if t.status == "success" and t.net_result < 0]
        failed = [t for t in trades if t.status == "failed"]
        baseline_win_rate = len(wins) / len(trades) if trades else 0
        baseline_avg = sum(t.net_result for t in trades if t.status == "success") / len(trades) if trades else 0

        # ── Dimension analyses ──
        pair_patterns = self._analyze_dimension(
            trades, key_fn=lambda t: t.pair, dim_name="pair", baseline_wr=baseline_win_rate)
        network_patterns = self._analyze_dimension(
            trades, key_fn=lambda t: t.network, dim_name="network", baseline_wr=baseline_win_rate)
        style_patterns = self._analyze_dimension(
            trades, key_fn=lambda t: t.style, dim_name="style", baseline_wr=baseline_win_rate)
        time_patterns = self._analyze_time_patterns(trades, baseline_win_rate)
        hop_patterns = self._analyze_dimension(
            trades, key_fn=lambda t: str(t.expected_profit > 0 and "profitable_expected" or "not_profitable"),
            dim_name="expected_profit_signal", baseline_wr=baseline_win_rate)

        # Hop-count patterns (from opportunities that were executed)
        hop_patterns = self._analyze_hop_patterns(db, trades, baseline_win_rate)

        all_patterns = (
            pair_patterns + network_patterns + style_patterns
            + time_patterns + hop_patterns
        )

        # Sort by absolute deviation from baseline (most surprising first)
        all_patterns.sort(
            key=lambda p: abs(p["win_rate"] - baseline_win_rate),
            reverse=True,
        )

        # ── Recommendations ──
        recommendations = self._generate_recommendations(
            all_patterns, baseline_win_rate, baseline_avg, trades)

        # ── Persist to InsightLog ──
        self._persist_insights(db, all_patterns, recommendations)

        summary = {
            "total_trades_analyzed": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "failed": len(failed),
            "baseline_win_rate": round(baseline_win_rate * 100, 1),
            "baseline_avg_profit": round(baseline_avg, 4),
            "dimensions": 5,
            "patterns_found": len(all_patterns),
            "recommendations_count": len(recommendations),
            "last_analyzed": datetime.now(timezone.utc).isoformat(),
        }

        return {
            "patterns": all_patterns,
            "recommendations": recommendations,
            "summary": summary,
        }

    def score_opportunity(self, db: Session, pair: str, network: str,
                          style: str, net_profit: float, base_confidence: float,
                          hops: int = 1) -> dict:
        """Adjust an opportunity's confidence based on learned patterns.

        Returns {"confidence": adjusted, "priority_boost": float, "factors": [...]}.
        """
        analysis = self.analyze(db)
        patterns = analysis["patterns"]
        summary = analysis["summary"]

        if summary["total_trades_analyzed"] < MIN_SAMPLE:
            return {
                "confidence": base_confidence,
                "priority_boost": 0,
                "factors": [{"dimension": "insufficient_data",
                             "note": f"Only {summary['total_trades_analyzed']} trades — learning needs {MIN_SAMPLE}+"}],
            }

        baseline_wr = summary["baseline_win_rate"] / 100
        factors = []
        adjustments = []

        for p in patterns:
            multiplier = self._multiplier(p, baseline_wr)
            applies = False

            if p["dimension"] == "pair" and p["key"] == pair:
                applies = True
            elif p["dimension"] == "network" and p["key"] == network:
                applies = True
            elif p["dimension"] == "style" and p["key"] == style:
                applies = True
            elif p["dimension"] == "time_of_day":
                # Check if current hour falls in this bucket
                hour = datetime.now(timezone.utc).hour
                if p["key"] == f"hour_{hour}":
                    applies = True
            elif p["dimension"] == "hop_count" and p["key"] == str(hops):
                applies = True

            if applies:
                adj = (multiplier - 1.0) * LEARNING_WEIGHT
                adj = max(-MAX_ADJUSTMENT, min(MAX_ADJUSTMENT, adj))
                adjustments.append(adj)
                factors.append({
                    "dimension": p["dimension"],
                    "key": p["key"],
                    "win_rate": p["win_rate"],
                    "sample": p["sample_size"],
                    "adjustment": round(adj * 100, 1),
                })

        # Average the applicable adjustments
        if adjustments:
            avg_adj = sum(adjustments) / len(adjustments)
        else:
            avg_adj = 0

        adjusted_confidence = max(1, min(100, base_confidence * (1 + avg_adj)))
        priority_boost = avg_adj * 100  # points added to priority score

        return {
            "confidence": round(adjusted_confidence, 1),
            "priority_boost": round(priority_boost, 2),
            "factors": factors,
        }

    def get_cached_patterns(self, db: Session, limit: int = 100) -> list[dict]:
        """Return patterns from the most recent InsightLog entries."""
        rows = db.query(InsightLog).filter(
            InsightLog.insight_type == "learned_pattern"
        ).order_by(desc(InsightLog.timestamp)).limit(limit).all()
        patterns = []
        for r in rows:
            try:
                patterns.append(json.loads(r.notes))
            except (json.JSONDecodeError, TypeError):
                pass
        return patterns

    def get_cached_recommendations(self, db: Session, limit: int = 50) -> list[dict]:
        """Return recommendations from InsightLog."""
        rows = db.query(InsightLog).filter(
            InsightLog.insight_type == "learned_recommendation"
        ).order_by(desc(InsightLog.timestamp)).limit(limit).all()
        recs = []
        for r in rows:
            try:
                recs.append(json.loads(r.notes))
            except (json.JSONDecodeError, TypeError):
                pass
        return recs

    # ── Internal analysis helpers ────────────────────────────────────────────

    def _analyze_dimension(self, trades, key_fn, dim_name, baseline_wr):
        """Generic dimension analyzer — groups trades by key_fn."""
        groups = defaultdict(list)
        for t in trades:
            k = key_fn(t)
            if k:
                groups[k].append(t)

        patterns = []
        for key, group in groups.items():
            if len(group) < 1:
                continue
            wins = sum(1 for t in group if t.status == "success" and t.net_result > 0)
            total = len(group)
            wr = wins / total if total else 0
            pnl = sum(t.net_result for t in group if t.status == "success")
            avg = pnl / total if total else 0

            patterns.append({
                "dimension": dim_name,
                "key": key,
                "sample_size": total,
                "win_rate": round(wr * 100, 1),
                "total_pnl": round(pnl, 4),
                "avg_profit": round(avg, 4),
                "deviation": round((wr - baseline_wr) * 100, 1),
                "reliable": total >= MIN_SAMPLE,
            })
        return patterns

    def _analyze_time_patterns(self, trades, baseline_wr):
        """Analyze win rate by hour of day (UTC)."""
        hour_groups = defaultdict(list)
        for t in trades:
            if t.created_at:
                hour = t.created_at.replace(tzinfo=timezone.utc).hour
                hour_groups[hour].append(t)

        patterns = []
        for hour, group in sorted(hour_groups.items()):
            wins = sum(1 for t in group if t.status == "success" and t.net_result > 0)
            total = len(group)
            wr = wins / total if total else 0
            pnl = sum(t.net_result for t in group if t.status == "success")

            patterns.append({
                "dimension": "time_of_day",
                "key": f"hour_{hour}",
                "label": f"{hour:02d}:00–{hour:02d}:59 UTC",
                "sample_size": total,
                "win_rate": round(wr * 100, 1),
                "total_pnl": round(pnl, 4),
                "avg_profit": round(pnl / total, 4) if total else 0,
                "deviation": round((wr - baseline_wr) * 100, 1),
                "reliable": total >= MIN_SAMPLE,
            })
        return patterns

    def _analyze_hop_patterns(self, db, trades, baseline_wr):
        """Analyze win rate by hop count (from linked opportunities)."""
        # Build a map of opportunity_id -> hops
        opp_hops = {}
        opps = db.query(Opportunity).all()
        for o in opps:
            opp_hops[o.id] = o.hops

        hop_groups = defaultdict(list)
        for t in trades:
            hops = opp_hops.get(t.opportunity_id, 1) if t.opportunity_id else 1
            hop_groups[hops].append(t)

        patterns = []
        for hops, group in sorted(hop_groups.items()):
            wins = sum(1 for t in group if t.status == "success" and t.net_result > 0)
            total = len(group)
            wr = wins / total if total else 0
            pnl = sum(t.net_result for t in group if t.status == "success")

            patterns.append({
                "dimension": "hop_count",
                "key": str(hops),
                "label": f"{hops} hop{'s' if hops != 1 else ''}",
                "sample_size": total,
                "win_rate": round(wr * 100, 1),
                "total_pnl": round(pnl, 4),
                "avg_profit": round(pnl / total, 4) if total else 0,
                "deviation": round((wr - baseline_wr) * 100, 1),
                "reliable": total >= MIN_SAMPLE,
            })
        return patterns

    def _multiplier(self, pattern, baseline_wr):
        """Compute a confidence multiplier from a pattern.

        A pattern with a 80% win rate vs 50% baseline yields ~1.6.
        Capped to [0.5, 2.0] to prevent extreme swings on small samples.
        """
        if not pattern.get("reliable"):
            return 1.0
        wr = pattern["win_rate"] / 100
        if baseline_wr <= 0:
            return 1.0
        mult = wr / baseline_wr
        return max(0.5, min(2.0, mult))

    def _generate_recommendations(self, patterns, baseline_wr, baseline_avg, trades):
        """Turn patterns into actionable recommendations."""
        recs = []
        reliable = [p for p in patterns if p.get("reliable")]

        # Best-performing pairs
        pair_pats = [p for p in reliable if p["dimension"] == "pair"]
        if pair_pats:
            best = max(pair_pats, key=lambda p: p["win_rate"])
            if best["win_rate"] > baseline_wr * 100 + 10:
                recs.append({
                    "priority": "high",
                    "category": "pair_focus",
                    "title": f"Prioritize {best['key']} opportunities",
                    "detail": f"{best['key']} has a {best['win_rate']:.0f}% win rate "
                              f"({best['sample_size']} trades, +{best['deviation']:.0f}% vs baseline). "
                              f"Consider lowering the min-profit threshold for this pair to capture more.",
                })
            worst = min(pair_pats, key=lambda p: p["win_rate"])
            if worst["win_rate"] < baseline_wr * 100 - 15 and worst["sample_size"] >= MIN_SAMPLE:
                recs.append({
                    "priority": "high",
                    "category": "pair_avoid",
                    "title": f"Be cautious with {worst['key']}",
                    "detail": f"{worst['key']} has only a {worst['win_rate']:.0f}% win rate "
                              f"({worst['sample_size']} trades, {worst['deviation']:.0f}% vs baseline). "
                              f"Consider raising the min-profit threshold or skipping this pair.",
                })

        # Network recommendations
        net_pats = [p for p in reliable if p["dimension"] == "network"]
        if net_pats and len(net_pats) > 1:
            best_net = max(net_pats, key=lambda p: p["win_rate"])
            recs.append({
                "priority": "medium",
                "category": "network_focus",
                "title": f"{best_net['key'].upper()} is your strongest network",
                "detail": f"{best_net['win_rate']:.0f}% win rate on {best_net['key']} "
                          f"({best_net['sample_size']} trades). "
                          f"Route more opportunities through this network when possible.",
            })

        # Time-of-day recommendations
        time_pats = [p for p in reliable if p["dimension"] == "time_of_day"]
        if time_pats:
            best_time = max(time_pats, key=lambda p: p["win_rate"])
            worst_time = min(time_pats, key=lambda p: p["win_rate"])
            if best_time["win_rate"] > baseline_wr * 100 + 15:
                recs.append({
                    "priority": "medium",
                    "category": "time_focus",
                    "title": f"Best trading window: {best_time.get('label', best_time['key'])}",
                    "detail": f"{best_time['win_rate']:.0f}% win rate during this hour "
                              f"({best_time['sample_size']} trades). "
                              f"Scanner could increase scan frequency in this window.",
                })
            if worst_time["win_rate"] < baseline_wr * 100 - 15:
                recs.append({
                    "priority": "low",
                    "category": "time_avoid",
                    "title": f"Avoid trading around {worst_time.get('label', worst_time['key'])}",
                    "detail": f"Only {worst_time['win_rate']:.0f}% win rate "
                              f"({worst_time['sample_size']} trades). "
                              f"Consider pausing auto-execution during this window.",
                })

        # Hop count recommendations
        hop_pats = [p for p in reliable if p["dimension"] == "hop_count"]
        if len(hop_pats) >= 2:
            best_hop = max(hop_pats, key=lambda p: p["win_rate"])
            recs.append({
                "priority": "medium",
                "category": "hop_optimization",
                "title": f"{best_hop.get('label', best_hop['key'])} routes perform best",
                "detail": f"{best_hop['win_rate']:.0f}% win rate with {best_hop['key']} hop(s) "
                          f"({best_hop['sample_size']} trades). "
                          f"Prefer this hop count when routing opportunities.",
            })

        # Style recommendations
        style_pats = [p for p in reliable if p["dimension"] == "style"]
        if len(style_pats) >= 2:
            best_style = max(style_pats, key=lambda p: p["win_rate"])
            recs.append({
                "priority": "low",
                "category": "style_optimization",
                "title": f"{best_style['key']} trades outperform",
                "detail": f"{best_style['key']} has a {best_style['win_rate']:.0f}% win rate "
                          f"vs {min(style_pats, key=lambda p: p['win_rate'])['win_rate']:.0f}% for the other style. "
                          f"Lean toward {best_style['key']} when both are available.",
            })

        # Overall learning progress
        total = len(trades)
        if total >= 20:
            recent = trades[-20:]
            recent_wr = sum(1 for t in recent if t.status == "success" and t.net_result > 0) / 20
            early = trades[:20]
            early_wr = sum(1 for t in early if t.status == "success" and t.net_result > 0) / 20
            if recent_wr > early_wr + 0.1:
                recs.append({
                    "priority": "info",
                    "category": "learning_progress",
                    "title": "Win rate is improving over time",
                    "detail": f"Early win rate: {early_wr*100:.0f}% → Recent win rate: {recent_wr*100:.0f}%. "
                              f"The system is learning effectively. Keep logging all trades.",
                })
            elif recent_wr < early_wr - 0.1:
                recs.append({
                    "priority": "warning",
                    "category": "learning_progress",
                    "title": "Win rate is declining",
                    "detail": f"Early win rate: {early_wr*100:.0f}% → Recent win rate: {recent_wr*100:.0f}%. "
                              f"Market conditions may have shifted. Review recent failures for new patterns.",
                })

        return recs

    def _persist_insights(self, db: Session, patterns, recommendations):
        """Store patterns and recommendations as InsightLog entries."""
        # Clear old learned entries to avoid unbounded growth
        db.query(InsightLog).filter(
            InsightLog.insight_type.in_(["learned_pattern", "learned_recommendation"])
        ).delete()

        for p in patterns:
            db.add(InsightLog(
                insight_type="learned_pattern",
                pair=p["key"] if p["dimension"] == "pair" else "",
                network=p["key"] if p["dimension"] == "network" else "",
                metric=p["dimension"],
                value=p["win_rate"],
                notes=json.dumps(p),
            ))

        for r in recommendations:
            db.add(InsightLog(
                insight_type="learned_recommendation",
                metric=r["category"],
                value=1 if r["priority"] == "high" else 0,
                notes=json.dumps(r),
            ))

        db.commit()


# Singleton
pattern_engine = PatternEngine()
