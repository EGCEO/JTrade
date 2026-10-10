"""EV-based opportunity scoring — Python port of bot/src/math/scoring.ts.

Calculates execution probability using smooth exponential penalties for gas,
hops, price impact/slippage, liquidity, and historical success rate, then
derives expected value (EV) as the final ranking score.
"""

import math
from dataclasses import dataclass, field


@dataclass
class ScoreInput:
    net_profit_usd: float = 0
    gas_cost_usd: float = 0
    hops: int = 1
    price_impact_bps: float = 0
    slippage_bps: float = 0
    liquidity_score: float = 0  # 0–1
    recent_success_rate: float | None = None  # 0–1


@dataclass
class ScoreConfig:
    min_net_profit_usd: float = 0.75
    min_expected_value_usd: float = 0.5
    min_execution_probability: float = 0.35
    failure_gas_fraction: float = 1.0  # 1 = public mempool
    gas_k: float = 1.8
    hop_decay: float = 0.85
    impact_k: float = 0.009
    liquidity_floor: float = 0.0
    success_rate_weight: float = 0.5


DEFAULT_SCORE_CONFIG = ScoreConfig()


@dataclass
class ScoreResult:
    net_profit_usd: float = 0
    execution_probability: float = 0
    expected_value_usd: float = 0
    final_score: float = 0  # == expected_value_usd
    approved: bool = False
    factors: list = field(default_factory=list)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _finite_or(x: float, fallback: float) -> float:
    return x if math.isfinite(x) else fallback


def _calculate_execution_probability(inp: ScoreInput, cfg: ScoreConfig) -> float:
    profit = inp.net_profit_usd
    gas = inp.gas_cost_usd

    if not math.isfinite(profit) or not math.isfinite(gas) or profit <= 0 or gas < 0:
        return 0.0

    p = 1.0

    # 1. Gas relative to profit
    p *= math.exp(-cfg.gas_k * (gas / profit))

    # 2. Hops (1 hop = no penalty)
    hops = max(1, _finite_or(inp.hops, 1))
    p *= cfg.hop_decay ** (hops - 1)

    # 3. Price impact + slippage
    total_impact_bps = max(0, _finite_or(inp.price_impact_bps, 0) + _finite_or(inp.slippage_bps, 0))
    p *= math.exp(-cfg.impact_k * total_impact_bps)

    # 4. Liquidity
    liq = _clamp01(_finite_or(inp.liquidity_score, 0))
    p *= max(cfg.liquidity_floor, liq)

    # 5. Historical success rate
    if inp.recent_success_rate is not None and math.isfinite(inp.recent_success_rate):
        rate = _clamp01(inp.recent_success_rate)
        p *= 1 - cfg.success_rate_weight + cfg.success_rate_weight * rate

    return _clamp01(p)


def calculate_score(inp: ScoreInput, overrides: dict | None = None) -> ScoreResult:
    """Main scoring function. Returns ScoreResult with EV as final_score."""
    cfg = DEFAULT_SCORE_CONFIG
    if overrides:
        for k, v in overrides.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)

    p = _calculate_execution_probability(inp, cfg)
    profit = inp.net_profit_usd

    if p == 0:
        return ScoreResult(net_profit_usd=_finite_or(profit, 0))

    failure_cost = inp.gas_cost_usd * cfg.failure_gas_fraction
    ev = p * profit - (1 - p) * failure_cost

    approved = (
        profit > 0
        and profit >= cfg.min_net_profit_usd
        and p >= cfg.min_execution_probability
        and ev >= cfg.min_expected_value_usd
    )

    return ScoreResult(
        net_profit_usd=profit,
        execution_probability=round(p, 4),
        expected_value_usd=round(ev, 4),
        final_score=round(ev, 4),
        approved=approved,
    )
