"""Prioritization, risk-check, and tier-unlock logic for the Arbitrage Command Center."""

TIERS = [
    {
        "level": 0,
        "name": "Tier 0 — Starter",
        "min_balance": 0,
        "networks": ["base"],
        "pairs": "Core major pairs only",
        "max_size_percent": 0.15,
        "description": "Base network only, strict risk",
    },
    {
        "level": 1,
        "name": "Tier 1 — Growing",
        "min_balance": 100,
        "networks": ["base", "arbitrum"],
        "pairs": "More pairs unlocked, slightly higher size",
        "max_size_percent": 0.20,
        "description": "More pairs, slightly higher size",
    },
    {
        "level": 2,
        "name": "Tier 2 — Advanced",
        "min_balance": 500,
        "networks": ["base", "arbitrum", "optimism", "polygon"],
        "pairs": "Triangular paths and more DEX venues",
        "max_size_percent": 0.25,
        "description": "Triangular paths, more DEX venues",
    },
    {
        "level": 3,
        "name": "Tier 3 — Full Access",
        "min_balance": 2000,
        "networks": ["base", "arbitrum", "optimism", "polygon", "ethereum"],
        "pairs": "Full pair universe, highest size limits",
        "max_size_percent": 0.30,
        "description": "Full pair universe, Ethereum unlocked",
    },
]


def get_tier(balance: float) -> dict:
    """Return the tier dict for a given balance."""
    current = TIERS[0]
    for tier in TIERS:
        if balance >= tier["min_balance"]:
            current = tier
    return current


def get_next_tier(balance: float) -> dict | None:
    """Return the next tier to unlock, or None if at max."""
    current = get_tier(balance)
    for tier in TIERS:
        if tier["level"] == current["level"] + 1:
            return tier
    return None


def get_unlocked_networks(balance: float) -> list[str]:
    return get_tier(balance)["networks"]


def get_current_thresholds(account_balance: float, is_aggressive: bool):
    """Return (min_profit, max_size_percent, max_hops, allow_more_pairs)."""
    if account_balance < 100:
        base_min_profit = 0.75
        max_size_pct = 0.15
    elif account_balance < 500:
        base_min_profit = 1.50
        max_size_pct = 0.20
    else:
        base_min_profit = 3.00
        max_size_pct = 0.25

    if is_aggressive:
        min_profit = base_min_profit * 0.4
        max_size_pct = max_size_pct * 1.8
        max_hops = 4
        allow_more_pairs = True
    else:
        min_profit = base_min_profit
        max_hops = 2
        allow_more_pairs = False

    return min_profit, max_size_pct, max_hops, allow_more_pairs


def calculate_priority_score(net_profit: float, confidence: float, hops: int) -> float:
    """Score = net * 1000 + confidence * 10 - hops * 5."""
    return net_profit * 1000 + (confidence * 10) - (hops * 5)


def passes_risk_checks(net_profit, trade_size, account_balance, is_aggressive,
                      daily_loss_so_far, config_values: dict | None = None):
    """Check whether an opportunity passes all risk gates."""
    cv = config_values or {}
    min_profit_override = cv.get("min_profit_override")
    max_risk_override = cv.get("max_risk_override")
    daily_limit_pct = cv.get("daily_loss_limit", 0.05)

    if min_profit_override is not None:
        min_profit = min_profit_override
    else:
        min_profit = 0.40 if is_aggressive else 0.75

    if max_risk_override is not None:
        max_risk_pct = max_risk_override
    else:
        max_risk_pct = 0.20 if is_aggressive else 0.12

    if net_profit < min_profit:
        return False, f"Net profit ${net_profit:.2f} below minimum ${min_profit:.2f}"
    if trade_size > account_balance * max_risk_pct:
        return False, f"Trade size ${trade_size:.2f} exceeds max risk {max_risk_pct*100:.0f}% of balance"
    if daily_loss_so_far + abs(min(0, net_profit)) > account_balance * daily_limit_pct:
        return False, "Daily loss limit would be exceeded"
    return True, "OK"
