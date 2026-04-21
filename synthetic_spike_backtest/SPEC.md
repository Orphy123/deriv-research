# Synthetic Spike Strategy Specification (V1)

This document freezes the first executable specification for backtesting.
Any future rule changes should create a new version tag (V1.1, V2, etc).

## 1) Scope

- Instruments:
  - `Boom 1000 Index`
  - `Crash 1000 Index`
- Data source: tick data with `time_utc`, `bid`, optional `ask`.
- Backtest objective: evaluate feasibility of an opposite-move trigger strategy
  with strict timing and immediate adverse exits.

## 2) Direction Model

- Normal flow direction:
  - Boom 1000 -> `LONG`
  - Crash 1000 -> `SHORT`
- Opposite move trigger:
  - Boom trigger event: downward move beyond threshold.
  - Crash trigger event: upward move beyond threshold.

## 3) Trigger Definition

- Let `delta_price = bid[t] - bid[t-1]`.
- Let `point` be instrument point size from manifest.
- Convert threshold in points to price:
  - `threshold_price = trigger_opposite_threshold_points * point`
- Trigger condition:
  - Boom: `delta_price <= -threshold_price`
  - Crash: `delta_price >= +threshold_price`

## 4) Watch Window Logic

- On each trigger event, start (or reset) a watch window.
- Watch duration: `watch_minutes` (default `10`).
- Watch remains valid only if no new opposite trigger occurs before window end.
- Operationally this means a trade is allowed only after a continuous quiet
  period of `watch_minutes` since the latest opposite trigger.

## 5) Entry Rule

- Entry event time is the first tick at or after:
  - `latest_trigger_time + watch_minutes`
- Optional offset:
  - move forward by `entry_offset_ticks` ticks (default `0`).
- Trade side:
  - Boom -> BUY
  - Crash -> SELL

## 6) Exit Rules

Exit precedence:

1. **Adverse tick exit (primary)**
   - Long: first tick where `bid[t] < bid[t-1]`
   - Short: first tick where `ask[t] > ask[t-1]` (or synthetic ask if missing)
2. **Time exit (fallback)**
   - Force-close at first tick at/after `entry_time + max_hold_minutes`
   - Default `max_hold_minutes = 15`
3. **Data end exit**
   - If dataset ends before the above, close at final available tick.

## 7) Cost Scenarios

Each trade is evaluated in three cost modes:

- `spread_only`: spread applied through bid/ask execution prices.
- `spread_plus_slippage`: spread + fixed slippage points per side.
- `stress`: spread multiplier + slippage multiplier.

Gross PnL uses mid-price movement (no costs) for comparability.

## 8) Timing + Ordering Guarantees

- Timestamps are UTC and sorted ascending.
- If multiple triggers occur, the latest one defines the current watch state.
- If adverse and timeout could occur within the same latency-adjusted slice,
  whichever event time is earlier wins.
- Latency is modeled as execution delay in milliseconds before the order is
  considered filled/closed.

## 9) Feasibility Gates (Backtest Decision)

The strategy is considered `proceed_to_demo_bot` only if all pass:

- Sufficient sample size (`min_trades_required`).
- Positive mean net expectancy in baseline scenario.
- Stress scenario does not collapse below configured threshold.
- Monthly stability condition passes (not concentrated in one month).

Otherwise result is `stop_and_revise` or `inconclusive`.

## 10) Explicit Non-Goals For V1

- Portfolio/margin simulation across multiple simultaneous positions.
- Market impact modeling.
- Dynamic regime filter integration.
- Live execution code (kept separate until feasibility passes).
