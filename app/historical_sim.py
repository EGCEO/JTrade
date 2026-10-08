"""Historical data paper-mode simulator.

Fetches real historical OHLCV data from CoinGecko's public API and replays it
through the 4-bot pipeline (Scanner → Quant → Guardian → Execution) in paper
mode, populating the dashboard with realistic opportunities, trades, logs,
and heartbeats — no external bots required.

Includes a file-based market-data cache so repeated sim runs within the TTL
window don't re-hit CoinGecko's rate-limited API.

Runs as a background thread; controlled via /api/sim/* endpoints.
"""
import hashlib
import json
import math
import os
import random
import threading
import time
import urllib.request
from datetime import datetime, timedelta

from app.database import SessionLocal
from app.models import (
    Config, Opportunity, TradeLog, BotHeartbeat, AccountSnapshot,
    TierProgress, Log, Notification, CapitalTransaction,
    OppStatus, OppType, BotName, BotState, TradeMode, StrategyStyle,
    ACTIVE_BOTS,
)
from app.prioritization import (
    calculate_net_profit, get_current_thresholds, passes_risk_checks,
    calculate_score, get_network_tier, is_network_unlocked,
)
from app.learning import get_success_rate_for_opp, analyze_trades, auto_tune_thresholds

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SIM_PAIRS = [
    ("bitcoin", "BTC/USDT"),
    ("ethereum", "ETH/USDT"),
    ("binancecoin", "BNB/USDT"),
    ("solana", "SOL/USDT"),
    ("ripple", "XRP/USDT"),
]

CG_DAYS = 30            # 30 days of hourly data from CoinGecko (~720 candles)
REPLAY_DELAY = 1.2      # seconds between candles (accelerated replay)
CG_FETCH_DELAY = 6      # seconds between CoinGecko API calls (free-tier rate limit)

# --- Market data cache ---
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "market_cache")
CACHE_TTL = 7200        # 2 hours — CoinGecko hourly data doesn't change often

# State
_sim_state = {
    "running": False,
    "thread": None,
    "progress": 0,
    "total_candles": 0,
    "current_day": "",
    "pairs_loaded": 0,
    "opps_generated": 0,
    "trades_executed": 0,
    "started_at": None,
    "error": "",
}


def get_sim_status() -> dict:
    return {k: v for k, v in _sim_state.items() if k != "thread"}


# ---------------------------------------------------------------------------
# Fetch historical data from CoinGecko public API
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Market data cache
# ---------------------------------------------------------------------------

def _cache_key(coin_id: str, days: int) -> str:
    return hashlib.md5(f"{coin_id}_{days}".encode()).hexdigest()


def _cache_path(key: str) -> str:
    return os.path.join(CACHE_DIR, f"{key}.json")


def _cache_get(key: str):
    """Return cached raw CoinGecko response if fresh, else None."""
    path = _cache_path(key)
    if not os.path.exists(path):
        return None
    if time.time() - os.path.getmtime(path) > CACHE_TTL:
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return None


def _cache_set(key: str, data):
    """Persist raw CoinGecko response to disk."""
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_cache_path(key), "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"[historical_sim] Cache write failed: {e}")


def fetch_klines(coin_id: str, days: int = CG_DAYS):
    """Fetch historical market data from CoinGecko. Returns list of (openTime, open, high, low, close, volume).

    CoinGecko's market_chart endpoint returns hourly prices and volumes.
    We synthesize OHLC candles from consecutive price points.
    Uses a file-based cache to avoid rate limits on repeated runs.
    Includes retry logic for rate limiting (HTTP 429).
    """
    key = _cache_key(coin_id, days)
    cached = _cache_get(key)
    if cached is not None:
        print(f"[historical_sim] Cache hit for {coin_id} ({days}d)")
        raw = cached
    else:
        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart?vs_currency=usd&days={days}&interval=hourly"
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": "ArbitrageGods/1.0",
                    "Accept": "application/json",
                })
                with urllib.request.urlopen(req, timeout=20) as resp:
                    raw = json.loads(resp.read().decode())
                break
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 2:
                    wait = (attempt + 1) * 10  # 10s, then 20s
                    print(f"[historical_sim] Rate limited on {coin_id}, retrying in {wait}s")
                    time.sleep(wait)
                    continue
                raise
        else:
            return []
        _cache_set(key, raw)
        print(f"[historical_sim] Cache miss — fetched & cached {coin_id} ({days}d)")

    prices = raw.get("prices", [])        # [[timestamp_ms, price], ...]
    volumes = raw.get("total_volumes", [])  # [[timestamp_ms, volume], ...]

    candles = []
    for i in range(1, len(prices)):
        ts = prices[i][0]
        close = prices[i][1]
        open_p = prices[i - 1][1]
        vol = volumes[i][1] if i < len(volumes) else 0
        # Synthesize high/low from the open-close range with a small wiggle
        hi = max(open_p, close)
        lo = min(open_p, close)
        wiggle = (hi - lo) / hi * 0.3 if hi > 0 else 0.001
        hi *= (1 + wiggle * random.uniform(0.2, 0.8))
        lo *= (1 - wiggle * random.uniform(0.2, 0.8))
        candles.append((ts, open_p, hi, lo, close, vol))
    return candles


def fetch_all_pairs():
    """Fetch market data for all sim pairs. Returns {pair_label: [candles]}."""
    data = {}
    for coin_id, label in SIM_PAIRS:
        try:
            candles = fetch_klines(coin_id)
            if candles:
                data[label] = candles
            time.sleep(CG_FETCH_DELAY)
        except Exception as e:
            print(f"[historical_sim] Failed to fetch {coin_id}: {e}")
            time.sleep(CG_FETCH_DELAY)
    return data


# ---------------------------------------------------------------------------
# Simulation helpers
# ---------------------------------------------------------------------------

def _log(db, bot, level, message, meta=None):
    db.add(Log(bot=bot, level=level, message=message,
              meta=json.dumps(meta) if meta else "{}"))


def _heartbeat(db, bot_enum, state, action, error=""):
    b = db.query(BotHeartbeat).filter(BotHeartbeat.bot == bot_enum).first()
    if not b:
        b = BotHeartbeat(bot=bot_enum, paused=False)
        db.add(b)
    b.state = state
    b.last_heartbeat = datetime.utcnow()
    b.last_action = action
    b.last_error = error
    b.paused = False


def _all_heartbeats(db, state=BotState.running, action="Historical sim active"):
    for bot in ACTIVE_BOTS:
        _heartbeat(db, bot, state, action)


def _pick_network(balance):
    """Pick a network that's unlocked for the current balance."""
    tier = get_network_tier(balance)
    networks = tier["networks"]
    return random.choice(networks)


def _simulate_opportunity(db, pair_label, candle, cfg, balance):
    """Generate a realistic arbitrage opportunity from a historical candle.

    Uses the candle's volatility (high-low range) to estimate the cross-DEX
    spread, then computes net profit after all costs.
    """
    open_time, o, h, l, c, vol = candle

    # Volatility as fraction of close price
    volatility = (h - l) / c if c > 0 else 0

    # Only generate opportunities when there's meaningful price movement
    if volatility < 0.001:  # < 0.1% range — too tight
        return None

    # Cross-DEX spread: a fraction of the volatility.
    # Real arbitrage spreads are 0.5-3% of the volatility range; we use a
    # generous multiplier so opportunities are frequent enough for simulation.
    spread_pct = volatility * random.uniform(0.80, 2.50)

    # Trade size: within risk limits, scales with balance
    max_risk = cfg.max_risk_per_trade_aggressive if cfg.is_aggressive else cfg.max_risk_per_trade
    max_size = balance * max_risk
    # Flashloan style allows larger sizes (borrowed capital)
    is_flashloan = random.random() < 0.65
    if is_flashloan:
        trade_size = min(cfg.max_flashloan_size, max_size * random.uniform(5, 12))
    else:
        trade_size = max_size * random.uniform(0.4, 1.0)
    trade_size = max(trade_size, 20.0)  # minimum viable size

    # Gross profit from spread
    gross_profit = spread_pct * trade_size

    # Pick network (needed for gas cost estimation)
    network = _pick_network(balance)

    # Costs
    dex_fees = trade_size * cfg.dex_fee_pct * 2  # buy + sell on DEX
    # Gas cost varies by network — L2s (Base, Arbitrum, etc.) are much cheaper than Ethereum
    if network == "ethereum":
        gas_cost = cfg.gas_estimate_usd * random.uniform(0.8, 1.5)
    else:
        gas_cost = random.uniform(0.03, 0.25)  # L2 gas: $0.03-0.25
    slippage = trade_size * cfg.slippage_pct
    price_impact = trade_size * cfg.price_impact_pct
    competition = trade_size * cfg.competition_haircut_pct
    flashloan_fee = trade_size * 0.0009 if is_flashloan else 0.0  # Aave V3: 0.09%

    net_profit = calculate_net_profit(
        sell_proceeds=trade_size + gross_profit,
        buy_cost=trade_size,
        dex_fees=dex_fees,
        estimated_gas=gas_cost,
        slippage_estimate=slippage,
        flashloan_fee=flashloan_fee,
        price_impact_cost=price_impact,
        competition_haircut=competition,
    )

    if net_profit <= 0:
        return None

    # Determine hops and type
    hops = random.choices([1, 2, 3], weights=[50, 35, 15])[0]
    if is_flashloan:
        opp_type = random.choice([OppType.flashloan, OppType.triangular, OppType.multihop])
    else:
        opp_type = OppType.crossdex
    style = StrategyStyle.flashloan if is_flashloan else StrategyStyle.inventory

    # Score using the scoring engine
    ts = trade_size or net_profit or 1
    price_impact_bps = (price_impact / ts * 10000)
    # Flashloan atomic execution has lower effective slippage
    slippage_bps = (slippage / ts * 10000) * (0.3 if is_flashloan else 1.0)
    # Liquidity from volume — use log scale for broader range
    if vol > 0:
        liquidity = min(1.0, max(0.5, 0.5 + 0.5 * (vol / 5_000_000)))
    else:
        liquidity = 0.7

    score_overrides = {
        "min_net_profit_usd": cfg.score_min_net_profit_usd,
        "min_expected_value_usd": cfg.score_min_expected_value_usd,
        "min_execution_probability": cfg.score_min_execution_probability,
        "failure_gas_fraction": cfg.score_failure_gas_fraction,
        "gas_k": cfg.score_gas_k,
        "hop_decay": cfg.score_hop_decay,
        "impact_k": cfg.score_impact_k,
        "liquidity_floor": cfg.score_liquidity_floor,
        "success_rate_weight": cfg.score_success_rate_weight,
    }
    # --- Learning engine: apply learned success rate from historical patterns ---
    learned_rate = get_success_rate_for_opp(
        db, pair_label, network,
        "flashloan" if is_flashloan else "inventory",
        trade_size, executed_at=datetime.utcnow(),
    )

    score_result = calculate_score(
        net_profit_usd=net_profit,
        gas_cost_usd=gas_cost,
        hops=hops,
        price_impact_bps=price_impact_bps,
        slippage_bps=slippage_bps,
        liquidity_score=liquidity,
        recent_success_rate=learned_rate,
        overrides=score_overrides,
    )

    return {
        "pair": pair_label,
        "network": network,
        "style": style,
        "opp_type": opp_type,
        "gross_profit": gross_profit,
        "net_profit": net_profit,
        "trade_size": trade_size,
        "dex_fees": dex_fees,
        "estimated_gas": gas_cost,
        "slippage_estimate": slippage,
        "flashloan_fee": flashloan_fee,
        "price_impact_cost": price_impact,
        "competition_haircut": competition,
        "hops": hops,
        "confidence": liquidity,
        "score": score_result["final_score"],
        "exec_prob": score_result["execution_probability"],
        "ev": score_result["expected_value_usd"],
        "approved": score_result["approved"],
        "open_time": open_time,
    }


def _execute_trade(db, opp_data, cfg):
    """Simulate execution of an approved opportunity as a paper trade."""
    # Win/loss based on execution probability
    p = opp_data["exec_prob"]
    wins = random.random() < p

    if wins:
        # Win: actual profit close to expected, with small variance
        actual_profit = opp_data["net_profit"] * random.uniform(0.85, 1.05)
        status = "success"
    else:
        # Loss: lose gas + some slippage
        actual_profit = -(opp_data["estimated_gas"] + opp_data["slippage_estimate"] * random.uniform(0.5, 1.0))
        status = "failed"

    actual_profit = round(actual_profit, 6)

    # Create the opportunity record
    opp = Opportunity(
        ext_id=f"sim_{int(time.time()*1000)}_{random.randint(1000,9999)}",
        pair=opp_data["pair"],
        network=opp_data["network"],
        style=opp_data["style"],
        opp_type=opp_data["opp_type"],
        path="[]",
        amount_in=str(opp_data["trade_size"]),
        expected_amount_out=str(opp_data["trade_size"] + opp_data["net_profit"]),
        net_profit_wei="0",
        net_profit_usd=opp_data["net_profit"],
        buy_cost=opp_data["trade_size"],
        sell_proceeds=opp_data["trade_size"] + opp_data["gross_profit"],
        dex_fees=opp_data["dex_fees"],
        estimated_gas=opp_data["estimated_gas"],
        slippage_estimate=opp_data["slippage_estimate"],
        flashloan_fee=opp_data["flashloan_fee"],
        price_impact_cost=opp_data["price_impact_cost"],
        competition_haircut=opp_data["competition_haircut"],
        net_profit=opp_data["net_profit"],
        hops=opp_data["hops"],
        confidence=opp_data["confidence"],
        score=opp_data["score"],
        trade_size=opp_data["trade_size"],
        source="historical_sim",
        status=OppStatus.executed if wins else OppStatus.failed,
    )
    db.add(opp)
    db.flush()

    # Create trade log
    gas_cost_usd = opp_data["estimated_gas"]
    slippage_cost = round(max(0, opp_data["net_profit"] - actual_profit), 6) if wins else round(opp_data["slippage_estimate"], 6)

    trade = TradeLog(
        opportunity_id=opp.id,
        ext_opportunity_id=opp.ext_id,
        mode=TradeMode.paper,
        style=opp_data["style"],
        network=opp_data["network"],
        pair=opp_data["pair"],
        expected_profit=opp_data["net_profit"],
        actual_profit=actual_profit,
        net_profit_usd=actual_profit,
        trade_size=opp_data["trade_size"],
        status=status,
        detail=f"Historical sim: {opp_data['pair']} on {opp_data['network']}",
        gas_cost_usd=gas_cost_usd,
        slippage_cost=slippage_cost,
        notes=f"Exec prob: {opp_data['exec_prob']:.2%}, EV: ${opp_data['ev']:.4f}",
    )
    db.add(trade)

    # Update paper balance
    cfg.current_balance_paper += actual_profit
    bal_after = cfg.current_balance_paper

    # Capital transaction
    db.add(CapitalTransaction(
        type="profit" if actual_profit >= 0 else "loss",
        mode=TradeMode.paper,
        amount=actual_profit,
        balance_after=bal_after,
        note=f"Historical sim trade: {opp_data['pair']}",
    ))

    # Update tier progress
    tp = db.query(TierProgress).first()
    if tp:
        tp.highest_balance = max(tp.highest_balance, bal_after)

    # Notification
    db.add(Notification(
        type="trade" if wins else "error",
        title=f"{'✅' if wins else '❌'} Paper Trade {'Filled' if wins else 'Failed'}",
        message=f"{opp_data['pair']} on {opp_data['network']} — P/L: ${actual_profit:.2f} (paper)",
    ))

    return actual_profit, wins


def _simulate_capital_flow(db, cfg, candle_idx):
    """Simulate a deposit or withdrawal every ~48 candles (2 'days').

    Models realistic capital flows: occasional deposits when balance is low,
    occasional withdrawals when profits accumulate. These are paper-mode
    capital transactions that affect the compounding balance.
    """
    if candle_idx == 0 or candle_idx % 48 != 0:
        return

    balance = cfg.current_balance_paper
    profit = balance - cfg.starting_capital

    # 60% chance of a small deposit, 25% chance of a withdrawal, 15% nothing
    roll = random.random()
    if roll < 0.60:
        # Deposit: small amount relative to current balance
        amount = round(random.uniform(20, 100), 2)
        cfg.current_balance_paper += amount
        bal_after = cfg.current_balance_paper
        db.add(CapitalTransaction(
            type="deposit", mode=TradeMode.paper, amount=amount,
            balance_after=bal_after, note=f"Historical sim: simulated deposit at candle {candle_idx}",
        ))
        _log(db, "system", "info",
             f"📥 Simulated deposit: +${amount:.2f} (balance ${bal_after:.2f})")
    elif roll < 0.85 and profit > 50:
        # Withdrawal: take some profit off the table
        amount = round(min(profit * random.uniform(0.15, 0.35), 200), 2)
        if amount > 0:
            cfg.current_balance_paper -= amount
            bal_after = cfg.current_balance_paper
            db.add(CapitalTransaction(
                type="withdraw", mode=TradeMode.paper, amount=-amount,
                balance_after=bal_after, note=f"Historical sim: simulated withdrawal at candle {candle_idx}",
            ))
            _log(db, "system", "info",
                 f"📤 Simulated withdrawal: -${amount:.2f} (balance ${bal_after:.2f})")


# ---------------------------------------------------------------------------
# Main simulation loop
# ---------------------------------------------------------------------------

def _sim_loop():
    """Background thread: fetch historical data and replay it through the bot pipeline."""
    db = SessionLocal()
    try:
        cfg = db.query(Config).first()
        if not cfg:
            _sim_state["error"] = "No config found"
            _sim_state["running"] = False
            return

        # Ensure paper mode
        cfg.is_real_execution = False
        cfg.is_running = True
        db.commit()

        # Clear stale pending/approved opportunities so they don't inflate
        # current exposure and block the Guardian risk check during replay.
        stale = db.query(Opportunity).filter(
            Opportunity.status.in_([OppStatus.pending, OppStatus.approved])
        ).all()
        for o in stale:
            o.status = OppStatus.skipped
        if stale:
            db.commit()
            _log(db, "guardian", "info",
                 f"Cleared {len(stale)} stale pending/approved opportunities before replay")

        # Set all bots to running
        _all_heartbeats(db, BotState.running, "Historical sim starting...")
        _log(db, "system", "info", "Historical data paper mode starting — fetching real market data from CoinGecko")
        db.commit()

        # Fetch historical data
        _sim_state["error"] = ""
        try:
            _log(db, "scanner", "info", f"Fetching {CG_DAYS} days of hourly market data from CoinGecko...")
            db.commit()
            all_data = fetch_all_pairs()
            _sim_state["pairs_loaded"] = len(all_data)
            if not all_data:
                _sim_state["error"] = "Failed to fetch any historical data from CoinGecko"
                _sim_state["running"] = False
                _log(db, "system", "error", "Failed to fetch historical data — no pairs loaded")
                db.commit()
                return
            candle_count = min(len(candles) for candles in all_data.values())
            _sim_state["total_candles"] = candle_count
            pair_labels = list(all_data.keys())
            _log(db, "scanner", "info", f"Loaded {len(all_data)} pairs × {candle_count} hourly candles ({CG_DAYS} days)")
            db.commit()
        except Exception as e:
            _sim_state["error"] = f"Fetch error: {e}"
            _sim_state["running"] = False
            _log(db, "system", "error", f"Failed to fetch historical data: {e}")
            db.commit()
            return

        _log(db, "system", "info", f"Replaying {candle_count} candles across {len(pair_labels)} pairs at {REPLAY_DELAY}s intervals")
        db.commit()

        for i in range(candle_count):
            if not _sim_state["running"]:
                _log(db, "system", "info", "Historical sim stopped by user")
                db.commit()
                break

            _sim_state["progress"] = i + 1

            # Refresh config to pick up any user changes (e.g. stop, toggle aggressive)
            db.expire_all()
            cfg = db.query(Config).first()
            if not cfg.is_running:
                _log(db, "system", "info", "System stopped — historical sim halting")
                _all_heartbeats(db, BotState.paused, "Sim stopped")
                db.commit()
                break

            balance = cfg.current_balance_paper
            t = get_current_thresholds(
                balance, cfg.is_aggressive,
                cfg.max_hops_normal, cfg.max_hops_aggressive,
                cfg.min_profit_normal, cfg.min_profit_aggressive,
            )

            # Determine the "day" for progress display
            first_candle = list(all_data.values())[0][i]
            candle_dt = datetime.utcfromtimestamp(first_candle[0] / 1000)
            _sim_state["current_day"] = candle_dt.strftime("%Y-%m-%d %H:%M UTC")

            # Scanner: scan a subset of pairs this candle
            scan_count = random.randint(2, min(5, len(pair_labels)))
            scanned_pairs = random.sample(pair_labels, scan_count)

            # Heartbeats
            _all_heartbeats(db, BotState.running, f"Scanning candle {i+1}/{candle_count} — {candle_dt.strftime('%b %d, %H:%M')}")
            db.commit()

            opps_this_candle = 0
            trades_this_candle = 0

            for pair_label in scanned_pairs:
                candle = all_data[pair_label][i]

                # --- Scanner: detect opportunity ---
                opp = _simulate_opportunity(db, pair_label, candle, cfg, balance)
                if opp is None:
                    continue

                # Check network unlock
                if not is_network_unlocked(opp["network"], balance):
                    continue

                # --- Quant: score and threshold check ---
                if opp["net_profit"] < t.min_profit:
                    continue
                if opp["hops"] > t.max_hops:
                    continue
                if not opp["approved"]:
                    # Log skipped opp
                    db.add(Opportunity(
                        ext_id=f"sim_skip_{int(time.time()*1000)}_{random.randint(1000,9999)}",
                        pair=opp["pair"], network=opp["network"],
                        style=opp["style"], opp_type=opp["opp_type"],
                        net_profit_usd=opp["net_profit"], net_profit=opp["net_profit"],
                        hops=opp["hops"], confidence=opp["confidence"],
                        score=opp["score"], trade_size=opp["trade_size"],
                        source="historical_sim", status=OppStatus.skipped,
                    ))
                    opps_this_candle += 1
                    continue

                # --- Guardian: risk check ---
                # Compute daily loss so far
                today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                today_trades = db.query(TradeLog).filter(
                    TradeLog.mode == TradeMode.paper, TradeLog.executed_at >= today_start
                ).all()
                daily_pnl = sum(tr.actual_profit for tr in today_trades)
                daily_loss_so_far = abs(min(0, daily_pnl))

                # Current exposure (pending/approved opps)
                open_opps = db.query(Opportunity).filter(
                    Opportunity.status.in_([OppStatus.pending, OppStatus.approved])
                ).all()
                current_exposure = sum(o.trade_size for o in open_opps)

                # For flashloan trades, only gas is at risk (not the borrowed amount)
                risk_size = opp["estimated_gas"] if opp["style"] == StrategyStyle.flashloan else opp["trade_size"]
                risk_ok = passes_risk_checks(
                    net_profit=opp["net_profit"],
                    trade_size=risk_size,
                    account_balance=balance,
                    is_aggressive=cfg.is_aggressive,
                    daily_loss_so_far=daily_loss_so_far,
                    config_min_profit=t.min_profit,
                    config_max_risk_pct=cfg.max_risk_per_trade_aggressive if cfg.is_aggressive else cfg.max_risk_per_trade,
                    config_daily_limit_pct=cfg.daily_loss_limit,
                    max_open_exposure=cfg.max_open_exposure,
                    current_exposure=current_exposure,
                )

                if not risk_ok:
                    db.add(Opportunity(
                        ext_id=f"sim_risk_{int(time.time()*1000)}_{random.randint(1000,9999)}",
                        pair=opp["pair"], network=opp["network"],
                        style=opp["style"], opp_type=opp["opp_type"],
                        net_profit_usd=opp["net_profit"], net_profit=opp["net_profit"],
                        hops=opp["hops"], confidence=opp["confidence"],
                        score=opp["score"], trade_size=opp["trade_size"],
                        source="historical_sim", status=OppStatus.skipped,
                    ))
                    opps_this_candle += 1
                    continue

                # --- Execution: simulate paper trade ---
                # Create approved opportunity
                opp_record = Opportunity(
                    ext_id=f"sim_exec_{int(time.time()*1000)}_{random.randint(1000,9999)}",
                    pair=opp["pair"], network=opp["network"],
                    style=opp["style"], opp_type=opp["opp_type"],
                    net_profit_usd=opp["net_profit"], net_profit=opp["net_profit"],
                    buy_cost=opp["trade_size"],
                    sell_proceeds=opp["trade_size"] + opp["gross_profit"],
                    dex_fees=opp["dex_fees"], estimated_gas=opp["estimated_gas"],
                    slippage_estimate=opp["slippage_estimate"],
                    flashloan_fee=opp["flashloan_fee"],
                    price_impact_cost=opp["price_impact_cost"],
                    competition_haircut=opp["competition_haircut"],
                    hops=opp["hops"], confidence=opp["confidence"],
                    score=opp["score"], trade_size=opp["trade_size"],
                    source="historical_sim", status=OppStatus.approved,
                )
                db.add(opp_record)
                db.flush()
                opp_record.status = OppStatus.executed if random.random() < opp["exec_prob"] else OppStatus.failed
                db.commit()

                actual_profit, wins = _execute_trade(db, opp, cfg)
                db.commit()

                opps_this_candle += 1
                trades_this_candle += 1
                _sim_state["trades_executed"] += 1

                # Log the trade
                _log(db, "execution", "info" if wins else "warning",
                     f"{'✅' if wins else '❌'} Paper trade: {opp['pair']} {opp['network']} — P/L ${actual_profit:.4f}",
                     {"pair": opp["pair"], "profit": actual_profit, "prob": opp["exec_prob"]})

                # Refresh balance after trade
                balance = cfg.current_balance_paper

            _sim_state["opps_generated"] += opps_this_candle

            # Simulate deposit/withdrawal capital flows every ~48 candles
            _simulate_capital_flow(db, cfg, i)

            # --- Learning engine: re-analyze patterns every ~48 candles ---
            # This lets the system learn from recent trades and feed improved
            # success rates back into the scoring pipeline in real time.
            if i > 0 and i % 48 == 0:
                try:
                    result = analyze_trades(db)
                    if result.get("ok"):
                        _log(db, "quant", "info",
                             f"🧠 Learning engine: {result['patterns_identified']} patterns from {result['trades_analyzed']} trades")
                        # Auto-tune Quant thresholds based on learned patterns
                        db.expire_all()
                        cfg = db.query(Config).first()
                        tune_result = auto_tune_thresholds(db, cfg)
                        if tune_result.get("ok") and tune_result.get("changes"):
                            for ch in tune_result["changes"]:
                                _log(db, "quant", "info",
                                     f"🔧 Auto-tuned {ch['param']}: {ch['old']} → {ch['new']} ({ch['reason']})")
                except Exception as e:
                    print(f"[historical_sim] Learning analysis failed: {e}")

            # Periodic log
            if i % 24 == 0:  # every ~24 candles (1 "day")
                _log(db, "scanner", "info",
                     f"Day {i//24 + 1}/{candle_count//24}: scanned {scan_count} pairs, {opps_this_candle} opps, {trades_this_candle} trades. Balance: ${balance:.2f}")

            # Account snapshot every 24 candles
            if i % 24 == 0 or i == candle_count - 1:
                db.add(AccountSnapshot(
                    simulated_at=candle_dt,
                    balance_paper=cfg.current_balance_paper,
                    balance_real=cfg.current_balance_real,
                    mode=TradeMode.paper,
                    tier=1,
                ))

            db.commit()
            time.sleep(REPLAY_DELAY)

        # Sim finished or stopped
        _all_heartbeats(db, BotState.paused if not _sim_state["running"] else BotState.running,
                       "Historical sim complete" if _sim_state["running"] else "Sim stopped")
        if _sim_state["running"]:
            _sim_state["running"] = False
            _log(db, "system", "info",
                 f"Historical replay complete: {_sim_state['trades_executed']} trades, balance ${cfg.current_balance_paper:.2f}")
        db.commit()

    except Exception as e:
        _sim_state["error"] = str(e)
        _sim_state["running"] = False
        try:
            _log(db, "system", "error", f"Historical sim crashed: {e}")
            db.commit()
        except Exception:
            pass
    finally:
        _sim_state["running"] = False
        db.close()


# ---------------------------------------------------------------------------
# Public control functions
# ---------------------------------------------------------------------------

def start_sim():
    """Start the historical data paper mode simulation."""
    if _sim_state["running"]:
        return {"ok": False, "error": "Sim already running"}

    _sim_state["running"] = True
    _sim_state["error"] = ""
    _sim_state["progress"] = 0
    _sim_state["total_candles"] = 0
    _sim_state["opps_generated"] = 0
    _sim_state["trades_executed"] = 0
    _sim_state["started_at"] = datetime.utcnow().isoformat()
    _sim_state["pairs_loaded"] = 0
    _sim_state["current_day"] = ""

    t = threading.Thread(target=_sim_loop, daemon=True)
    _sim_state["thread"] = t
    t.start()
    return {"ok": True, "message": "Historical data paper mode started"}


def stop_sim():
    """Stop the simulation."""
    _sim_state["running"] = False
    # Also set is_running = False in DB
    db = SessionLocal()
    try:
        cfg = db.query(Config).first()
        if cfg:
            cfg.is_running = False
        db.commit()
    finally:
        db.close()
    return {"ok": True, "message": "Historical sim stopping"}
