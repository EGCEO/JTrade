import enum
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, Enum
)
from sqlalchemy.orm import relationship
from app.database import Base


class TradeMode(str, enum.Enum):
    paper = "paper"
    real = "real"


class StrategyStyle(str, enum.Enum):
    inventory = "inventory"
    flashloan = "flashloan"


class OppType(str, enum.Enum):
    crossdex = "crossdex"
    flashloan = "flashloan"
    triangular = "triangular"
    multihop = "multihop"


class OppStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    executed = "executed"
    skipped = "skipped"
    failed = "failed"


class BotName(str, enum.Enum):
    scanner = "scanner"
    quant = "quant"
    guardian = "guardian"
    execution = "execution"
    calculator = "calculator"  # legacy alias for quant


class BotState(str, enum.Enum):
    running = "running"
    paused = "paused"
    error = "error"
    offline = "offline"


# The four active bots the system uses
ACTIVE_BOTS = [BotName.scanner, BotName.quant, BotName.guardian, BotName.execution]


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Config(Base):
    __tablename__ = "configs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    # Capital
    starting_capital = Column(Float, default=100.0)
    current_balance_paper = Column(Float, default=100.0)
    current_balance_real = Column(Float, default=0.0)
    sheets_auto_export = Column(Boolean, default=False)
    # Master controls
    is_running = Column(Boolean, default=False)
    auto_compound = Column(Boolean, default=False)
    # Mode flags
    is_aggressive = Column(Boolean, default=False)
    is_real_execution = Column(Boolean, default=False)
    # Bot auth
    bot_secret = Column(String(128), default="")
    # Wallet
    wallet_address = Column(String(64), default="")
    base_network = Column(String(32), default="base")
    # Normal thresholds
    min_profit_normal = Column(Float, default=0.75)
    max_risk_per_trade = Column(Float, default=0.12)       # fraction of balance
    daily_loss_limit = Column(Float, default=0.05)         # fraction of balance
    max_open_exposure = Column(Float, default=0.30)       # fraction of balance
    max_hops_normal = Column(Integer, default=2)
    # Aggressive thresholds
    min_profit_aggressive = Column(Float, default=0.40)
    max_risk_per_trade_aggressive = Column(Float, default=0.20)
    max_hops_aggressive = Column(Integer, default=4)
    # Attention zone
    target_attention_min = Column(Float, default=20.0)
    target_attention_max = Column(Float, default=100.0)
    # Flash loan
    max_flashloan_size = Column(Float, default=1000.0)
    # Routers
    base_router = Column(String(64), default="0x4752ba5dBc23f44D87826276bf6fd6b1C372aD24")  # Uniswap V2 Router02 on Base
    eth_router = Column(String(64), default="0x23617e59A5925b2A4Bf75d73ff6711cD0b29De85")
    base_chain_id = Column(Integer, default=8453)
    base_rpc_url = Column(String(128), default="https://mainnet.base.org")
    # Fee estimates
    cex_fee_pct = Column(Float, default=0.001)
    dex_fee_pct = Column(Float, default=0.003)
    gas_estimate_usd = Column(Float, default=2.0)
    slippage_pct = Column(Float, default=0.005)
    price_impact_pct = Column(Float, default=0.001)
    competition_haircut_pct = Column(Float, default=0.002)
    # Cooldowns (seconds)
    cooldown_normal = Column(Integer, default=300)
    cooldown_aggressive = Column(Integer, default=60)
    # Scoring engine config (tunable thresholds for Quant bot scoring)
    score_min_net_profit_usd = Column(Float, default=0.75)
    score_min_expected_value_usd = Column(Float, default=0.5)
    score_min_execution_probability = Column(Float, default=0.35)
    score_failure_gas_fraction = Column(Float, default=1.0)
    score_gas_k = Column(Float, default=1.8)
    score_hop_decay = Column(Float, default=0.85)
    score_impact_k = Column(Float, default=0.009)
    score_liquidity_floor = Column(Float, default=0.0)
    score_success_rate_weight = Column(Float, default=0.5)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Opportunity(Base):
    __tablename__ = "opportunities"
    id = Column(Integer, primary_key=True)
    # External ID (e.g. "opp_123")
    ext_id = Column(String(64), default="")
    pair = Column(String(64), nullable=False, default="")
    network = Column(String(32), nullable=False, default="base")
    style = Column(Enum(StrategyStyle), default=StrategyStyle.inventory)
    opp_type = Column(Enum(OppType), default=OppType.flashloan)
    # Token path (JSON array of addresses)
    path = Column(Text, default="[]")
    # Wei amounts (new format)
    amount_in = Column(String(80), default="0")
    expected_amount_out = Column(String(80), default="0")
    net_profit_wei = Column(String(80), default="0")
    net_profit_usd = Column(Float, default=0.0)
    # Cost breakdown (old format / USD)
    buy_cost = Column(Float, default=0.0)
    sell_proceeds = Column(Float, default=0.0)
    cex_fees = Column(Float, default=0.0)
    dex_fees = Column(Float, default=0.0)
    estimated_gas = Column(Float, default=0.0)
    slippage_estimate = Column(Float, default=0.0)
    transfer_costs = Column(Float, default=0.0)
    flashloan_fee = Column(Float, default=0.0)
    price_impact_cost = Column(Float, default=0.0)
    competition_haircut = Column(Float, default=0.0)
    net_profit = Column(Float, default=0.0)
    # Meta
    hops = Column(Integer, default=1)
    confidence = Column(Float, default=0.5)        # 0..1
    score = Column(Float, default=0.0)
    trade_size = Column(Float, default=0.0)
    status = Column(Enum(OppStatus), default=OppStatus.pending)
    source = Column(String(32), default="scanner")
    created_at = Column(DateTime, default=datetime.utcnow)


class TradeLog(Base):
    __tablename__ = "trade_logs"
    id = Column(Integer, primary_key=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id"), nullable=True)
    ext_opportunity_id = Column(String(64), default="")
    mode = Column(Enum(TradeMode), default=TradeMode.paper)
    style = Column(Enum(StrategyStyle), default=StrategyStyle.inventory)
    network = Column(String(32), default="base")
    pair = Column(String(64))
    expected_profit = Column(Float, default=0.0)
    actual_profit = Column(Float, default=0.0)
    net_profit_usd = Column(Float, default=0.0)
    trade_size = Column(Float, default=0.0)
    status = Column(String(32), default="filled")
    detail = Column(Text)
    # New format fields
    tx_hash = Column(String(80), default="")
    amount_in = Column(String(80), default="")
    amount_out = Column(String(80), default="")
    net_profit_wei = Column(String(80), default="")
    gas_used = Column(String(80), default="")
    gas_cost_usd = Column(Float, default=0.0)
    slippage_cost = Column(Float, default=0.0)
    notes = Column(Text, default="")
    executed_at = Column(DateTime, default=datetime.utcnow)


class BotHeartbeat(Base):
    __tablename__ = "bot_heartbeats"
    bot = Column(Enum(BotName), primary_key=True)
    state = Column(Enum(BotState), default=BotState.offline)
    last_heartbeat = Column(DateTime)
    heartbeat_source = Column(String(32), default="unknown")
    last_action = Column(String(255))
    last_error = Column(Text)
    paused = Column(Boolean, default=False)


class AccountSnapshot(Base):
    __tablename__ = "account_snapshots"
    id = Column(Integer, primary_key=True)
    simulated_at = Column(DateTime, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    balance_paper = Column(Float, default=0.0)
    balance_real = Column(Float, default=0.0)
    mode = Column(Enum(TradeMode), default=TradeMode.paper)
    tier = Column(Integer, default=1)


class TierProgress(Base):
    __tablename__ = "tier_progress"
    id = Column(Integer, primary_key=True)
    current_tier = Column(Integer, default=1)
    highest_balance = Column(Float, default=0.0)
    networks_unlocked = Column(Text, default="base")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class InsightLog(Base):
    __tablename__ = "insight_logs"
    id = Column(Integer, primary_key=True)
    category = Column(String(64))
    label = Column(String(128))
    metric = Column(String(64))
    value = Column(Float, default=0.0)
    sample_count = Column(Integer, default=0)
    observation = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class Log(Base):
    __tablename__ = "logs"
    id = Column(Integer, primary_key=True)
    bot = Column(String(32), default="system")
    level = Column(String(16), default="info")     # info, warning, error
    message = Column(Text, default="")
    meta = Column(Text, default="{}")              # JSON
    created_at = Column(DateTime, default=datetime.utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    type = Column(String(32), default="info")      # info, warning, error, success, trade
    title = Column(String(255), default="")
    message = Column(Text, default="")
    read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class CapitalTransaction(Base):
    __tablename__ = "capital_transactions"
    id = Column(Integer, primary_key=True)
    type = Column(String(32), default="adjustment")  # deposit, withdraw, compound, profit, loss, adjustment
    mode = Column(Enum(TradeMode), default=TradeMode.paper)
    amount = Column(Float, default=0.0)
    balance_after = Column(Float, default=0.0)
    note = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class LearnedPattern(Base):
    __tablename__ = "learned_patterns"
    id = Column(Integer, primary_key=True)
    dimension = Column(String(32), nullable=False)      # pair, network, style, hops, size, time, pair_network
    label = Column(String(128), nullable=False)         # e.g. "BTC/USDT", "base", "flashloan"
    win_rate = Column(Float, default=0.0)                 # 0..1
    avg_profit = Column(Float, default=0.0)
    avg_loss = Column(Float, default=0.0)
    total_pnl = Column(Float, default=0.0)
    sample_count = Column(Integer, default=0)
    confidence = Column(Float, default=0.0)              # 0..1 (statistical confidence)
    adjustment_factor = Column(Float, default=0.0)       # -0.20..+0.20 nudge for scoring
    recommendation = Column(Text, default="")
    is_actionable = Column(Boolean, default=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PerformanceSnapshot(Base):
    __tablename__ = "performance_snapshots"
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    mode = Column(Enum(TradeMode), default=TradeMode.paper)
    balance = Column(Float, default=0.0)
    total_pnl = Column(Float, default=0.0)
    daily_pnl = Column(Float, default=0.0)
    win_rate = Column(Float, default=0.0)
    avg_profit = Column(Float, default=0.0)
    avg_loss = Column(Float, default=0.0)
    drawdown = Column(Float, default=0.0)
    max_drawdown = Column(Float, default=0.0)
    trade_count = Column(Integer, default=0)
