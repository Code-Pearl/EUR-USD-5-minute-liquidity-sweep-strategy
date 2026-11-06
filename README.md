# EUR/USD 5-minute liquidity sweep strategy | backtest specification
## interpretation by CODE__PEARL 
![result.png]{result.png}

Yes. The idea is to turn the trading approach in your text and screenshot into a proper, rules-based Python backtest using real EUR/USD price data.

I would not simply code an indicator that identifies candles above and below yesterday's high and low. That would test something much weaker than the strategy being described.

The central hypothesis is:

Price sweeps a significant higher-timeframe liquidity level, fails to hold beyond it, confirms a reversal on the 5-minute chart, and then moves towards liquidity on the opposite side.

The important distinction is that we enter after the sweep and confirmation, not when price first touches or breaks the level.

## 1. What I can extract from the material

There are five liquidity references:

| Level       | Meaning                                      | Timeframe      |
| ----------- | -------------------------------------------- | -------------- |
| PDH         | Previous Day High                            | Daily          |
| PDL         | Previous Day Low                             | Daily          |
| PWH         | Previous Week High                           | Weekly         |
| PWL         | Previous Week Low                            | Weekly         |
| Session H/L | High and Low of a trading session            | Intraday       |
| Equal H/L   | Two or more highs/lows around the same price | 5m / higher TF |

The main setup is PDH/PDL. The other levels provide context and can be tested separately.

The screenshot also appears to show structural annotations such as AR-H, AR-L and MSS, with a marked risk/reward position. I would treat those as visual clues, not assume their precise definitions without testing them.

## 2. Data source: I would use Dukascopy, not Yahoo Finance

For this particular experiment, I would use Dukascopy historical data.

| Source           | Assessment                                                                                       |
| ---------------- | ------------------------------------------------------------------------------------------------ |
| Yahoo Finance    | Useful for quick experiments, but 5-minute history is restricted to approximately 60 days.       |
| Dukascopy        | Better choice for multi-year FX research; provides historical minute, five-minute and tick data. |
| Broker tick data | Best for validating execution against the actual broker you intend to trade with.                |

Dukascopy provides EUR/USD historical candles and bid/ask prices. Its data can be downloaded and processed locally in Python.



Historical Price Data+3



My proposed approach:

- Download EUR/USD 1-minute BID and ASK candles.
- Construct 5-minute candles from the minute data.
- Calculate daily and weekly liquidity levels independently.
- Use 1-minute candles to simulate trade execution.
- Use bid/ask prices to account for the spread.
- Avoid assuming that a trade won just because its target was touched somewhere inside a 5-minute candle.

This is important. A backtest that uses only 5-minute OHLC data can produce misleading results when a stop and target are both touched in the same candle.

## 3. Turning the strategy into mechanical rules

I would start with one primary strategy, rather than combine every liquidity concept into one complicated system.

Primary setup: PDH / PDL sweep and reversal

[Trading With Price Action: The Ultimate Forex Trading Guide](https://images.openai.com/static-rsc-4/6yevu9YF4B2ZvpOot8wgqzSw2NIOn5UhbuUPtFzGtBsFd31tW1pIV_pl8Xu0aJZFhAC_EeK4KnWOZyd_2R2iZ4G6gPKXvZYGkqweKT4OaJ-JmvPdaLlTTeK5KQkN6paBIwTPbhDyfYeNmUrZ-X2KIla9lqHicf9Q6yYWaVRb2HQ?purpose=inline)

[holoforex.com](https://www.holoforex.com/blogs/trading-with-price-action?utm_source=chatgpt.com)

1. Mark the higher-timeframe levels

   Calculate previous day's high and low, plus previous week's high and low.
2. Wait for a liquidity sweep

   Short setup: price trades above PDH. Long setup: price trades below PDL.
3. Wait for price to reclaim the level

   Short: a completed 5-minute candle closes back below PDH.

   Long: a completed 5-minute candle closes back above PDL.
4. Wait for market structure shift (MSS)

   Short: price breaks the most recent confirmed 5-minute swing low.

   Long: price breaks the most recent confirmed 5-minute swing high.
5. Enter after confirmation

   Enter at the next available 5-minute candle open, with execution on the appropriate bid/ask side.
6. Set stop and target

   Stop: beyond the extreme of the sweep.

   Target: test both a fixed risk/reward target and the opposing liquidity level.

### Trading constraints

- Instrument: EUR/USD.
- Execution timeframe: 5 minutes.
- Confirmation timeframe: 5 minutes.
- Main liquidity timeframe: daily.
- Additional context: weekly and intraday levels.
- Trading session: 08:00–10:00 London local time.
- Maximum: one trade per London session.
- Risk: 1% of current account equity.
- Initial account: $400, matching the example in the material.
- No entry without a complete setup.

One important definition: I would use the New York 17:00 FX rollover to construct previous trading-day levels, rather than blindly using midnight UTC. London session times will automatically account for daylight-saving changes.

## 4. What I have built

EUR/USD Liquidity Backtest Package

Created

Includes the Python backtester and its documentation.

&#x20;Download complete package

Python backtester

eurusd_liquidity_backtest.py

Download

Strategy documentation

EURUSD_Liquidity_Backtest_Documentation.md

Download

## 5. How to run it

You'll need Python and Node.js installed.

Install Python dependencies:

```
pip install pandas numpy
```

Download historical data and run the backtest:

```
python eurusd_liquidity_backtest.py --download --start 2020-01-01 --end 2026-11-06
```

It will download BID and ASK data, construct the 5-minute candles and run the strategy.

The output will include:

| Output           | What it tells you             |
| ---------------- | ----------------------------- |
| trades.csv       | Every individual trade        |
| summary.json     | Overall performance           |
| Win rate         | Percentage of winning trades  |
| Profit factor    | Gross profits / gross losses  |
| Expectancy       | Average return per trade in R |
| Maximum drawdown | Largest equity decline        |
| Ending equity    | Growth from initial $400      |

You can also change the target to the opposing liquidity level:

```
python eurusd_liquidity_backtest.py --target-mode opposing_level
```



Important

&#x20;I have created and syntax-checked the backtesting code, but have not downloaded the historical dataset or executed the historical test. Therefore, I am not presenting invented performance figures as actual results.



## 6. What I would investigate next

I would eventually run these as separate experiments:

| Experiment | Hypothesis                                               |
| ---------- | -------------------------------------------------------- |
| A          | PDH/PDL sweep + MSS                                      |
| B          | PDH/PDL sweep + candle reclaim only                      |
| C          | Sweep + MSS + weekly level confluence                    |
| D          | Asian session high/low sweep + MSS                       |
| E          | Equal highs/lows sweep + MSS                             |
| F          | Sweep + MSS with 1R, 1.5R, 2R and opposing-level targets |

One detail worth investigating: the screenshot appears to show AR-H and AR-L, which could mean Asian Range High and Asian Range Low. That is potentially a different setup from the PDH/PDL strategy described in the text. I have deliberately kept those separate rather than mixing them into the first backtest.

My recommendation is to establish whether the basic PDH/PDL approach has positive expectancy first. Then test the additional liquidity concepts to see whether they genuinely improve performance after spread and execution costs.

The objective isn't to prove that this trader's strategy works. It's to find out whether the underlying trading idea has a statistically meaningful edge on EUR/USD.
