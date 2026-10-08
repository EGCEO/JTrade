from typing import Optional, List, Dict, Any
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
    auto_compound: Optional[bool] = None
    min_profit_normal: Optional[float] = None
    max_risk_per_trade: Optional[float] = None
    daily_loss_limit: Optional[float] = None
    max_open_exposure: Optional[float] = None
    max_hops_normal: Optional[int] = None
    min_profit_aggressive: Optional[float] = None
    max_risk_per_trade_aggressive: Optional[float] = None
    max_hops_aggressive: Optional[int] = None
    target_attention_min: Optional[float] = None
    target_attention_max: Optional[float] = None
    max_flashloan_size: Optional[float] = None
    base_router: Optional[str] = None
    eth_router: Optional[str] = None
    cex_fee_pct: Optional[float] = None
    dex_fee_pct: Optional[float] = None
    gas_estimate_usd: Optional[float] = None
    slippage_pct: Optional[float] = None
    price_impact_pct: Optional[float] = None
    competition_haircut_pct: Optional[float] = None
    cooldown_normal: Optional[int] = None
    cooldown_aggressive: Optional[int] = None
    wallet_address: Optional[str] = None
    base_network: Optional[str] = None
    # Scoring engine config
    score_min_net_profit_usd: Optional[float] = None
    score_min_expected_value_usd: Optional[float] = None
    score_min_execution_probability: Optional[float] = None
    score_failure_gas_fraction: Optional[float] = None
    score_gas_k: Optional[float] = None
    score_hop_decay: Optional[float] = None
    score_impact_k: Optional[float] = None
    score_liquidity_floor: Optional[float] = None
    score_success_rate_weight: Optional[float] = None


# ---- Real Execution confirmation ----
class RealExecutionConfirm(BaseModel):
    confirm: bool = False
    phrase: str = ""


# ---- Capital actions ----
class CapitalAction(BaseModel):
    amount: float
    mode: str = "paper"     # paper | real
    note: str = ""


# ---- Opportunity (webhook push — new exact payload) ----
class OpportunityPush(BaseModel):
    # New format
    id: str = ""
    type: str = "flashloan"          # crossdex | flashloan | triangular | multihop
    network: str = "base"
    path: List[str] = []
    amountIn: str = "0"
    expectedAmountOut: str = "0"
    netProfit: str = "0"
    netProfitUsd: float = 0.0
    score: float = 0.0
    status: str = "approved"
    source: str = "quant"
    timestamp: Optional[int] = None
    # Old-format fields (backward compat)
    pair: str = ""
    style: str = ""
    buy_cost: float = 0.0
    sell_proceeds: float = 0.0
    cex_fees: float = 0.0
    dex_fees: float = 0.0
    estimated_gas: float = 0.0
    slippage_estimate: float = 0.0
    transfer_costs: float = 0.0
    flashloan_fee: float = 0.0
    price_impact_cost: float = 0.0
    competition_haircut: float = 0.0
    hops: int = 1
    confidence: float = 0.5
    trade_size: float = 0.0


# ---- Trade result (webhook push — new exact payload) ----
class TradeResultPush(BaseModel):
    # New format
    opportunityId: str = ""
    mode: str = "paper"
    status: str = "success"          # success | failed
    network: str = "base"
    txHash: str = ""
    amountIn: str = ""
    amountOut: str = ""
    netProfit: str = ""
    netProfitUsd: float = 0.0
    gasUsed: str = ""
    notes: str = ""
    timestamp: Optional[int] = None
    # Old-format fields (backward compat)
    opportunity_id: Optional[int] = None
    style: str = "inventory"
    pair: str = ""
    expected_profit: float = 0.0
    actual_profit: float = 0.0
    trade_size: float = 0.0
    detail: str = ""


# ---- Heartbeat (webhook push — new exact payload) ----
class HeartbeatPush(BaseModel):
    bot: str                        # scanner | quant | guardian | execution
    status: str = "running"
    message: str = ""
    timestamp: Optional[int] = None
    meta: Dict[str, Any] = {}
    # Old-format fields (backward compat)
    state: str = ""
    last_action: str = ""
    last_error: str = ""


# ---- Log push (webhook) ----
class LogPush(BaseModel):
    bot: str = "system"
    level: str = "info"
    message: str = ""
    meta: Dict[str, Any] = {}
    timestamp: Optional[int] = None


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
