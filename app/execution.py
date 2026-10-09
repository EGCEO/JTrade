"""Real execution engine for Base DEX arbitrage trades.

Uses web3 to sign and broadcast transactions on Base mainnet.
Wallet credentials (PRIVATE_KEY, WALLET_ADDRESS) are delivered via secrets.
"""
import os
import json
import time
import logging

from web3 import Web3

logger = logging.getLogger(__name__)

BASE_RPC_URL = os.environ.get("BASE_RPC_URL", "https://mainnet.base.org")

# ── Minimal ABIs ──────────────────────────────────────────────────────────────
ROUTER_ABI = json.loads('''[
  {"constant":true,"inputs":[{"name":"amountIn","type":"uint256"},{"name":"path","type":"address[]"}],"name":"getAmountsOut","outputs":[{"name":"","type":"uint256[]"}],"payable":false,"stateMutability":"view","type":"function"},
  {"constant":false,"inputs":[{"name":"amountIn","type":"uint256"},{"name":"amountOutMin","type":"uint256"},{"name":"path","type":"address[]"},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"name":"swapExactTokensForTokens","outputs":[{"name":"amounts","type":"uint256[]"}],"payable":false,"stateMutability":"nonpayable","type":"function"},
  {"constant":false,"inputs":[{"name":"amountIn","type":"uint256"},{"name":"amountOutMin","type":"uint256"},{"name":"path","type":"address[]"},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"name":"swapExactTokensForETH","outputs":[{"name":"amounts","type":"uint256[]"}],"payable":false,"stateMutability":"nonpayable","type":"function"},
  {"constant":false,"inputs":[{"name":"amountIn","type":"uint256"},{"name":"amountOutMin","type":"uint256"},{"name":"path","type":"address[]"},{"name":"to","type":"address"},{"name":"deadline","type":"uint256"}],"name":"swapExactETHForTokens","outputs":[{"name":"amounts","type":"uint256[]"}],"payable":true,"stateMutability":"payable","type":"function"}
]''')

ERC20_ABI = json.loads('''[
  {"constant":false,"inputs":[{"name":"spender","type":"address"},{"name":"value","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"payable":false,"stateMutability":"nonpayable","type":"function"},
  {"constant":true,"inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"payable":false,"stateMutability":"view","type":"function"},
  {"constant":true,"inputs":[{"name":"owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"payable":false,"stateMutability":"view","type":"function"},
  {"constant":true,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"payable":false,"stateMutability":"view","type":"function"},
  {"constant":true,"inputs":[],"name":"symbol","outputs":[{"name":"","type":"string"}],"payable":false,"stateMutability":"view","type":"function"}
]''')

# Base mainnet token addresses
BASE_TOKENS = {
    "WETH":  "0x4200000000000000000000000000000000000006",
    "USDC":  "0x833589fCD6eDb6E08f4c7C32D4f71B54bdA02913",
    "USDbC": "0xd9aAEc86B65D86f6A7B5B1b0c42FFA531710b6CA",
    "DAI":   "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb",
}

BASE_ROUTERS = {
    "Aerodrome": "0xcF77a3Ba9A5CA3a3C8d1A1c421B677934371B306",
    "UniswapV2": "0x4752ba5dbc23f44d87826276bf6fd6b1c372ad24",
    "BaseSwap":  "0x327Df1E6de05895d2ab08513aaDD9313Fe505d86",
}

WETH_ABI = json.loads('''[
  {"constant":false,"inputs":[],"name":"deposit","outputs":[],"payable":true,"stateMutability":"payable","type":"function"},
  {"constant":false,"inputs":[{"name":"wad","type":"uint256"}],"name":"withdraw","outputs":[],"payable":false,"stateMutability":"nonpayable","type":"function"},
  {"constant":true,"inputs":[{"name":"owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"payable":false,"stateMutability":"view","type":"function"}
]''')

BASE_CHAIN_ID = 8453


class ExecutionEngine:
    """Signs and broadcasts real DEX trades on Base."""

    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(BASE_RPC_URL))
        self.private_key = os.environ.get("PRIVATE_KEY", "")
        self.wallet_address = os.environ.get("WALLET_ADDRESS", "")
        self.account = None
        if self.private_key and self.w3.is_connected():
            try:
                pk = self.private_key
                if not pk.startswith("0x"):
                    pk = "0x" + pk
                self.account = self.w3.eth.account.from_key(pk)
            except Exception as e:
                logger.error("Failed to load wallet key: %s", e)

    # ── Status ────────────────────────────────────────────────────────────────
    def is_configured(self) -> bool:
        if not (self.private_key and self.wallet_address and self.w3.is_connected()):
            return False
        if not self.account:
            return False
        return self.account.address.lower() == self.wallet_address.lower()

    def get_status(self) -> dict:
        connected = self.w3.is_connected()
        chain_id = None
        balance = 0
        if connected:
            try:
                chain_id = self.w3.eth.chain_id
                if self.wallet_address:
                    balance = float(self.w3.from_wei(
                        self.w3.eth.get_balance(self.wallet_address), "ether"))
            except Exception:
                pass
        return {
            "configured": self.is_configured(),
            "connected": connected,
            "wallet_address": self.wallet_address or "",
            "chain_id": chain_id,
            "balance": round(balance, 6),
            "network": "Base Mainnet" if chain_id == BASE_CHAIN_ID else
                       f"Chain {chain_id}" if chain_id else "Unknown",
            "private_key_set": bool(self.private_key),
        }

    # ── Simulation ────────────────────────────────────────────────────────────
    def get_amounts_out(self, router_address: str, amount_in: int, path: list[str]) -> list[int]:
        """Return expected output amounts for a given input via getAmountsOut."""
        router = self.w3.eth.contract(
            address=Web3.to_checksum_address(router_address), abi=ROUTER_ABI)
        return router.functions.getAmountsOut(amount_in, path).call()

    # ── Execution ──────────────────────────────────────────────────────────────
    def _send_tx(self, tx: dict) -> dict:
        """Sign, send, and wait for a transaction. Returns receipt summary."""
        if not self.account:
            return {"success": False, "error": "Wallet not configured"}
        try:
            signed = self.account.sign_transaction(tx)
            raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
            tx_hash = self.w3.eth.send_raw_transaction(raw)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            return {
                "success": receipt.status == 1,
                "tx_hash": tx_hash.hex(),
                "gas_used": receipt.gasUsed,
                "block_number": receipt.blockNumber,
            }
        except Exception as e:
            logger.error("Transaction failed: %s", e)
            return {"success": False, "error": str(e)}

    def _ensure_allowance(self, token_address: str, router_address: str,
                          amount_needed: int) -> dict:
        """Approve router to spend tokens if allowance is insufficient."""
        token = self.w3.eth.contract(
            address=Web3.to_checksum_address(token_address), abi=ERC20_ABI)
        spender = Web3.to_checksum_address(router_address)
        current = token.functions.allowance(self.account.address, spender).call()
        if current >= amount_needed:
            return {"success": True, "skipped": True}
        tx = token.functions.approve(spender, 2**256 - 1).build_transaction({
            "from": self.account.address,
            "nonce": self.w3.eth.get_transaction_count(self.account.address),
            "gas": 100_000,
            "gasPrice": self.w3.eth.gas_price,
        })
        return self._send_tx(tx)

    def execute_swap(self, router_address: str, token_in: str, token_out: str,
                     amount_in: int, amount_out_min: int = 0) -> dict:
        """Execute a single ERC20→ERC20 swap on a V2-compatible router."""
        if not self.is_configured():
            return {"success": False, "error": "Wallet not configured"}
        router_addr = Web3.to_checksum_address(router_address)
        token_in_addr = Web3.to_checksum_address(token_in)
        token_out_addr = Web3.to_checksum_address(token_out)

        # Approve
        appr = self._ensure_allowance(token_in_addr, router_addr, amount_in)
        if not appr.get("success"):
            return appr

        router = self.w3.eth.contract(address=router_addr, abi=ROUTER_ABI)
        deadline = int(time.time()) + 300
        path = [token_in_addr, token_out_addr]
        func = router.functions.swapExactTokensForTokens(
            amount_in, amount_out_min, path, self.account.address, deadline)
        tx = func.build_transaction({
            "from": self.account.address,
            "nonce": self.w3.eth.get_transaction_count(self.account.address),
            "gas": 300_000,
            "gasPrice": self.w3.eth.gas_price,
        })
        return self._send_tx(tx)

    def wrap_eth(self, amount_wei: int) -> dict:
        """Wrap native ETH to WETH on Base."""
        if not self.is_configured():
            return {"success": False, "error": "Wallet not configured"}
        weth = self.w3.eth.contract(
            address=Web3.to_checksum_address(BASE_TOKENS["WETH"]), abi=WETH_ABI)
        tx = weth.functions.deposit().build_transaction({
            "from": self.account.address,
            "nonce": self.w3.eth.get_transaction_count(self.account.address),
            "gas": 100_000,
            "gasPrice": self.w3.eth.gas_price,
            "value": amount_wei,
        })
        return self._send_tx(tx)

    def test_swap(self, router_name: str = "UniswapV2",
                   token_in_name: str = "WETH", token_out_name: str = "USDC",
                   amount_in_human: float = 0.001) -> dict:
        """Execute a minimal test swap to verify execution engine and chain communication.

        Defaults to swapping 0.001 WETH for USDC on Aerodrome.
        If the wallet has no WETH, wraps ETH to WETH first.
        Returns detailed result for verification.
        """
        if not self.is_configured():
            return {"success": False, "error": "Wallet not configured"}

        router_address = BASE_ROUTERS.get(router_name)
        if not router_address:
            return {"success": False, "error": f"Unknown router: {router_name}"}

        token_in_addr = BASE_TOKENS.get(token_in_name)
        token_out_addr = BASE_TOKENS.get(token_out_name)
        if not token_in_addr or not token_out_addr:
            return {"success": False,
                    "error": f"Unknown tokens: {token_in_name}/{token_out_name}"}

        token_in_cs = Web3.to_checksum_address(token_in_addr)
        token_out_cs = Web3.to_checksum_address(token_out_addr)
        token_in_contract = self.w3.eth.contract(address=token_in_cs, abi=ERC20_ABI)
        token_out_contract = self.w3.eth.contract(address=token_out_cs, abi=ERC20_ABI)

        try:
            dec_in = token_in_contract.functions.decimals().call()
            dec_out = token_out_contract.functions.decimals().call()
        except Exception as e:
            return {"success": False, "error": f"Failed to read decimals: {e}"}

        amount_in_raw = int(amount_in_human * (10 ** dec_in))

        # Check token balance — if insufficient WETH, wrap ETH first
        balance = token_in_contract.functions.balanceOf(self.account.address).call()
        result = {
            "router": router_name,
            "router_address": router_address,
            "token_in": token_in_name,
            "token_out": token_out_name,
            "amount_in_human": amount_in_human,
            "amount_in_raw": amount_in_raw,
            "token_in_balance_before": balance,
        }

        if balance < amount_in_raw:
            if token_in_name == "WETH":
                eth_balance = self.w3.eth.get_balance(self.account.address)
                gas_needed = 100_000 * self.w3.eth.gas_price
                if eth_balance < amount_in_raw + gas_needed:
                    result["success"] = False
                    result["error"] = (
                        f"Insufficient ETH to wrap. Have "
                        f"{self.w3.from_wei(eth_balance, 'ether')} ETH, "
                        f"need ~{self.w3.from_wei(amount_in_raw + gas_needed, 'ether')} ETH")
                    return result
                wrap_result = self.wrap_eth(amount_in_raw)
                result["wrap_eth"] = wrap_result
                if not wrap_result.get("success"):
                    result["success"] = False
                    result["error"] = f"ETH wrapping failed: {wrap_result.get('error')}"
                    return result
                balance = token_in_contract.functions.balanceOf(
                    self.account.address).call()
                result["token_in_balance_after_wrap"] = balance
                if balance < amount_in_raw:
                    result["success"] = False
                    result["error"] = "WETH balance still insufficient after wrapping"
                    return result
            else:
                result["success"] = False
                result["error"] = (
                    f"Insufficient {token_in_name} balance: "
                    f"have {balance / (10 ** dec_in)}, need {amount_in_human}")
                return result

        # Get expected output
        try:
            amounts = self.get_amounts_out(router_address, amount_in_raw,
                                           [token_in_cs, token_out_cs])
            expected_out = amounts[-1]
            result["expected_output_raw"] = expected_out
            result["expected_output_human"] = expected_out / (10 ** dec_out)
        except Exception as e:
            result["success"] = False
            result["error"] = f"Failed to quote swap: {e}"
            return result

        # Execute the swap
        swap_result = self.execute_swap(router_address, token_in_addr,
                                         token_out_addr, amount_in_raw,
                                         amount_out_min=0)
        result.update(swap_result)

        # Get token_out balance after
        if swap_result.get("success"):
            try:
                bal_after = token_out_contract.functions.balanceOf(
                    self.account.address).call()
                result["token_out_balance_after"] = bal_after
                result["token_out_balance_after_human"] = bal_after / (10 ** dec_out)
            except Exception:
                pass

        return result

    def send_eth(self, to_address: str, amount_eth: float) -> dict:
        """Send native ETH from the configured wallet to a destination address."""
        if not self.is_configured():
            return {"success": False, "error": "Wallet not configured"}
        try:
            to_cs = Web3.to_checksum_address(to_address)
        except Exception:
            return {"success": False, "error": "Invalid destination address"}

        amount_wei = self.w3.to_wei(amount_eth, "ether")
        eth_balance = self.w3.eth.get_balance(self.account.address)
        gas_price = self.w3.eth.gas_price
        gas_cost = 21_000 * gas_price
        if eth_balance < amount_wei + gas_cost:
            available_wei = max(0, eth_balance - gas_cost)
            available = float(self.w3.from_wei(available_wei, "ether"))
            return {"success": False, "error": f"Insufficient ETH. Available after gas: {available:.6f} ETH"}

        tx = {
            "from": self.account.address,
            "to": to_cs,
            "value": amount_wei,
            "nonce": self.w3.eth.get_transaction_count(self.account.address),
            "gas": 21_000,
            "gasPrice": gas_price,
            "chainId": self.w3.eth.chain_id,
        }
        result = self._send_tx(tx)
        if result.get("success"):
            result["amount_eth"] = amount_eth
            result["to_address"] = to_address
            result["tx_hash"] = result.get("tx_hash", "")
        return result

    def execute_arbitrage(self, opportunity, config: dict) -> dict:
        """Execute a two-leg arbitrage: buy on cheaper DEX, sell on more expensive DEX.

        ``opportunity`` is an Opportunity ORM row with buy_venue/sell_venue
        containing router addresses, and buy_price/sell_price in USD.
        Returns a dict with success, tx hashes, gas, and net result.
        """
        if not self.is_configured():
            return {"success": False, "error": "Wallet not configured"}

        # Resolve token addresses from the pair string (e.g. "WETH/USDC")
        parts = opportunity.pair.split("/")
        if len(parts) != 2:
            return {"success": False, "error": f"Cannot parse pair: {opportunity.pair}"}
        token_a, token_b = parts[0].strip(), parts[1].strip()
        if token_a not in BASE_TOKENS or token_b not in BASE_TOKENS:
            return {"success": False,
                    "error": f"Unknown tokens: {token_a}/{token_b}. Add to BASE_TOKENS."}

        token_in_addr = BASE_TOKENS[token_a]
        token_out_addr = BASE_TOKENS[token_b]

        # Determine trade size from config
        balance = config.get("current_real_balance", 0)
        tier_max = config.get("max_risk_normal", 0.12)
        trade_size_usd = min(balance * tier_max, balance) if balance > 0 else 0
        if trade_size_usd <= 0:
            return {"success": False, "error": "Insufficient real balance for execution"}

        # Convert USD size to token amount (use buy_price as price of token_a in USD)
        price_a = opportunity.buy_price if opportunity.buy_price > 0 else 1
        amount_a = trade_size_usd / price_a

        # Get decimals
        token_in_contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(token_in_addr), abi=ERC20_ABI)
        token_out_contract = self.w3.eth.contract(
            address=Web3.to_checksum_address(token_out_addr), abi=ERC20_ABI)
        try:
            dec_in = token_in_contract.functions.decimals().call()
            dec_out = token_out_contract.functions.decimals().call()
        except Exception as e:
            return {"success": False, "error": f"Failed to read decimals: {e}"}

        amount_in_raw = int(amount_a * (10 ** dec_in))

        # Leg 1: Buy token_b on the cheaper DEX (buy_venue)
        buy_router = opportunity.buy_venue
        result = {"legs": [], "gas_total": 0}

        leg1 = self.execute_swap(buy_router, token_in_addr, token_out_addr,
                                 amount_in_raw, amount_out_min=0)
        result["legs"].append({"leg": "buy", "router": buy_router, **leg1})
        if not leg1.get("success"):
            result["success"] = False
            result["error"] = f"Buy leg failed: {leg1.get('error', 'unknown')}"
            return result
        result["gas_total"] += leg1.get("gas_used", 0)

        # Get actual output from leg 1
        try:
            amounts = self.get_amounts_out(buy_router, amount_in_raw,
                                           [token_in_addr, token_out_addr])
            amount_b_received = amounts[-1]
        except Exception:
            amount_b_received = 0

        if amount_b_received <= 0:
            result["success"] = False
            result["error"] = "Buy leg produced zero output"
            return result

        # Leg 2: Sell token_b back to token_a on the more expensive DEX (sell_venue)
        sell_router = opportunity.sell_venue
        # Approve sell router to spend token_b
        appr = self._ensure_allowance(token_out_addr, sell_router, amount_b_received)
        if not appr.get("success"):
            result["success"] = False
            result["error"] = f"Approval for sell leg failed: {appr.get('error')}"
            return result

        router = self.w3.eth.contract(
            address=Web3.to_checksum_address(sell_router), abi=ROUTER_ABI)
        deadline = int(time.time()) + 300
        path = [Web3.to_checksum_address(token_out_addr),
                Web3.to_checksum_address(token_in_addr)]
        func = router.functions.swapExactTokensForTokens(
            amount_b_received, 0, path, self.account.address, deadline)
        tx = func.build_transaction({
            "from": self.account.address,
            "nonce": self.w3.eth.get_transaction_count(self.account.address),
            "gas": 300_000,
            "gasPrice": self.w3.eth.gas_price,
        })
        leg2 = self._send_tx(tx)
        result["legs"].append({"leg": "sell", "router": sell_router, **leg2})
        if not leg2.get("success"):
            result["success"] = False
            result["error"] = f"Sell leg failed: {leg2.get('error', 'unknown')}"
            return result
        result["gas_total"] += leg2.get("gas_used", 0)

        # Calculate net result
        try:
            final_balance = token_in_contract.functions.balanceOf(
                self.account.address).call()
            initial_balance_raw = int(amount_in_raw)
            net_raw = final_balance - initial_balance
            net_result = net_raw / (10 ** dec_in)
        except Exception:
            net_result = 0

        gas_cost_eth = result["gas_total"] * self.w3.eth.gas_price / 1e18
        gas_cost_usd = gas_cost_eth * (opportunity.buy_price or 2500)

        result["success"] = True
        result["net_result"] = round(net_result, 6)
        result["gas_cost_usd"] = round(gas_cost_usd, 4)
        result["trade_size_usd"] = round(trade_size_usd, 2)
        return result
