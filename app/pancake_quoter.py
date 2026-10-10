"""PancakeSwap Infinity CLQuoter integration for the Base scanner.

Uses the CLQuoter contract to get price quotes from PancakeSwap Infinity
concentrated liquidity pools on Base mainnet. Unlike V2 routers, Infinity
uses a singleton PoolManager with PoolKey-based pools and requires the
CLQuoter's revert-based quoting pattern.
"""
import json
import logging
from web3 import Web3

logger = logging.getLogger("scanner")

# PancakeSwap Infinity contract addresses on Base
CL_POOL_MANAGER = "0xa0FfB9c1CE1Fe56963B0321B32E7A0302114058b"
CL_QUOTER = "0xd0737C9762912dD34c3271197E362Aa736Df0926"

# Common fee tiers (fee in ppm, tickSpacing) to try for each pair.
# PancakeSwap Infinity decouples fee from tickSpacing, but most pools
# follow Uniswap V3-style mappings. Includes tiers seen on actual
# Infinity pools deployed on Base.
FEE_TIERS = [
    (100, 1),       # 0.01% — confirmed on Infinity Base
    (500, 10),      # 0.05% — standard
    (1000, 60),     # 0.10% — confirmed on Infinity Base
    (2500, 50),     # 0.25% — PancakeSwap V3 standard
    (3000, 60),     # 0.30% — Uniswap V3 standard, confirmed on Infinity Base
    (10000, 200),   # 1.00% — standard
]

# ABI for CLQuoter.quoteExactInputSingle
# struct PoolKey { address currency0; address currency1; address hooks;
#                  address poolManager; uint24 fee; bytes32 parameters; }
# struct QuoteExactSingleParams { PoolKey poolKey; bool zeroForOne;
#                                 uint128 exactAmount; bytes hookData; }
CL_QUOTER_ABI = json.loads('''[
  {
    "inputs": [{
      "components": [
        {
          "components": [
            {"name": "currency0", "type": "address"},
            {"name": "currency1", "type": "address"},
            {"name": "hooks", "type": "address"},
            {"name": "poolManager", "type": "address"},
            {"name": "fee", "type": "uint24"},
            {"name": "parameters", "type": "bytes32"}
          ],
          "name": "poolKey",
          "type": "tuple"
        },
        {"name": "zeroForOne", "type": "bool"},
        {"name": "exactAmount", "type": "uint128"},
        {"name": "hookData", "type": "bytes"}
      ],
      "name": "params",
      "type": "tuple"
    }],
    "name": "quoteExactInputSingle",
    "outputs": [
      {"name": "amountOut", "type": "uint256"},
      {"name": "gasEstimate", "type": "uint256"}
    ],
    "stateMutability": "nonpayable",
    "type": "function"
  }
]''')


def _encode_parameters(tick_spacing: int) -> str:
    """Encode tickSpacing into the bytes32 parameters field.

    Layout (from CLPoolParametersHelper):
      bits [0-15]:  hooks registration bitmap (0 = no hooks)
      bits [16-39]: tickSpacing (24 bits)
    """
    return "0x" + format(tick_spacing << 16, "064x")


class PancakeInfinityQuoter:
    """Quotes swaps from PancakeSwap Infinity CL pools on Base."""

    def __init__(self, w3: Web3):
        self.w3 = w3
        self.quoter = w3.eth.contract(
            address=Web3.to_checksum_address(CL_QUOTER),
            abi=CL_QUOTER_ABI,
        )
        self.pool_manager = Web3.to_checksum_address(CL_POOL_MANAGER)

    def _build_pool_key(self, token_in: str, token_out: str,
                        fee: int, tick_spacing: int):
        """Construct a PoolKey and determine swap direction.

        currency0 must be the numerically lower address.
        Returns (pool_key_dict, zero_for_one).
        """
        t0 = Web3.to_checksum_address(token_in)
        t1 = Web3.to_checksum_address(token_out)

        if int(t0, 16) <= int(t1, 16):
            currency0, currency1 = t0, t1
            zero_for_one = True   # currency0 → currency1
        else:
            currency0, currency1 = t1, t0
            zero_for_one = False  # currency1 → currency0

        pool_key = {
            "currency0": currency0,
            "currency1": currency1,
            "hooks": "0x0000000000000000000000000000000000000000",
            "poolManager": self.pool_manager,
            "fee": fee,
            "parameters": _encode_parameters(tick_spacing),
        }
        return pool_key, zero_for_one

    def get_amount_out(self, token_in: str, token_out: str,
                       amount_in: int) -> int | None:
        """Quote a swap, trying multiple fee tiers.

        Returns the output amount (int) or None if no pool exists.
        """
        for fee, tick_spacing in FEE_TIERS:
            pool_key, zero_for_one = self._build_pool_key(
                token_in, token_out, fee, tick_spacing)
            try:
                result = self.quoter.functions.quoteExactInputSingle({
                    "poolKey": pool_key,
                    "zeroForOne": zero_for_one,
                    "exactAmount": amount_in,
                    "hookData": b"",
                }).call()
                amount_out, _gas = result
                if amount_out and amount_out > 0:
                    return amount_out
            except Exception as e:
                logger.debug(
                    "CLQuoter fee=%d ts=%d failed: %s",
                    fee, tick_spacing, str(e)[:120])
                continue
        return None
