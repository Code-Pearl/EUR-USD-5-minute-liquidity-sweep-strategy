# EUR/USD 5-minute PDH/PDL liquidity sweep backtest

## Purpose

This project converts the supplied trading description into a falsifiable strategy test. It does **not** assume the social-media claims (including account growth or win rate) are true.

The primary hypothesis:

> During the London 08:00–10:00 window, when EUR/USD sweeps the previous FX day's high or low, reclaims the level, and then breaks a confirmed 5-minute swing in the opposite direction, does entering after confirmation produce positive expectancy?

## Why Dukascopy M1 BID + ASK, rather than Yahoo 5m

Yahoo Finance intraday history is limited to roughly the most recent 60 days. Dukascopy provides historical FX minute/five-minute bars and bid/ask data. The script downloads M1 BID and ASK bars, aggregates the 5-minute signal chart, and uses M1 bars for exits. This reduces (but does not eliminate) intrabar ambiguity.

Data vendor/source differences remain: Dukascopy is not necessarily the same quote stream as your retail broker. For final validation, repeat with your broker's historical bid/ask data.

## Exact baseline rules

### Market and time
- Instrument: EUR/USD.
- Signal chart: 5-minute OHLC.
- Execution/exit simulation: 1-minute OHLC.
- London session: 08:00 inclusive to 10:00 exclusive, `Europe/London` timezone (DST-aware).
- FX trading-day boundary: 17:00 `America/New_York` (DST-aware).
- At most one trade per FX day / London session.
- Initial equity: USD 400.
- Risk sizing: 1% of current equity per trade.

### Levels
- PDH / PDL: highest high / lowest low of the previous completed FX trading day.
- PWH / PWL: highest high / lowest low of the previous completed FX trading week. Calculated and retained as contextual fields, but **not used as entry triggers in the baseline**.
- Session highs/lows and equal highs/lows are deliberately excluded from the first test. They are separate hypotheses and should not be mixed into the baseline.

### Short setup
1. During London session, a 5m candle's high trades at least 0.2 pip above PDH.
2. That same candle closes below PDH (sweep and reclaim).
3. Within the next six 5m bars, a candle closes below the latest confirmed 5m swing low.
4. Swing pivots use two bars to the left and two bars to the right. A pivot only becomes available after the two right-side bars have closed; no future data is used at decision time.
5. Enter short at the next 5m bar open, executed at the BID open.
6. Stop is 0.5 pip above the highest price reached from the sweep through confirmation.
7. Position size is calculated so stop distance risks 1% of current USD equity.

### Long setup
Exact mirror:
1. 5m low trades at least 0.2 pip below PDL.
2. Same candle closes above PDL.
3. Within six 5m bars, a candle closes above the latest confirmed 5m swing high.
4. Enter next 5m bar open at ASK.
5. Stop is 0.5 pip below the lowest price reached from sweep through confirmation.

### Exit and target variants
Run both separately; do not blend their results:
- `fixed_rr`: default 2R target.
- `opposing_level`: long target = PDH; short target = PDL.

Stops/targets are checked against executable quotes:
- Long stop/target checks use BID low/high.
- Short stop/target checks use ASK high/low.
- If stop and target are both touched in the same M1 candle, the script assumes the stop happened first (conservative).
- If neither is touched by 10:00 London, the trade is closed at the last available executable close before the session ends.

## Data download and run

Requirements:
- Python 3.10+
- Internet connection for the first data download.
- No Node.js, npm or npx required. The script installs its Python dependencies automatically.

**Easiest Windows use:** double-click `RUN_EURUSD_BACKTEST.bat`. It runs the Python file, downloads BID/ASK data if missing, then starts the backtest. The window stays open so you can read any error.

You can also double-click `eurusd_liquidity_backtest.py`. With no command-line arguments it automatically downloads missing data (default start: 2020-01-01) and runs the test.

Manual command:
```bash
python eurusd_liquidity_backtest.py
```

To explicitly download/update the requested range:
```bash
python eurusd_liquidity_backtest.py --download --start 2020-01-01 --end 2026-11-06
```

The downloader uses the Python `dukascopy-downloader` package, which stores resumable BID/ASK minute candles locally. No separate Node.js installation is needed.

Alternative target:
```bash
python eurusd_liquidity_backtest.py --start 2020-01-01 --end 2026-11-06 --target-mode opposing_level
```

Change assumptions:
```bash
python eurusd_liquidity_backtest.py --risk-pct 0.005 --rr 1.5
```

The CLI creates:
- `results/trades.csv` — one row per trade, with entry, stop, target, exit, units, P&L, R multiple and exit reason.
- `results/summary.json` — trade count, win rate, net profit, ending equity, profit factor, expectancy and drawdown.

The downloader stores raw data under `data/raw/bid/` and `data/raw/ask/`.

## Critical validation checklist

Before interpreting results:
1. Check that BID and ASK timestamps overlap and there are no unexplained missing periods.
2. Confirm downloaded CSV schema and timezone; Dukascopy timestamps are Unix milliseconds in UTC.
3. Inspect several randomly selected days against a chart from the same feed.
4. Confirm the 17:00 New York rollover matches the daily candles you intend to trade.
5. Run the backtest with at least 3–5 years, not just a few weeks.
6. Include realistic commission and slippage. The script supports a round-turn commission input per 100,000 EUR units; slippage should be tested separately by worsening fills.
7. Repeat with a second broker/data feed.
8. Split results into chronological in-sample and out-of-sample periods. Do not optimize thresholds on the full history and then report that same history as proof.
9. Report results by year, long vs short, PDH vs PDL, month, and session. A positive total can hide regime dependence.
10. Compare against a simple baseline and randomised entry controls.

## Known limitations / things to improve before live use

- Dukascopy M1 OHLC is not tick-by-tick execution. Same-minute stop/target ambiguity is conservatively resolved stop-first, but gaps and exact order sequencing are not reconstructed.
- The sweep definition is intentionally strict: sweep and reclaim must occur in the same 5m candle. Later reclaim variants should be separate experiments.
- The baseline does not require weekly level confluence. PWH/PWL are calculated but not used as filters.
- The code does not yet implement equal highs/lows, Asian range, session range, order blocks, fair value gaps, or discretionary chart interpretation.
- The screenshot labels are not sufficiently legible to identify every annotation confidently. Do not assume "AR-H/AR-L" mean PDH/PDL; they may refer to a range high/low.
- No model can infer actual resting liquidity from OHLC candles. "Liquidity" here means observable reference levels that may have stop/entry orders around them.

## What would count as evidence?

Do not judge the system by win rate alone. Focus on:
- expectancy in R per trade after costs;
- profit factor after costs;
- maximum drawdown;
- number of trades (sample size);
- stability across years and market regimes;
- out-of-sample performance;
- sensitivity to spread/slippage and small parameter changes.

A strategy with a 40% win rate can be profitable if average wins are sufficiently larger than losses. Conversely, a high win rate can lose money if losses are much larger.
