"""Scanner Bot for Base DEXes.

Monitors token pairs across V2-compatible DEX routers on Base mainnet,
detects cross-DEX and triangular arbitrage opportunities, and pushes them
to the Arbitrage Gods dashboard via webhook.

Run as:  python -m app.scanner_bot
"""
import os
import json
import time
import logging
import requests
from datetime import datetime, timezone

from web3 import Web3

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("scanner")

# ── Configuration ─────────────────────────────────────────────────────────────
BASE_RPC_URL = os.environ.get("BASE_RPC_URL", "https://mainnet.base.org")
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://web:3000")
WEBHOOK_API_KEY = os.environ.get("WEBHOOK_API_KEY", "dev-webhook-key")
SCAN_INTERVAL = int(os.environ.get("SCAN_INTERVAL", "15"))
SCAN_AMOUNT_USD = float(os.environ.get("SCAN_AMOUNT_USD", "100"))

# DEX routers on Base (V2-compatible — must support getAmountsOut)
# Aerodrome is the primary V2-style DEX on Base.
DEFAULT_ROUTERS = {
    "Aerodrome":  "0xcF77a3Ba9A5CA3a3C8d1A1c421B677934371B306",
    "UniswapV2":  "0x4752ba5dbc23f44d87826276bf6fd6b1c372ad24",
    "BaseSwap":   "0x327Df1E6de05895d2ab08513aaDD9313Fe505d86",
}

# Load extra routers from env: SCANNER_ROUTERS=Name1:0xaddr1,Name2:0xaddr2
_extra = os.environ.get("SCANNER_ROUTERS", "")
if _extra:
    for entry in _extra.split(","):
        if ":" in entry:
            name, addr = entry.split(":", 1)
            DEFAULT_ROUTERS[name.strip()] = addr.strip()

# Token pairs to monitor on Base
TOKENS = {
    "WETH":  {"address": "0x4200000000000000000000000000000000000006", "decimals": 18},
    "USDC":  {"address": "0x833589fCD6eDb6E08f4c7C32D4f71B54bdA02913", "decimals": 6},
    "USDbC": {"address": "0xd9aAEc8B5e561C9b3Ea3A6d87E3Df7C0c4F2E3A5", "decimals": 6},
    "DAI":   {"address": "0x50c4B2eA67927d3Bf3a82F8E20Aa8e3c83F4D7b6", "decimals": 18},
}

# Pairs to scan (base/quote)
SCAN_PAIRS = [
    ("WETH", "USDC"),
    ("WETH", "USDbC"),
    ("WETH", "DAI"),
    ("USDC", "USDbC"),
    ("USDC", "DAI"),
]

# Triangular paths to check within each DEX
TRIANGULAR_PATHS = [
    ("USDC", "WETH", "USDC"),
    ("USDbC", "WETH", "USDbC"),
    ("DAI", "WETH", "DAI"),
    ("USDC", "DAI", "USDC"),
]

# Fee estimates
DEX_FEE_PCT = 0.003       # 0.3% per swap
GAS_ESTIMATE_USD = 1.5     # Base gas is cheap
SLIPPAGE_PCT = 0.005       # 0.5%

# ── ABI ───────────────────────────────────────────────────────────────────────
ROUTER_ABI = json.loads('''[
  {"constant":true,"inputs":[{"name":"amountIn","type":"uint256"},{"name":"path","type":"address[]"}],"name":"getAmountsOut","outputs":[{"name":"","type":"uint256[]"}],"payable":false,"stateMutability":"view","type":"function"}
]''')

ERC20_ABI = json.loads('''[
  {"constant":true,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"payable":false,"stateMutability":"view","type":"function"}
]''')


class ScannerBot:
    """Scans Base DEXes for arbitrage and pushes opportunities to the dashboard."""

    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(BASE_RPC_URL))
        self.routers = DEFAULT_ROUTERS
        self.opportunities_pushed = 0
        self.scans_completed = 0
        self.last_action = "Starting up"

        # Cache token decimals
        self._decimals_cache = {}
        for name, info in TOKENS.items():
            self._decimals_cache[name] = info["decimals"]

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _router_contract(self, addr: str):
        return self.w3.eth.contract(
            address=Web3.to_checksum_address(addr), abi=ROUTER_ABI)

    def _to_raw(self, amount_human: float, token_name: str) -> int:
        decimals = self._decimals_cache.get(token_name, 18)
        return int(amount_human * (10 ** decimals))

    def _from_raw(self, amount_raw: int, token_name: str) -> float:
        decimals = self._decimals_cache.get(token_name, 18)
        return amount_raw / (10 ** decimals)

    def _get_amounts_out(self, router_addr: str, amount_in_raw: int,
                         path_tokens: list[str]) -> int | None:
        """Call getAmountsOut on a router. Returns last amount (output) or None."""
        path = [Web3.to_checksum_address(TOKENS[t]["address"]) for t in path_tokens]
        try:
            router = self._router_contract(router_addr)
            amounts = router.functions.getAmountsOut(amount_in_raw, path).call()
            return amounts[-1] if amounts else None
        except Exception as e:
            logger.debug("getAmountsOut failed on %s for %s: %s",
                         router_addr, path_tokens, e)
            return None

    # ── Dashboard communication ──────────────────────────────────────────────────
    def _push_opportunity(self, data: dict) -> bool:
        """Push an opportunity to the dashboard webhook."""
        url = f"{DASHBOARD_URL}/api/opportunities"
        headers = {"Content-Type": "application/json", "X-API-Key": WEBHOOK_API_KEY}
        try:
            resp = requests.post(url, json=data, headers=headers, timeout=10)
            if resp.status_code == 200:
                self.opportunities_pushed += 1
                logger.info("Pushed opportunity: %s on %s → %s (net $%.2f)",
                            data["pair"], data["buy_venue"], data["sell_venue"],
                            data["net_profit"])
                return True
            else:
                logger.warning("Push failed (%d): %s", resp.status_code, resp.text[:200])
        except Exception as e:
            logger.warning("Push error: %s", e)
        return False

    def _send_heartbeat(self, status: str = "running", action: str = "",
                        error: str = ""):
        url = f"{DASHBOARD_URL}/api/bots/scanner/heartbeat"
        headers = {"Content-Type": "application/json", "X-API-Key": WEBHOOK_API_KEY}
        payload = {"status": status, "last_action": action, "error_message": error}
        try:
            requests.post(url, json=payload, headers=headers, timeout=5)
        except Exception:
            pass

    def _read_mode(self) -> dict | None:
        """Read current mode/thresholds from the dashboard."""
        url = f"{DASHBOARD_URL}/api/mode"
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return None

    # ── Scanning ─────────────────────────────────────────────────────────────────
    def scan_cross_dex(self):
        """Compare prices for each pair across all configured DEX routers."""
        if len(self.routers) < 2:
            return  # Need at least 2 DEXes for cross-DEX arbitrage

        router_items = list(self.routers.items())

        for base_tok, quote_tok in SCAN_PAIRS:
            # Scan amount in quote token (e.g., 100 USDC)
            amount_in_raw = self._to_raw(SCAN_AMOUNT_USD, quote_tok)
            prices = {}  # router_name -> output_amount_raw

            for name, addr in router_items:
                out = self._get_amounts_out(addr, amount_in_raw,
                                            [quote_tok, base_tok])
                if out and out > 0:
                    prices[name] = out

            if len(prices) < 2:
                continue

            # Find best (most base_tok per quote_tok) and worst
            sorted_dexes = sorted(prices.items(), key=lambda x: x[1], reverse=True)
            best_dex, best_out = sorted_dexes[0]
            worst_dex, worst_out = sorted_dexes[-1]

            if best_dex == worst_dex:
                continue

            # Calculate profit: buy base_tok on best (cheapest), sell on worst
            # Actually: we get MORE base_tok on best_dex, so buy there.
            # Then sell base_tok back to quote_tok on worst_dex.
            # But for cross-DEX, we buy on the DEX that gives more base_tok per quote_tok,
            # and sell on the DEX that gives more quote_tok per base_tok.
            # Simplification: buy base_tok where price is lowest, sell where highest.

            base_received = self._from_raw(best_out, base_tok)

            # Now sell base_received back to quote_tok on worst_dex
            sell_amount_raw = self._to_raw(base_received, base_tok)
            quote_back = self._get_amounts_out(
                self.routers[worst_dex], sell_amount_raw, [base_tok, quote_tok])

            if not quote_back or quote_back <= 0:
                continue

            quote_back_human = self._from_raw(quote_back, quote_tok)
            gross_profit = quote_back_human - SCAN_AMOUNT_USD
            estimated_costs = (SCAN_AMOUNT_USD * DEX_FEE_PCT * 2  # 2 swaps
                               + GAS_ESTIMATE_USD
                               + SCAN_AMOUNT_USD * SLIPPAGE_PCT * 2)
            net_profit = gross_profit - estimated_costs

            if net_profit <= 0:
                continue

            # Calculate prices for display
            buy_price = SCAN_AMOUNT_USD / base_received if base_received > 0 else 0
            sell_price = quote_back_human / base_received if base_received > 0 else 0

            confidence = min(95, abs(net_profit / SCAN_AMOUNT_USD * 1000) + 40)

            self._push_opportunity({
                "pair": f"{base_tok}/{quote_tok}",
                "network": "base",
                "style": "inventory",
                "buy_venue": self.routers[best_dex],
                "sell_venue": self.routers[worst_dex],
                "buy_price": round(buy_price, 6),
                "sell_price": round(sell_price, 6),
                "gross_profit": round(gross_profit, 4),
                "estimated_costs": round(estimated_costs, 4),
                "net_profit": round(net_profit, 4),
                "confidence": round(confidence, 1),
                "hops": 2,
            })

    def scan_triangular(self):
        """Check triangular arbitrage within each DEX (A→B→A)."""
        for dex_name, router_addr in self.routers.items():
            for a, b, c in TRIANGULAR_PATHS:
                if a not in TOKENS or b not in TOKENS or c not in TOKENS:
                    continue
                if a != c:
                    continue  # Must be a round trip

                amount_in_raw = self._to_raw(SCAN_AMOUNT_USD, a)

                # Leg 1: A → B
                out_b_raw = self._get_amounts_out(router_addr, amount_in_raw, [a, b])
                if not out_b_raw or out_b_raw <= 0:
                    continue

                # Leg 2: B → A
                out_a_raw = self._get_amounts_out(router_addr, out_b_raw, [b, a])
                if not out_a_raw or out_a_raw <= 0:
                    continue

                amount_back = self._from_raw(out_a_raw, a)
                gross_profit = amount_back - SCAN_AMOUNT_USD
                estimated_costs = (SCAN_AMOUNT_USD * DEX_FEE_PCT * 2
                                   + GAS_ESTIMATE_USD
                                   + SCAN_AMOUNT_USD * SLIPPAGE_PCT * 2)
                net_profit = gross_profit - estimated_costs

                if net_profit <= 0:
                    continue

                base_received = self._from_raw(out_b_raw, b)
                buy_price = SCAN_AMOUNT_USD / base_received if base_received > 0 else 0
                sell_price = amount_back / base_received if base_received > 0 else 0

                confidence = min(90, abs(net_profit / SCAN_AMOUNT_USD * 1000) + 30)

                self._push_opportunity({
                    "pair": f"{a}/{b}",
                    "network": "base",
                    "style": "flash_loan",
                    "buy_venue": f"{dex_name}",
                    "sell_venue": f"{dex_name}",
                    "buy_price": round(buy_price, 6),
                    "sell_price": round(sell_price, 6),
                    "gross_profit": round(gross_profit, 4),
                    "estimated_costs": round(estimated_costs, 4),
                    "net_profit": round(net_profit, 4),
                    "confidence": round(confidence, 1),
                    "hops": 2,
                })

    # ── Main loop ────────────────────────────────────────────────────────────────
    def run(self):
        logger.info("Scanner Bot starting — Base DEX Arbitrage Scanner")
        logger.info("RPC: %s", BASE_RPC_URL)
        logger.info("Dashboard: %s", DASHBOARD_URL)
        logger.info("Routers: %s", list(self.routers.keys()))
        logger.info("Tokens: %s", list(TOKENS.keys()))
        logger.info("Scan pairs: %s", [f"{a}/{b}" for a, b in SCAN_PAIRS])
        logger.info("Scan amount: $%.2f", SCAN_AMOUNT_USD)
        logger.info("Scan interval: %ds", SCAN_INTERVAL)

        if not self.w3.is_connected():
            logger.error("Cannot connect to Base RPC at %s", BASE_RPC_URL)
            self._send_heartbeat("error", "", f"Cannot connect to {BASE_RPC_URL}")
        else:
            chain_id = self.w3.eth.chain_id
            logger.info("Connected to Base — chain ID %d", chain_id)
            self._send_heartbeat("running", "Scanner started")

        while True:
            try:
                if not self.w3.is_connected():
                    logger.warning("RPC disconnected, retrying...")
                    self.w3 = Web3(Web3.HTTPProvider(BASE_RPC_URL))
                    time.sleep(5)
                    continue

                # Read mode from dashboard (determines if we should scan)
                mode = self._read_mode()
                if mode and "base" not in mode.get("unlocked_networks", ["base"]):
                    self.last_action = "Base not unlocked, skipping scan"
                    logger.debug("Base not unlocked, skipping")
                else:
                    self.last_action = f"Scanning {len(self.routers)} DEXes, {len(SCAN_PAIRS)} pairs"
                    self.scan_cross_dex()
                    self.scan_triangular()
                    self.scans_completed += 1
                    logger.info("Scan #%d complete — %d opportunities pushed total",
                                self.scans_completed, self.opportunities_pushed)

                self._send_heartbeat("running", self.last_action)

            except Exception as e:
                logger.error("Scan error: %s", e)
                self._send_heartbeat("error", self.last_action, str(e))

            time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    bot = ScannerBot()
    bot.run()
