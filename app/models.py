import json
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, ForeignKey
from app.database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Config(Base):
    __tablename__ = "config"
    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True, nullable=False)
    value = Column(Text, nullable=False)  # JSON-encoded
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class Opportunity(Base):
    __tablename__ = "opportunities"
    id = Column(Integer, primary_key=True)
    pair = Column(String, nullable=False)
    network = Column(String, nullable=False)
    style = Column(String, nullable=False)  # "inventory" or "flash_loan"
    buy_venue = Column(String, nullable=False)
    sell_venue = Column(String, nullable=False)
    buy_price = Column(Float, default=0)
    sell_price = Column(Float, default=0)
    gross_profit = Column(Float, default=0)
    estimated_costs = Column(Float, default=0)
    net_profit = Column(Float, default=0)
    confidence = Column(Float, default=50)  # 0-100
    hops = Column(Integer, default=1)
    status = Column(String, default="pending")  # pending, approved, rejected, executed, skipped
    priority_score = Column(Float, default=0)
    source = Column(String, default="")  # which bot pushed this (scanner, quant, etc.)
    external_id = Column(String, default="")  # external bot's own ID
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    executed_at = Column(DateTime, nullable=True)


class TradeLog(Base):
    __tablename__ = "trade_logs"
    id = Column(Integer, primary_key=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id"), nullable=True)
    mode = Column(String, nullable=False)  # "paper" or "real"
    style = Column(String, nullable=False)
    network = Column(String, nullable=False)
    pair = Column(String, nullable=False)
    expected_profit = Column(Float, default=0)
    actual_profit = Column(Float, default=0)
    status = Column(String, default="pending")  # success, failed, skipped
    buy_cost = Column(Float, default=0)
    sell_proceeds = Column(Float, default=0)
    fees = Column(Float, default=0)
    gas = Column(Float, default=0)
    slippage = Column(Float, default=0)
    net_result = Column(Float, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    notes = Column(Text, default="")


class BotHeartbeat(Base):
    __tablename__ = "bot_heartbeats"
    id = Column(Integer, primary_key=True)
    bot_name = Column(String, unique=True, nullable=False)  # scanner, calculator, executor
    status = Column(String, default="offline")  # running, paused, error, offline
    last_heartbeat = Column(DateTime, nullable=True)
    last_action = Column(String, default="")
    error_message = Column(String, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class AccountSnapshot(Base):
    __tablename__ = "account_snapshots"
    id = Column(Integer, primary_key=True)
    mode = Column(String, nullable=False)  # "paper" or "real"
    balance = Column(Float, nullable=False)
    starting_capital = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class TierProgress(Base):
    __tablename__ = "tier_progress"
    id = Column(Integer, primary_key=True)
    current_tier = Column(Integer, default=0)
    paper_balance = Column(Float, default=0)
    real_balance = Column(Float, default=0)
    unlocked_networks = Column(Text, default='["base"]')  # JSON array
    next_tier_requirement = Column(String, default="Reach $100 paper balance")
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class BotLog(Base):
    __tablename__ = "bot_logs"
    id = Column(Integer, primary_key=True)
    bot = Column(String, nullable=False)
    level = Column(String, default="info")  # info, warning, error
    message = Column(Text, nullable=False)
    meta = Column(Text, default="")  # JSON-encoded
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class InsightLog(Base):
    __tablename__ = "insight_logs"
    id = Column(Integer, primary_key=True)
    insight_type = Column(String, nullable=False)  # "pair_performance", "time_pattern", "slippage", etc.
    pair = Column(String, default="")
    network = Column(String, default="")
    metric = Column(String, default="")
    value = Column(Float, default=0)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    notes = Column(Text, default="")
