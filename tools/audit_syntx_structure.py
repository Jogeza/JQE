"""Offline structural audit of cached Weltrade SyntX datasets.

Read-only: opens data/historical.sqlite3 in read-only mode, never connects to a
terminal, never writes state. Reports data integrity plus market-structure
metrics per instrument/timeframe so the durable watchlist can be narrowed to
datasets JQE can actually work with.

Structure metrics are descriptive. They do not demonstrate positive expectancy;
use tools/weltrade_scope_backtest.py with explicit costs for that.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

TIMEFRAME_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}

VOLATILITY_FAMILY = ("FX VOL", "SFX VOL")
JUMP_FAMILY = ("PAINX", "MAX PAINX")


@dataclass
class DatasetAudit:
    provider: str
    symbol: str
    timeframe: str
    bars: int
    first_utc: str
    last_utc: str
    span_hours: float
    expected_bars: int
    coverage_pct: float
    duplicate_timestamps: int
    out_of_order: int
    non_positive_volume: int
    non_positive_range: int


@dataclass
class StructureAudit:
    symbol: str
    timeframe: str
    family: str
    atr_pct_mean: float
    atr_pct_p95: float
    daily_vol_pct: float
    er_20: float
    er_100: float
    acf_1: float
    acf_5: float
    variance_ratio_10: float
    hurst_rs: float
    excess_kurtosis: float
    max_abs_return_pct: float
    share_bars_over_3sigma_pct: float
    share_bars_over_5sigma_pct: float
    body_to_range: float
    direction_balance: float


def _family(symbol: str) -> str:
    upper = symbol.upper()
    if upper.startswith(JUMP_FAMILY):
        return "jump"
    if upper.startswith(VOLATILITY_FAMILY):
        return "volatility"
    return "other"


def load_datasets(db: Path, provider: str) -> list[tuple[str, str, int]]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT symbol, timeframe, COUNT(*) FROM candles WHERE provider = ? GROUP BY symbol, timeframe",
            (provider,),
        ).fetchall()
    finally:
        con.close()
    return [(str(s), str(t), int(c)) for s, t, c in rows]


def load_candles(db: Path, provider: str, symbol: str, timeframe: str) -> pd.DataFrame:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        frame = pd.read_sql_query(
            "SELECT time, open, high, low, close, volume FROM candles "
            "WHERE provider = ? AND symbol = ? AND timeframe = ? ORDER BY time",
            con,
            params=(provider, symbol, timeframe),
        )
    finally:
        con.close()
    return frame


def _utc(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def audit_integrity(frame: pd.DataFrame, provider: str, symbol: str, timeframe: str) -> DatasetAudit:
    step = TIMEFRAME_SECONDS[timeframe]
    times = frame["time"].to_numpy(dtype=float)
    span = float(times[-1] - times[0]) if len(times) > 1 else 0.0
    expected = int(span // step) + 1 if span > 0 else len(times)
    duplicates = int(len(times) - len(np.unique(times)))
    out_of_order = int(np.sum(np.diff(times) < 0))
    body_high_low = (frame["high"] - frame["low"]).to_numpy(dtype=float)
    return DatasetAudit(
        provider=provider,
        symbol=symbol,
        timeframe=timeframe,
        bars=int(len(frame)),
        first_utc=_utc(times[0]),
        last_utc=_utc(times[-1]),
        span_hours=round(span / 3600.0, 2),
        expected_bars=expected,
        coverage_pct=round(100.0 * len(times) / expected, 2) if expected else 0.0,
        duplicate_timestamps=duplicates,
        out_of_order=out_of_order,
        non_positive_volume=int(np.sum(frame["volume"].to_numpy(dtype=float) <= 0)),
        non_positive_range=int(np.sum(body_high_low <= 0)),
    )


def _efficiency_ratio(close: np.ndarray, window: int) -> float:
    if len(close) <= window:
        return float("nan")
    change = np.abs(close[window:] - close[:-window])
    path = np.array([np.sum(np.abs(np.diff(close[i : i + window + 1]))) for i in range(len(close) - window)])
    valid = path > 0
    if not np.any(valid):
        return float("nan")
    return float(np.mean(change[valid] / path[valid]))


def _acf(returns: np.ndarray, lag: int) -> float:
    if len(returns) <= lag + 2:
        return float("nan")
    a = returns[:-lag]
    b = returns[lag:]
    if np.std(a) == 0 or np.std(b) == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def _variance_ratio(returns: np.ndarray, q: int) -> float:
    if len(returns) <= q * 3:
        return float("nan")
    var1 = np.var(returns, ddof=1)
    if var1 <= 0:
        return float("nan")
    grouped = returns[: (len(returns) // q) * q].reshape(-1, q).sum(axis=1)
    varq = np.var(grouped, ddof=1)
    return float(varq / (q * var1))


def _hurst_rs(close: np.ndarray, min_chunk: int = 16) -> float:
    series = close[: (len(close) // min_chunk) * min_chunk]
    if len(series) < min_chunk * 2:
        return float("nan")
    ns: list[int] = []
    rs_values: list[float] = []
    for size in (min_chunk, min_chunk * 2, min_chunk * 4, min_chunk * 8):
        if size > len(series):
            continue
        chunks = series[: (len(series) // size) * size].reshape(-1, size)
        if chunks.shape[0] < 2:
            continue
        observed: list[float] = []
        for chunk in chunks:
            dev = chunk - np.mean(chunk)
            cumulative = np.cumsum(dev)
            r = float(np.max(cumulative) - np.min(cumulative))
            s = float(np.std(chunk, ddof=1))
            if s > 0 and r > 0:
                observed.append(r / s)
        if observed:
            ns.append(size)
            rs_values.append(float(np.mean(observed)))
    if len(ns) < 2:
        return float("nan")
    slope = float(np.polyfit(np.log(ns), np.log(rs_values), 1)[0])
    return round(slope, 3)


def audit_structure(frame: pd.DataFrame, symbol: str, timeframe: str) -> StructureAudit:
    close = frame["close"].to_numpy(dtype=float)
    high = frame["high"].to_numpy(dtype=float)
    low = frame["low"].to_numpy(dtype=float)
    open_ = frame["open"].to_numpy(dtype=float)
    returns = np.diff(np.log(close))
    returns = returns[np.isfinite(returns)]
    previous_close = close[:-1]
    true_range = np.maximum.reduce([
        high[1:] - low[1:],
        np.abs(high[1:] - previous_close),
        np.abs(low[1:] - previous_close),
    ])
    atr_pct = 100.0 * true_range / previous_close
    sigma = float(np.std(returns, ddof=1)) if len(returns) > 2 else float("nan")
    abs_returns = np.abs(returns)
    bars_per_day = 86400.0 / TIMEFRAME_SECONDS[timeframe]
    rng = high - low
    valid_rng = rng > 0
    return StructureAudit(
        symbol=symbol,
        timeframe=timeframe,
        family=_family(symbol),
        atr_pct_mean=round(float(np.mean(atr_pct)), 4) if len(atr_pct) else float("nan"),
        atr_pct_p95=round(float(np.percentile(atr_pct, 95)), 4) if len(atr_pct) else float("nan"),
        daily_vol_pct=round(float(sigma * np.sqrt(bars_per_day) * 100.0), 3),
        er_20=round(_efficiency_ratio(close, 20), 4),
        er_100=round(_efficiency_ratio(close, 100), 4),
        acf_1=round(_acf(returns, 1), 4),
        acf_5=round(_acf(returns, 5), 4),
        variance_ratio_10=round(_variance_ratio(returns, 10), 4),
        hurst_rs=_hurst_rs(close),
        excess_kurtosis=round(float(pd.Series(returns).kurt()), 3),
        max_abs_return_pct=round(float(np.max(abs_returns) * 100.0), 4) if len(abs_returns) else float("nan"),
        share_bars_over_3sigma_pct=round(float(np.mean(abs_returns > 3 * sigma) * 100.0), 4) if sigma else float("nan"),
        share_bars_over_5sigma_pct=round(float(np.mean(abs_returns > 5 * sigma) * 100.0), 4) if sigma else float("nan"),
        body_to_range=round(float(np.mean(np.abs(close[1:] - open_[1:]) / rng[1:][valid_rng[1:]])) if np.any(valid_rng[1:]) else float("nan"), 4),
        direction_balance=round(float(np.mean(np.sign(np.diff(close)))), 4),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/historical.sqlite3")
    parser.add_argument("--provider", default="weltrade")
    parser.add_argument("--timeframes", default="M1,M5")
    parser.add_argument("--min-bars", type=int, default=200)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args()

    db = Path(args.db)
    if not db.exists():
        raise SystemExit(f"Cached store not found: {db}")
    timeframes = [t.strip().upper() for t in args.timeframes.split(",") if t.strip()]

    integrity: list[dict] = []
    structure: list[dict] = []
    for symbol, timeframe, bars in load_datasets(db, args.provider):
        if timeframe not in timeframes or bars < args.min_bars:
            continue
        frame = load_candles(db, args.provider, symbol, timeframe)
        if len(frame) < args.min_bars:
            continue
        integrity.append(asdict(audit_integrity(frame, args.provider, symbol, timeframe)))
        structure.append(asdict(audit_structure(frame, symbol, timeframe)))

    if args.json:
        print(json.dumps({"integrity": integrity, "structure": structure}, indent=2))
        return

    integrity.sort(key=lambda r: (r["symbol"], r["timeframe"]))
    structure.sort(key=lambda r: (r["symbol"], r["timeframe"]))
    print(f"Cached {args.provider} datasets audited: {len(integrity)}")
    print("\n== Integrity ==")
    header = f"{'symbol':<18}{'tf':<5}{'bars':>7}{'span_h':>9}{'cov%':>8}{'dup':>5}{'ooo':>5}{'vol<=0':>8}{'range<=0':>9}  first..last"
    print(header)
    for row in integrity:
        print(
            f"{row['symbol']:<18}{row['timeframe']:<5}{row['bars']:>7}{row['span_hours']:>9.1f}"
            f"{row['coverage_pct']:>8.1f}{row['duplicate_timestamps']:>5}{row['out_of_order']:>5}"
            f"{row['non_positive_volume']:>8}{row['non_positive_range']:>9}  {row['first_utc']}..{row['last_utc']}"
        )
    print("\n== Structure ==")
    print(
        f"{'symbol':<18}{'tf':<5}{'fam':<11}{'ATR%':>7}{'ATR95':>7}{'dVol%':>7}"
        f"{'ER20':>7}{'ER100':>7}{'ACF1':>7}{'VR10':>7}{'Hurst':>7}{'kurt':>7}{'maxR%':>7}{'3s%':>7}{'body':>6}"
    )
    for row in structure:
        print(
            f"{row['symbol']:<18}{row['timeframe']:<5}{row['family']:<11}"
            f"{row['atr_pct_mean']:>7.3f}{row['atr_pct_p95']:>7.3f}{row['daily_vol_pct']:>7.2f}"
            f"{row['er_20']:>7.3f}{row['er_100']:>7.3f}{row['acf_1']:>7.3f}"
            f"{row['variance_ratio_10']:>7.3f}{row['hurst_rs']:>7.3f}{row['excess_kurtosis']:>7.2f}"
            f"{row['max_abs_return_pct']:>7.3f}{row['share_bars_over_3sigma_pct']:>7.3f}{row['body_to_range']:>6.3f}"
        )


if __name__ == "__main__":
    main()
