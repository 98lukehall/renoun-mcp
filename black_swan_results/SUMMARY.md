# ReNoUn Black Swan Validation Report

Generated: 2026-03-08 21:29 UTC

## Summary Table

| Event | Asset | DD Unmanaged | DD Managed | Reduction | Early Warning (hours) | Pre-Crash Constellation | Result |
|-------|-------|-------------|------------|-----------|----------------------|------------------------|--------|
| COVID Crash | BTCUSDT | -54.6% | -18.4% | +36.2 pp | 290h | CONVERGENCE -> DIP_AND_RECOVERY -> PATTERN_BREAK | PASS |
| COVID Crash | ETHUSDT | -60.9% | -27.3% | +33.7 pp | 218h | CONVERGENCE -> SURFACE_VARIATION -> PATTERN_BREAK | PASS |
| China Ban | BTCUSDT | -45.8% | -31.0% | +14.8 pp | 445h | CLOSED_LOOP -> CONVERGENCE -> DIP_AND_RECOVERY | PARTIAL |
| China Ban | ETHUSDT | -60.3% | -42.9% | +17.4 pp | 272h | DIP_AND_RECOVERY -> CONVERGENCE -> DIP_AND_RECOVERY | PASS |
| LUNA Collapse | BTCUSDT | -36.6% | -18.5% | +18.1 pp | 396h | DIP_AND_RECOVERY -> PATTERN_BREAK -> DIP_AND_RECOVERY | PASS |
| LUNA Collapse | ETHUSDT | -41.6% | -16.0% | +25.6 pp | 191h | PATTERN_BREAK -> DIP_AND_RECOVERY -> PATTERN_BREAK | PASS |
| FTX Collapse | BTCUSDT | -27.0% | -11.0% | +16.0 pp | 345h | DIP_AND_RECOVERY -> CONVERGENCE -> PATTERN_BREAK | PASS |
| FTX Collapse | ETHUSDT | -34.8% | -15.3% | +19.5 pp | 125h | CONVERGENCE -> DIP_AND_RECOVERY -> PATTERN_BREAK | PASS |

## Key Findings

### BTC Performance

- 4/4 events showed early warning (exposure < 0.5 before worst hour)
- Average DD reduction: +21.3 pp (BTC only)
- Average early warning: 369 hours
- Events with protective exposure (avg < 0.5 during worst 24h): 3/4
- Full PASS: 3/4, PARTIAL: 1/4
- The crash regime flag improved multi-wave crash handling

### ETH Performance

- Average DD reduction: +24.1 pp
- Average early warning: 202 hours
- Full PASS: 4/4, PARTIAL: 0/4

### Combined (All Assets)

- Average DD reduction across all assets: +22.7 pp
- Full PASS: 7/8, PARTIAL: 1/8

### Per-Event DD Reduction Detail

- **COVID Crash (BTC):** +36.2 pp (unmanaged -54.6% -> managed -18.4%)
- **COVID Crash (ETH):** +33.7 pp (unmanaged -60.9% -> managed -27.3%)
- **China Ban (BTC):** +14.8 pp (unmanaged -45.8% -> managed -31.0%)
- **China Ban (ETH):** +17.4 pp (unmanaged -60.3% -> managed -42.9%)
- **LUNA Collapse (BTC):** +18.1 pp (unmanaged -36.6% -> managed -18.5%)
- **LUNA Collapse (ETH):** +25.6 pp (unmanaged -41.6% -> managed -16.0%)
- **FTX Collapse (BTC):** +16.0 pp (unmanaged -27.0% -> managed -11.0%)
- **FTX Collapse (ETH):** +19.5 pp (unmanaged -34.8% -> managed -15.3%)

## Methodology

- Rolling window analysis with 50-candle windows, 5-candle rebalance steps
- v2 exposure engine with asymmetric EMA smoothing + constellation persistence
- Crash regime flag active (suppresses false DIP_AND_RECOVERY during multi-wave events)
- Early warning = hours between first exposure < 0.5 and worst single-hour drawdown
- DD reduction = |unmanaged max DD| - |managed max DD| in percentage points
- Verdict criteria: PASS = early warning > 0h AND DD reduction > 0pp AND avg exposure < 0.5 during worst 24h

## Engine Details

- **Engine:** ReNoUn Finance v2 (17-channel structural analysis)
- **Patent:** Pending #63/923,592
- **Exposure mapping:** DHS-tiered base + constellation mods + stress signals
- **Smoothing:** Asymmetric EMA (alpha_down=0.6, alpha_up=0.3)
- **Floor:** 0.20 (never fully flat)
- **Crash regime penalty:** 0.5x exposure multiplier during multi-wave crash suppression