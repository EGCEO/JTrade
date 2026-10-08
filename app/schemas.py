from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


# ---- Auth ----
class UserCreate(BaseModel):
    username: str
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


# ---- Config ----
class ConfigUpdate(BaseModel):
    starting_capital: Optional[float] = None
    current_balance_paper: Optional[float] = None
    current_balance_real: Optional[float] = None
    is_aggressive: Optional[bool] = None
    is_real_execution: Optional[bool] = None
    min_profit_normal: Optional[float] = None
    max_risk_per_trade: Optional[float] = None
    daily_loss_limit: Optional[float] = None
    max_open_exposure: Optional[float] = None
    min_profit_aggressive: Optional[float] = None
    max_risk_per_trade_aggressive: Optional[float] = None
    max_flashloan_size: Optional[float] = None
    base_router: Optional[str] = None
    eth_router: Optional[str] = None
    cex_fee_pct: Optional[float] = None
    dex_fee_pct: Optional[float] = None
    gas_estimate_usd: Optional[float] = None
    slippage_pct: Optional[float] = None
    cooldown_normal: Optional[int] = None
    cooldown_aggressive: Optional[int] = None


# ---- Real Execution confirmation ----
class RealExecutionConfirm(BaseModel):
    confirm: bool = False
    phrase: str = ""


# ---- Opportunity (webhook push) ----
class OpportunityPush(BaseModel):
    pair: str
    network: str = "base"
    style: str = "inventory"        # inventory | flashloan
    buy_cost: float = 0.0
    sell_proceeds: float = 0.0
    cex_fees: float = 0.0
    dex_fees: float = 0.0
    estimated_gas: float = 0.0
    slippage_estimate: float = 0.0
    transfer_costs: float = 0.0
    flashloan_fee: float = 0.0
    hops: int = 1
    confidence: float = 0.5
    trade_size: float = 0.0
    source: str = "scanner"


# ---- Trade result (webhook push) ----
class TradeResultPush(BaseModel):
    opportunity_id: Optional[int] = None
    mode: str = "paper"
    style: str = "inventory"
    network: str = "base"
    pair: str = ""
    expected_profit: float = 0.0
    actual_profit: float = 0.0
    trade_size: float = 0.0
    status: str = "filled"
    detail: str = ""


# ---- Heartbeat (webhook push) ----
class HeartbeatPush(BaseModel):
    bot: str                        # scanner | calculator | execution
    state: str = "running"
    last_action: str = ""
    last_error: str = ""


# ---- Balance update (webhook push) ----
class BalanceUpdate(BaseModel):
    balance_paper: Optional[float] = None
    balance_real: Optional[float] = None
    mode: Optional[str] = None


# ---- Insight ----
class InsightPush(BaseModel):
    category: str
    label: str
    metric: str
    value: float = 0.0
    sample_count: int = 0
    observation: str = ""
