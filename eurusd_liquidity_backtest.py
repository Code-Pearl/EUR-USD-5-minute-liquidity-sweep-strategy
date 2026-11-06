#!/usr/bin/env python3
"""
EUR/USD PDH/PDL liquidity-sweep backtest.
Data: Dukascopy EURUSD 1-minute BID and ASK candles, aggregated to 5-minute.
All timestamps are UTC internally; London session uses Europe/London DST rules.

Install:
    pip install pandas numpy matplotlib
    npm install -g dukascopy-node

Download:
    python eurusd_liquidity_backtest.py --download --start 2020-01-01 --end 2026-11-06

Backtest existing data:
    python eurusd_liquidity_backtest.py --data-dir data --start 2020-01-01 --end 2026-11-06

This is research code, not a trading recommendation. Inspect data quality and
validate fills with your own broker before relying on results.
"""
from __future__ import annotations
import argparse
import glob
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PIP = 0.0001
NY_TZ = "America/New_York"
LONDON_TZ = "Europe/London"


def ensure_python_package(import_name: str, package_name: str | None = None) -> None:
    """Install a missing dependency into the exact Python running this script."""
    import importlib.util
    if importlib.util.find_spec(import_name) is None:
        package_name = package_name or import_name
        print(f"Installing missing Python package: {package_name}", flush=True)
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", package_name],
            check=True,
        )


def download_dukas_m1(start: str, end: str, data_dir: Path) -> None:
    """
    Download EURUSD M1 BID and ASK candles using the pure-Python
    dukascopy-downloader package. No Node.js, npm or npx required.
    """
    ensure_python_package("dukascopy_downloader", "dukascopy-downloader")
    from dukascopy_downloader import Downloader, load

    data_dir.mkdir(parents=True, exist_ok=True)
    print(f"Downloading EURUSD M1 BID + ASK from Dukascopy: {start} to {end}", flush=True)
    print("First download can take several minutes. Existing downloaded data is resumable.", flush=True)

    downloader = Downloader(str(data_dir))
    downloader.download(
        ["EURUSD"], tf="m1", start=start, end=end, sides="both"
    )

    # Export a predictable CSV layout for the backtester.
    for side in ("BID", "ASK"):
        print(f"Preparing {side} candles...", flush=True)
        df = load(
            str(data_dir), "EUR-USD", "m1",
            start=start, end=end, side=side,
        )
        if df is None or len(df) == 0:
            raise RuntimeError(f"Dukascopy returned no {side} EURUSD candles for {start} to {end}.")
        df = df.copy()
        if "time" in df.columns:
            times = pd.to_datetime(df.pop("time"), utc=True)
        elif isinstance(df.index, pd.DatetimeIndex):
            times = pd.to_datetime(df.index, utc=True)
        else:
            raise ValueError(f"Unexpected Dukascopy {side} data format: {list(df.columns)}")
        df.index = times
        df.index.name = "timestamp"
        required = ["open", "high", "low", "close"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"Dukascopy {side} data missing columns: {missing}")
        target = data_dir / "raw" / side.lower() / f"eurusd_{side.lower()}.csv"
        target.parent.mkdir(parents=True, exist_ok=True)
        export = df[required].copy()
        export.insert(0, "timestamp", (export.index.astype("int64") // 1_000_000))
        export.to_csv(target, index=False)
        print(f"Saved {len(export):,} {side} rows: {target}", flush=True)

    print("Dukascopy download and export complete.", flush=True)


def read_side(data_dir: Path, side: str) -> pd.DataFrame:
    files = glob.glob(str(data_dir / "raw" / side / "**" / "*.csv"), recursive=True)
    if not files:
        # Also allow manually supplied consolidated files.
        files = glob.glob(str(data_dir / f"eurusd_{side}*.csv"))
    if not files:
        raise FileNotFoundError(
            f"No {side.upper()} CSV files found under {data_dir}. "
            "Run with --download or place Dukascopy CSVs in data/raw/{bid,ask}/."
        )
    frames = []
    for f in files:
        d = pd.read_csv(f)
        d.columns = [str(c).strip().lower() for c in d.columns]
        time_col = "timestamp" if "timestamp" in d.columns else ("time" if "time" in d.columns else None)
        if time_col is None:
            raise ValueError(f"{f}: expected timestamp/time column; got {list(d.columns)}")
        # Dukascopy exports timestamps as Unix milliseconds; also accept ISO timestamps.
        ts = pd.to_numeric(d[time_col], errors="coerce")
        if ts.notna().mean() > 0.95:
            d.index = pd.to_datetime(ts, unit="ms", utc=True)
        else:
            d.index = pd.to_datetime(d[time_col], utc=True)
        for c in ("open", "high", "low", "close"):
            if c not in d:
                raise ValueError(f"{f}: missing {c}")
            d[c] = pd.to_numeric(d[c], errors="coerce")
        frames.append(d[["open", "high", "low", "close"]])
    result = pd.concat(frames).sort_index()
    result = result[~result.index.duplicated(keep="last")]
    result = result.dropna()
    result.columns = [f"{c}_{side}" for c in result.columns]
    return result


def load_data(data_dir: Path) -> pd.DataFrame:
    bid = read_side(data_dir, "bid")
    ask = read_side(data_dir, "ask")
    x = bid.join(ask, how="inner").sort_index()
    if x.empty:
        raise ValueError("BID and ASK files have no overlapping timestamps.")
    # Mid is used only to calculate reference levels and candle structure.
    for c in ("open", "high", "low", "close"):
        x[f"{c}_mid"] = (x[f"{c}_bid"] + x[f"{c}_ask"]) / 2
    # Basic data-quality checks.
    x = x[~x.index.duplicated(keep="last")]
    x = x[(x["high_bid"] >= x["low_bid"]) & (x["high_ask"] >= x["low_ask"])]
    return x


def resample_ohlc(df: pd.DataFrame, rule: str = "5min") -> pd.DataFrame:
    agg = {}
    for side in ("bid", "ask", "mid"):
        agg.update({
            f"open_{side}": "first", f"high_{side}": "max",
            f"low_{side}": "min", f"close_{side}": "last",
        })
    return df.resample(rule, label="left", closed="left").agg(agg).dropna()


def add_htf_levels(m1: pd.DataFrame) -> pd.DataFrame:
    """Previous completed FX day/week using 17:00 New York rollover."""
    x = m1.copy()
    ny = x.index.tz_convert(NY_TZ)
    # Shift clock by 17h so each synthetic FX day starts at 17:00 NY.
    shifted = (ny - pd.Timedelta(hours=17)).tz_localize(None)
    day_key = shifted.normalize()
    daily = x.groupby(day_key).agg(
        day_high=("high_mid", "max"), day_low=("low_mid", "min")
    )
    daily["pdh"] = daily["day_high"].shift(1)
    daily["pdl"] = daily["day_low"].shift(1)
    x["fx_day"] = day_key
    x["pdh"] = x["fx_day"].map(daily["pdh"])
    x["pdl"] = x["fx_day"].map(daily["pdl"])

    week_key = shifted.to_period("W-FRI")
    weekly = x.groupby(week_key).agg(
        week_high=("high_mid", "max"), week_low=("low_mid", "min")
    )
    weekly["pwh"] = weekly["week_high"].shift(1)
    weekly["pwl"] = weekly["week_low"].shift(1)
    x["fx_week"] = week_key
    x["pwh"] = x["fx_week"].map(weekly["pwh"])
    x["pwl"] = x["fx_week"].map(weekly["pwl"])
    return x


def add_confirmed_swings(m5: pd.DataFrame, left: int = 2, right: int = 2) -> pd.DataFrame:
    """A pivot at i-right becomes usable only at bar i (no look-ahead)."""
    x = m5.copy()
    highs = x["high_mid"].to_numpy()
    lows = x["low_mid"].to_numpy()
    last_hi = np.full(len(x), np.nan)
    last_lo = np.full(len(x), np.nan)
    cur_hi = cur_lo = np.nan
    for i in range(len(x)):
        p = i - right
        if p >= left:
            hwin = highs[p-left:p+right+1]
            lwin = lows[p-left:p+right+1]
            if highs[p] == np.max(hwin) and np.sum(hwin == highs[p]) == 1:
                cur_hi = highs[p]
            if lows[p] == np.min(lwin) and np.sum(lwin == lows[p]) == 1:
                cur_lo = lows[p]
        last_hi[i], last_lo[i] = cur_hi, cur_lo
    x["last_swing_high"] = last_hi
    x["last_swing_low"] = last_lo
    return x


def london_mask(index: pd.DatetimeIndex) -> np.ndarray:
    local = index.tz_convert(LONDON_TZ)
    mins = local.hour * 60 + local.minute
    return (mins >= 8 * 60) & (mins < 10 * 60)


def make_signals(m5: pd.DataFrame, max_confirm_bars: int = 6,
                 sweep_buffer_pips: float = 0.2) -> pd.DataFrame:
    """
    Sweep candle: penetrates PDH/PDL by buffer and closes back inside.
    Confirmation: later 5m close breaks the latest confirmed opposing pivot.
    Entry is next 5m bar open. Sweep-to-MSS window is capped.
    """
    x = add_confirmed_swings(m5)
    n = len(x)
    sig = np.zeros(n, dtype=int)  # +1 long, -1 short
    sweep_extreme = np.full(n, np.nan)
    active = None
    active_age = 0
    active_extreme = np.nan
    active_structure_level = np.nan
    active_day = None
    idx = x.index
    in_london = london_mask(idx)
    for i in range(n):
        row = x.iloc[i]
        day = row.get("fx_day", None)
        if not in_london[i] or pd.isna(row["pdh"]) or pd.isna(row["pdl"]):
            active = None
            continue
        if active_day != day:
            active = None
            active_day = day
        if active is None:
            if (row["high_mid"] >= row["pdh"] + sweep_buffer_pips * PIP
                    and row["close_mid"] < row["pdh"]
                    and pd.notna(row["last_swing_low"])):
                active, active_age, active_extreme = "short", 0, row["high_mid"]
                # Freeze the pre-confirmation structure level at the sweep.
                active_structure_level = row["last_swing_low"]
            elif (row["low_mid"] <= row["pdl"] - sweep_buffer_pips * PIP
                    and row["close_mid"] > row["pdl"]
                    and pd.notna(row["last_swing_high"])):
                active, active_age, active_extreme = "long", 0, row["low_mid"]
                active_structure_level = row["last_swing_high"]
        else:
            active_age += 1
            if active == "short":
                active_extreme = max(active_extreme, row["high_mid"])
                pivot = active_structure_level
                if pd.notna(pivot) and row["close_mid"] < pivot:
                    if i + 1 < n:
                        sig[i + 1] = -1
                        sweep_extreme[i + 1] = active_extreme
                    active = None
            else:
                active_extreme = min(active_extreme, row["low_mid"])
                pivot = active_structure_level
                if pd.notna(pivot) and row["close_mid"] > pivot:
                    if i + 1 < n:
                        sig[i + 1] = 1
                        sweep_extreme[i + 1] = active_extreme
                    active = None
            if active is not None and active_age > max_confirm_bars:
                active = None
    x["signal"] = sig
    x["sweep_extreme"] = sweep_extreme
    return x


def simulate(m1: pd.DataFrame, m5: pd.DataFrame, initial_equity: float = 400.0,
             risk_pct: float = 0.01, rr: float = 2.0,
             target_mode: str = "fixed_rr", max_trades_per_day: int = 1,
             stop_buffer_pips: float = 0.5, commission_per_100k_roundturn: float = 0.0):
    """Minute-bar execution; conservative stop-first rule if stop and target hit in same minute."""
    trades = []
    equity = initial_equity
    daily_count = {}
    m5 = make_signals(m5)
    for i, row in m5[m5["signal"] != 0].iterrows():
        side = int(row["signal"])
        # A confirmation on the final 5m candle must not create a 10:00 entry.
        local_entry = i.tz_convert(LONDON_TZ)
        if not (local_entry.hour * 60 + local_entry.minute < 10 * 60):
            continue
        day = row["fx_day"]
        if daily_count.get(day, 0) >= max_trades_per_day:
            continue
        # Entry at next 5m bar's opening minute, on executable side.
        entry_time = i
        if entry_time not in m1.index:
            continue
        if side == 1:
            entry = float(m1.loc[entry_time, "open_ask"])
            stop = float(row["sweep_extreme"]) - stop_buffer_pips * PIP
            risk_dist = entry - stop
            target = entry + rr * risk_dist if target_mode == "fixed_rr" else float(row["pdh"])
            # For longs, opposing liquidity is PDH.
            if target_mode == "opposing_level":
                target = float(row["pdh"])
            if risk_dist <= 0 or target <= entry:
                continue
        else:
            entry = float(m1.loc[entry_time, "open_bid"])
            stop = float(row["sweep_extreme"]) + stop_buffer_pips * PIP
            risk_dist = stop - entry
            target = entry - rr * risk_dist if target_mode == "fixed_rr" else float(row["pdl"])
            # For shorts, opposing liquidity is PDL.
            if target_mode == "opposing_level":
                target = float(row["pdl"])
            if risk_dist <= 0 or target >= entry:
                continue
        risk_cash = equity * risk_pct
        units = risk_cash / risk_dist  # EUR units; EURUSD quote currency is USD.
        start_pos = m1.index.get_indexer([entry_time])[0]
        if start_pos < 0:
            continue
        exit_price = None
        exit_time = None
        exit_reason = None
        # Hold no longer than end of London session; never carry into next session.
        local_day = entry_time.tz_convert(LONDON_TZ).date()
        future = m1.iloc[start_pos:]
        future_local = future.index.tz_convert(LONDON_TZ)
        for t, bar in future.iterrows():
            if t != entry_time and t.tz_convert(LONDON_TZ).date() != local_day:
                break
            if (t.tz_convert(LONDON_TZ).hour * 60 + t.tz_convert(LONDON_TZ).minute) >= 10 * 60:
                break
            if side == 1:
                stop_hit = bar["low_bid"] <= stop
                target_hit = bar["high_bid"] >= target
                if stop_hit:
                    exit_price, exit_time, exit_reason = stop, t, "stop"
                    break
                if target_hit:
                    exit_price, exit_time, exit_reason = target, t, "target"
                    break
            else:
                stop_hit = bar["high_ask"] >= stop
                target_hit = bar["low_ask"] <= target
                if stop_hit:
                    exit_price, exit_time, exit_reason = stop, t, "stop"
                    break
                if target_hit:
                    exit_price, exit_time, exit_reason = target, t, "target"
                    break
        if exit_price is None:
            last_t = future.index[-1]
            # If data ends or session ends, close at last executable close.
            if side == 1:
                exit_price = float(future.iloc[-1]["close_bid"])
            else:
                exit_price = float(future.iloc[-1]["close_ask"])
            exit_time, exit_reason = last_t, "session_close"
        gross = (exit_price - entry) * units * side
        commission = (units / 100000.0) * commission_per_100k_roundturn
        net = gross - commission
        equity += net
        daily_count[day] = daily_count.get(day, 0) + 1
        trades.append({
            "entry_time_utc": entry_time, "exit_time_utc": exit_time,
            "direction": "LONG" if side == 1 else "SHORT",
            "entry": entry, "stop": stop, "target": target, "exit": exit_price,
            "units": units, "risk_cash": risk_cash, "gross_pnl": gross,
            "commission": commission, "net_pnl": net, "equity_after": equity,
            "R_multiple": net / risk_cash if risk_cash else np.nan,
            "exit_reason": exit_reason, "target_mode": target_mode,
        })
    return pd.DataFrame(trades)


def report(trades: pd.DataFrame, initial_equity: float, outdir: Path):
    outdir.mkdir(parents=True, exist_ok=True)
    trades.to_csv(outdir / "trades.csv", index=False)
    if trades.empty:
        summary = {"trades": 0, "message": "No qualifying trades. Check data range and rules."}
    else:
        wins = trades[trades.net_pnl > 0]
        losses = trades[trades.net_pnl <= 0]
        gross_profit = wins.net_pnl.sum()
        gross_loss = abs(losses.net_pnl.sum())
        eq = pd.concat([pd.Series([initial_equity]), initial_equity + trades.net_pnl.cumsum()], ignore_index=True)
        dd = (eq / eq.cummax() - 1).min()
        summary = {
            "trades": int(len(trades)),
            "win_rate_pct": round(100 * len(wins) / len(trades), 2),
            "net_profit": round(float(trades.net_pnl.sum()), 2),
            "ending_equity": round(float(initial_equity + trades.net_pnl.sum()), 2),
            "return_pct": round(100 * (float(initial_equity + trades.net_pnl.sum()) / initial_equity - 1), 2),
            "profit_factor": round(float(gross_profit / gross_loss), 3) if gross_loss else None,
            "expectancy_R": round(float(trades.R_multiple.mean()), 4),
            "average_R": round(float(trades.R_multiple.mean()), 4),
            "max_drawdown_pct": round(100 * float(dd), 2),
            "avg_win": round(float(wins.net_pnl.mean()), 2) if len(wins) else 0,
            "avg_loss": round(float(losses.net_pnl.mean()), 2) if len(losses) else 0,
        }
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


def main():
    # Double-clicking the .py with no arguments performs the full workflow.
    launched_without_args = len(sys.argv) == 1
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true",
                    help="Download missing/selected Dukascopy data before backtesting.")
    ap.add_argument("--no-download", action="store_true",
                    help="Use existing local CSV data only.")
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default=pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d"))
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--out", default="results")
    ap.add_argument("--initial-equity", type=float, default=400.0)
    ap.add_argument("--risk-pct", type=float, default=0.01)
    ap.add_argument("--rr", type=float, default=2.0)
    ap.add_argument("--target-mode", choices=["fixed_rr", "opposing_level"], default="fixed_rr")
    ap.add_argument("--commission-per-100k-roundturn", type=float, default=0.0)
    args = ap.parse_args()

    # Install core Python dependencies automatically if this is a fresh machine.
    ensure_python_package("pandas")
    ensure_python_package("numpy")

    data_dir = Path(args.data_dir)
    bid_files = glob.glob(str(data_dir / "raw" / "bid" / "*.csv"))
    ask_files = glob.glob(str(data_dir / "raw" / "ask" / "*.csv"))
    need_download = args.download or (
        not args.no_download and (not bid_files or not ask_files)
    )

    if need_download:
        download_dukas_m1(args.start, args.end, data_dir)

    print("\\nLoading BID/ASK data...", flush=True)
    m1 = load_data(data_dir)
    m1 = m1.loc[args.start:args.end]
    if m1.empty:
        raise RuntimeError("No EURUSD data in the requested date range after loading.")
    print(f"Loaded {len(m1):,} overlapping M1 bars: {m1.index.min()} -> {m1.index.max()}", flush=True)

    m1 = add_htf_levels(m1)
    m5 = resample_ohlc(m1)
    levels = m1[["pdh", "pdl", "pwh", "pwl", "fx_day", "fx_week"]].resample("5min").first()
    m5 = m5.join(levels)
    print("Running 5-minute liquidity sweep backtest...", flush=True)
    trades = simulate(
        m1, m5, initial_equity=args.initial_equity, risk_pct=args.risk_pct,
        rr=args.rr, target_mode=args.target_mode,
        commission_per_100k_roundturn=args.commission_per_100k_roundturn,
    )
    report(trades, args.initial_equity, Path(args.out))
    print(f"\\nFinished. Results are in: {Path(args.out).resolve()}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\\nERROR: {exc}", flush=True)
        print("\\nIf this window was opened by double-clicking, press Enter to close.", flush=True)
        try:
            input()
        except EOFError:
            pass
        raise