# Feasibility Report

Decision: **inconclusive**

## Observed

- Trades: 4
- Baseline mean points (`spread_plus_slippage`): -1169.43
- Stress mean points: -1428.68
- Positive month ratio: 0.00%
- Max month PnL share: 86.74%

## Gate Checks

- trade_count_ok: FAIL
- baseline_expectancy_ok: FAIL
- stress_expectancy_ok: FAIL
- positive_month_ratio_ok: FAIL
- month_concentration_ok: FAIL

## Thresholds

- min_trades_required: 40
- min_baseline_expectancy_points: 0.0
- min_stress_expectancy_points: -250.0
- min_positive_month_ratio: 0.5
- max_month_pnl_share: 0.7

## Scenario Summary

- gross: trades=4 | mean=-132.45 pts | median=-74.46 | win_rate=0.00% | total=-529.79
- spread_only: trades=4 | mean=-1169.43 pts | median=-1096.19 | win_rate=0.00% | total=-4677.73
- spread_plus_slippage: trades=4 | mean=-1169.43 pts | median=-1096.19 | win_rate=0.00% | total=-4677.73
- stress: trades=4 | mean=-1428.68 pts | median=-1351.62 | win_rate=0.00% | total=-5714.72

## Baseline By Symbol

- Boom 1000 Index: trades=2 | mean=-1757.81 | median=-1757.81 | total=-3515.62
- Crash 1000 Index: trades=2 | mean=-581.05 | median=-581.05 | total=-1162.11