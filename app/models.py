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


class OppStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    executed = "executed"
    skipped = "skipped"
    failed = "failed"


class BotName(str, enum.Enum):
    scanner = "scanner"
    calculator = "calculator"
    execution = "execution"


class BotState(str, enum.Enum):
    running = "running"
    paused = "paused"
    error = "error"
    offline = "offline"


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
    # Mode flags
    is_aggressive = Column(Boolean, default=False)
    is_real_execution = Column(Boolean, default=False)
    # Normal thresholds
    min_profit_normal = Column(Float, default=0.75)
    max_risk_per_trade = Column(Float, default=0.12)       # fraction of balance
    daily_loss_limit = Column(Float, default=0.05)         # fraction of balance
    max_open_exposure = Column(Float, default=0.30)       # fraction of balance
    # Aggressive thresholds
    min_profit_aggressive = Column(Float, default=0.40)
    max_risk_per_trade_aggressive = Column(Float, default=0.20)
    # Flash loan
    max_flashloan_size = Column(Float, default=1000.0)
    # Routers
    base_router = Column(String(64), default="0xd6145b2D3F3799E8CdEda7B97e37c4b2Ca9c40")
    eth_router = Column(String(64), default="0x23617e59A5925b2A4Bf75d73ff6711cD0b29De85")
    # Fee estimates
    cex_fee_pct = Column(Float, default=0.001)
    dex_fee_pct = Column(Float, default=0.003)
    gas_estimate_usd = Column(Float, default=2.0)
    slippage_pct = Column(Float, default=0.005)
    # Cooldowns (seconds)
    cooldown_normal = Column(Integer, default=300)
    cooldown_aggressive = Column(Integer, default=60)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Opportunity(Base):
    __tablename__ = "opportunities"
    id = Column(Integer, primary_key=True)
    pair = Column(String(64), nullable=False)
    network = Column(String(32), nullable=False, default="base")
    style = Column(Enum(StrategyStyle), default=StrategyStyle.inventory)
    # Cost breakdown
    buy_cost = Column(Float, default=0.0)
    sell_proceeds = Column(Float, default=0.0)
    cex_fees = Column(Float, default=0.0)
    dex_fees = Column(Float, default=0.0)
    estimated_gas = Column(Float, default=0.0)
    slippage_estimate = Column(Float, default=0.0)
    transfer_costs = Column(Float, default=0.0)
    flashloan_fee = Column(Float, default=0.0)
    net_profit = Column(Float, default=0.0)
    # Meta
    hops = Column(Integer, default=1)
    confidence = Column(Float, default=0.5)        # 0..1
    score = Column(Float, default=0.0)
    trade_size = Column(Float, default=0.0)
    status = Column(Enum(OppStatus), default=OppStatus.pending)
    source = Column(String(32), default="scanner")  # who pushed it
    created_at = Column(DateTime, default=datetime.utcnow)


class TradeLog(Base):
    __tablename__ = "trade_logs"
    id = Column(Integer, primary_key=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id"), nullable=True)
    mode = Column(Enum(TradeMode), default=TradeMode.paper)
    style = Column(Enum(StrategyStyle), default=StrategyStyle.inventory)
    network = Column(String(32), default="base")
    pair = Column(String(64))
    expected_profit = Column(Float, default=0.0)
    actual_profit = Column(Float, default=0.0)
    trade_size = Column(Float, default=0.0)
    status = Column(String(32), default="filled")     # filled / failed / reverted
    detail = Column(Text)
    executed_at = Column(DateTime, default=datetime.utcnow)


class BotHeartbeat(Base):
    __tablename__ = "bot_heartbeats"
    bot = Column(Enum(BotName), primary_key=True)
    state = Column(Enum(BotState), default=BotState.offline)
    last_heartbeat = Column(DateTime)
    last_action = Column(String(255))
    last_error = Column(Text)
    paused = Column(Boolean, default=False)


class AccountSnapshot(Base):
    __tablename__ = "account_snapshots"
    id = Column(Integer, primary_key=True)
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
    networks_unlocked = Column(Text, default="base")   # comma-separated
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class InsightLog(Base):
    __tablename__ = "insight_logs"
    id = Column(Integer, primary_key=True)
    category = Column(String(64))      # e.g. "by_pair", "by_time", "slippage"
    label = Column(String(128))
    metric = Column(String(64))        # e.g. "win_rate", "avg_slippage"
    value = Column(Float, default=0.0)
    sample_count = Column(Integer, default=0)
    observation = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
