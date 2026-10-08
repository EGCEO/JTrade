"""Prioritization, dynamic sizing, risk checks, tier & network progression.

Implements the strategy specification:

  Net Profit = Gross Profit – (DEX fees + Flash-loan fees + Gas cost
               + Slippage cost + Price Impact cost + Competition haircut)

  Gross Profit = amountOut – amountIn

Opportunities are scored by true net profit after every cost, sorted
highest-first, with thresholds and risk limits that scale automatically
with the current tracked account balance.
"""

from dataclasses import dataclass
from typing import List


# ---------------------------------------------------------------------------
# Net profit calculation
# ---------------------------------------------------------------------------

def calculate_net_profit(
    sell_proceeds: float,
    buy_cost: float,
    cex_fees: float = 0.0,
    dex_fees: float = 0.0,
    estimated_gas: float = 0.0,
    slippage_estimate: float = 0.0,
    transfer_costs: float = 0.0,
    flashloan_fee: float = 0.0,
    price_impact_cost: float = 0.0,
    competition_haircut: float = 0.0,
) -> float:
    """Net Profit = Gross Profit – all costs."""
    gross = sell_proceeds - buy_cost
    total_costs = (
        cex_fees + dex_fees + estimated_gas + slippage_estimate
        + transfer_costs + flashloan_fee
        + price_impact_cost + competition_haircut
    )
    return round(gross - total_costs, 6)


# ---------------------------------------------------------------------------
# Dynamic thresholds based on account size
# ---------------------------------------------------------------------------

@dataclass
class Thresholds:
    min_profit: float
    max_size_percent: float
    max_hops: int
    allow_more_pairs: bool


def get_current_thresholds(account_balance: float, is_aggressive: bool,
                           max_hops_normal: int = 2, max_hops_aggressive: int = 4,
                           min_profit_normal: float = None,
                           min_profit_aggressive: float = None) -> Thresholds:
    # Small accounts ($50-$100) stay under the strictest rules
    if account_balance < 100:
        base_min_profit = 0.75
        max_size_percent = 0.15
    elif account_balance < 500:
        base_min_profit = 1.50
        max_size_percent = 0.20
    else:
        base_min_profit = 3.00
        max_size_percent = 0.25

    # Allow config overrides
    if min_profit_normal is not None:
        base_min_profit = min_profit_normal

    if is_aggressive:
        agg_min = min_profit_aggressive if min_profit_aggressive is not None else round(base_min_profit * 0.4, 4)
        return Thresholds(
            min_profit=agg_min,
            max_size_percent=round(max_size_percent * 1.8, 4),
            max_hops=max_hops_aggressive,
            allow_more_pairs=True,
        )
    return Thresholds(
        min_profit=base_min_profit,
        max_size_percent=max_size_percent,
        max_hops=max_hops_normal,
        allow_more_pairs=False,
    )


# ---------------------------------------------------------------------------
# Risk checks
# ---------------------------------------------------------------------------

def passes_risk_checks(
    net_profit: float,
    trade_size: float,
    account_balance: float,
    is_aggressive: bool,
    daily_loss_so_far: float,
    config_min_profit: float = None,
    config_max_risk_pct: float = None,
    config_daily_limit_pct: float = None,
    max_open_exposure: float = None,
    current_exposure: float = 0.0,
) -> bool:
    """Capital protection: min profit, max risk %, daily loss limit, total exposure."""
    min_profit = config_min_profit if config_min_profit is not None else (0.40 if is_aggressive else 0.75)
    max_risk_pct = config_max_risk_pct if config_max_risk_pct is not None else (0.20 if is_aggressive else 0.12)
    daily_limit_pct = config_daily_limit_pct if config_daily_limit_pct is not None else 0.05

    if net_profit < min_profit:
        return False
    if account_balance > 0 and trade_size > account_balance * max_risk_pct:
        return False
    if account_balance > 0 and daily_loss_so_far + abs(min(0, net_profit)) > account_balance * daily_limit_pct:
        return False
    if max_open_exposure and account_balance > 0 and current_exposure + trade_size > account_balance * max_open_exposure:
        return False
    return True


# ---------------------------------------------------------------------------
# Opportunity scoring & prioritization
# ---------------------------------------------------------------------------

@dataclass
class ScoredOpportunity:
    score: float
    net: float
    opportunity: dict


def prioritize_opportunities(all_opportunities: List[dict], account_balance: float,
                             is_aggressive: bool, max_hops_normal: int = 2,
                             max_hops_aggressive: int = 4) -> List[ScoredOpportunity]:
    t = get_current_thresholds(account_balance, is_aggressive, max_hops_normal, max_hops_aggressive)
    scored = []
    for opp in all_opportunities:
        # Prefer net_profit_usd if present (new format), else compute from costs
        net = opp.get("net_profit_usd") or opp.get("net_profit", 0) or calculate_net_profit(
            opp.get("sell_proceeds", 0), opp.get("buy_cost", 0),
            opp.get("cex_fees", 0), opp.get("dex_fees", 0), opp.get("estimated_gas", 0),
            opp.get("slippage_estimate", 0), opp.get("transfer_costs", 0), opp.get("flashloan_fee", 0),
            opp.get("price_impact_cost", 0), opp.get("competition_haircut", 0),
        )
        hops = opp.get("hops", 1)
        if net >= t.min_profit and hops <= t.max_hops:
            confidence = opp.get("confidence", 0.5)
            score = opp.get("score") or (net * 1000 + (confidence * 10) - (hops * 5))
            scored.append(ScoredOpportunity(score=round(score, 4), net=round(net, 6), opportunity=opp))
    scored.sort(key=lambda x: x.score, reverse=True)
    return scored


# ---------------------------------------------------------------------------
# Account levels (gamified progression)
# ---------------------------------------------------------------------------

LEVELS = [
    {"level": 1, "min": 0, "max": 100, "name": "Starter", "desc": "Core major pairs only, strict risk"},
    {"level": 2, "min": 100, "max": 500, "name": "Trader", "desc": "More pairs unlocked, slightly higher size"},
    {"level": 3, "min": 500, "max": 2000, "name": "Pro", "desc": "Triangular paths and more DEX venues"},
    {"level": 4, "min": 2000, "max": float("inf"), "name": "Elite", "desc": "Full pair universe, highest size limits"},
]


def get_account_level(balance: float) -> dict:
    for lv in LEVELS:
        if lv["min"] <= balance < lv["max"]:
            return lv
    return LEVELS[-1]


def get_next_level(balance: float) -> dict | None:
    current = get_account_level(balance)
    for lv in LEVELS:
        if lv["level"] == current["level"] + 1:
            return lv
    return None


def level_progress_pct(balance: float) -> float:
    lv = get_account_level(balance)
    if lv["max"] == float("inf"):
        return 100.0
    span = lv["max"] - lv["min"]
    if span <= 0:
        return 100.0
    return round(min(100.0, max(0.0, (balance - lv["min"]) / span * 100)), 2)


# ---------------------------------------------------------------------------
# Network progression (strict: Base -> efficient L2s -> Ethereum last)
# Networks unlock only after real compounded profits reach tier levels.
# ---------------------------------------------------------------------------

NETWORK_TIERS = [
    {"tier": 0, "networks": ["base"], "min_balance": 0, "label": "Base only"},
    {"tier": 1, "networks": ["base", "arbitrum"], "min_balance": 250, "label": "Base + Arbitrum"},
    {"tier": 2, "networks": ["base", "arbitrum", "optimism"], "min_balance": 750, "label": "+ Optimism"},
    {"tier": 3, "networks": ["base", "arbitrum", "optimism", "polygon"], "min_balance": 1500, "label": "+ Polygon"},
    {"tier": 4, "networks": ["base", "arbitrum", "optimism", "polygon", "ethereum"], "min_balance": 3000, "label": "+ Ethereum (final)"},
]


def get_network_tier(balance: float) -> dict:
    current = NETWORK_TIERS[0]
    for nt in NETWORK_TIERS:
        if balance >= nt["min_balance"]:
            current = nt
    return current


def get_next_network_tier(balance: float) -> dict | None:
    current = get_network_tier(balance)
    for nt in NETWORK_TIERS:
        if nt["tier"] == current["tier"] + 1:
            return nt
    return None


def is_network_unlocked(network: str, balance: float) -> bool:
    return network.lower() in [n.lower() for n in get_network_tier(balance)["networks"]]


# ---------------------------------------------------------------------------
# Scoring module — Python port of bot/src/math/scoring.ts
# Computes execution probability, expected value, and final approval.
# ---------------------------------------------------------------------------

import math as _math

DEFAULT_SCORE_CONFIG = {
    "min_net_profit_usd": 0.75,
    "min_expected_value_usd": 0.5,
    "min_execution_probability": 0.35,
    "failure_gas_fraction": 1.0,
    "gas_k": 1.8,
    "hop_decay": 0.85,
    "impact_k": 0.009,
    "liquidity_floor": 0.0,
    "success_rate_weight": 0.5,
}


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _finite_or(x: float, fallback: float) -> float:
    return x if _math.isfinite(x) else fallback


def calculate_execution_probability(
    net_profit_usd: float,
    gas_cost_usd: float,
    hops: int,
    price_impact_bps: float,
    slippage_bps: float,
    liquidity_score: float,
    recent_success_rate: float = None,
    cfg: dict = None,
) -> float:
    cfg = cfg or DEFAULT_SCORE_CONFIG
    profit = net_profit_usd
    gas = gas_cost_usd

    if not _math.isfinite(profit) or not _math.isfinite(gas) or profit <= 0 or gas < 0:
        return 0.0

    p = 1.0

    # 1. Gas relative to profit
    p *= _math.exp(-cfg["gas_k"] * (gas / profit))

    # 2. Hops (1 hop = no penalty)
    h = max(1, _finite_or(hops, 1))
    p *= cfg["hop_decay"] ** (h - 1)

    # 3. Price impact + slippage
    total_impact_bps = max(0, _finite_or(price_impact_bps, 0) + _finite_or(slippage_bps, 0))
    p *= _math.exp(-cfg["impact_k"] * total_impact_bps)

    # 4. Liquidity
    liq = _clamp01(_finite_or(liquidity_score, 0))
    p *= max(cfg["liquidity_floor"], liq)

    # 5. Historical success rate
    if recent_success_rate is not None and _math.isfinite(recent_success_rate):
        rate = _clamp01(recent_success_rate)
        p *= 1 - cfg["success_rate_weight"] + cfg["success_rate_weight"] * rate

    return _clamp01(p)


def calculate_score(
    net_profit_usd: float,
    gas_cost_usd: float,
    hops: int,
    price_impact_bps: float,
    slippage_bps: float,
    liquidity_score: float,
    recent_success_rate: float = None,
    overrides: dict = None,
) -> dict:
    """Returns {net_profit_usd, execution_probability, expected_value_usd, final_score, approved}."""
    cfg = dict(DEFAULT_SCORE_CONFIG)
    if overrides:
        cfg.update(overrides)

    p = calculate_execution_probability(
        net_profit_usd, gas_cost_usd, hops, price_impact_bps, slippage_bps,
        liquidity_score, recent_success_rate, cfg,
    )

    if p == 0:
        return {
            "net_profit_usd": _finite_or(net_profit_usd, 0),
            "execution_probability": 0.0,
            "expected_value_usd": 0.0,
            "final_score": 0.0,
            "approved": False,
        }

    profit = net_profit_usd
    failure_cost = gas_cost_usd * cfg["failure_gas_fraction"]
    ev = p * profit - (1 - p) * failure_cost

    approved = (
        profit > 0
        and profit >= cfg["min_net_profit_usd"]
        and p >= cfg["min_execution_probability"]
        and ev >= cfg["min_expected_value_usd"]
    )

    return {
        "net_profit_usd": profit,
        "execution_probability": round(p, 6),
        "expected_value_usd": round(ev, 6),
        "final_score": round(ev, 6),
        "approved": approved,
    }
