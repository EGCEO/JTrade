export interface ScoreInput {
  netProfit: bigint // in token decimals (or wei)
  netProfitUsd: number // for easier thresholds
  gasCostUsd: number
  hops: number
  priceImpactBps: number // e.g. 30 = 0.30%
  slippageBps: number
  liquidityScore: number // 0 to 1 (1 = very deep)
  recentSuccessRate?: number // 0 to 1 (optional)
}

export interface ScoreResult {
  netProfitUsd: number
  executionProbability: number
  expectedValueUsd: number
  finalScore: number // = expectedValueUsd
  approved: boolean
}

export interface ScoreConfig {
  minNetProfitUsd: number
  minExpectedValueUsd: number
  minExecutionProbability: number
  /** Fraction of gas lost on failure: 1 = public mempool, 0 = private relay / no-revert bundles */
  failureGasFraction: number
  /** p *= exp(-gasK * gasCost/profit). 1.8 ≈ 0.4x at ratio 0.5 */
  gasK: number
  /** p *= hopDecay^(hops-1) */
  hopDecay: number
  /** p *= exp(-impactK * (impactBps + slippageBps)). 0.009 ≈ 0.4x at 100 bps */
  impactK: number
  /** Floor for liquidity multiplier (0 = zero liquidity gives zero probability) */
  liquidityFloor: number
  /** Weight of historical success rate: p *= (1 - w) + w * rate */
  successRateWeight: number
}

export const DEFAULT_SCORE_CONFIG: ScoreConfig = {
  minNetProfitUsd: 0.75,
  minExpectedValueUsd: 0.5,
  minExecutionProbability: 0.35,
  failureGasFraction: 1,
  gasK: 1.8,
  hopDecay: 0.85,
  impactK: 0.009,
  liquidityFloor: 0,
  successRateWeight: 0.5,
}

const clamp01 = (x: number): number => Math.max(0, Math.min(1, x))

/** Returns x if finite, otherwise the fallback */
const finiteOr = (x: number, fallback: number): number =>
  Number.isFinite(x) ? x : fallback

const REJECTED: ScoreResult = {
  netProfitUsd: 0,
  executionProbability: 0,
  expectedValueUsd: 0,
  finalScore: 0,
  approved: false,
}

/**
 * Execution probability (0 to 1) using smooth penalties (no tier cliffs).
 *
 * NOTE: if netProfitUsd already comes from a simulation that includes price
 * impact and slippage, set impactK low (or 0) to avoid double counting, and
 * keep this term for risk the sim can't see (latency, competition, state change).
 */
function calculateExecutionProbability(input: ScoreInput, cfg: ScoreConfig): number {
  const profit = input.netProfitUsd
  const gas = input.gasCostUsd

  if (!Number.isFinite(profit) || !Number.isFinite(gas) || profit <= 0 || gas < 0) {
    return 0
  }

  let p = 1

  // 1. Gas relative to profit
  p *= Math.exp(-cfg.gasK * (gas / profit))

  // 2. Hops (1 hop = no penalty)
  const hops = Math.max(1, finiteOr(input.hops, 1))
  p *= Math.pow(cfg.hopDecay, hops - 1)

  // 3. Price impact + slippage
  const totalImpactBps = Math.max(
    0,
    finiteOr(input.priceImpactBps, 0) + finiteOr(input.slippageBps, 0),
  )
  p *= Math.exp(-cfg.impactK * totalImpactBps)

  // 4. Liquidity (non-finite treated as no liquidity)
  const liq = clamp01(finiteOr(input.liquidityScore, 0))
  p *= Math.max(cfg.liquidityFloor, liq)

  // 5. Historical success rate (if available and valid)
  if (input.recentSuccessRate !== undefined && Number.isFinite(input.recentSuccessRate)) {
    const rate = clamp01(input.recentSuccessRate)
    p *= 1 - cfg.successRateWeight + cfg.successRateWeight * rate
  }

  return clamp01(p)
}

/**
 * Main scoring function.
 * Expected value = p * netProfit - (1 - p) * gasCost * failureGasFraction
 * Final score = expected value (rank opportunities by this).
 */
export function calculateScore(
  input: ScoreInput,
  overrides: Partial<ScoreConfig> = {},
): ScoreResult {
  const cfg: ScoreConfig = { ...DEFAULT_SCORE_CONFIG, ...overrides }

  const p = calculateExecutionProbability(input, cfg)
  if (p === 0) {
    return { ...REJECTED, netProfitUsd: finiteOr(input.netProfitUsd, 0) }
  }

  const profit = input.netProfitUsd
  const failureCost = input.gasCostUsd * cfg.failureGasFraction
  const ev = p * profit - (1 - p) * failureCost

  const approved =
    input.netProfit > 0n &&
    profit >= cfg.minNetProfitUsd &&
    p >= cfg.minExecutionProbability &&
    ev >= cfg.minExpectedValueUsd

  return {
    netProfitUsd: profit,
    executionProbability: p,
    expectedValueUsd: ev,
    finalScore: ev,
    approved,
  }
}
