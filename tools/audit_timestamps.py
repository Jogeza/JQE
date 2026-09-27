"""Forensic audit of Weltrade research timestamps across MT5, SQLite, bundles, and experiments."""
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def audit():
    con = sqlite3.connect("data/historical.sqlite3")
    cur = con.cursor()
    
    symbols = cur.execute(
        "SELECT DISTINCT symbol FROM candles WHERE provider='weltrade' ORDER BY symbol"
    ).fetchall()
    symbols = [s[0] for s in symbols]
    print(f"=== AUDITING {len(symbols)} WELTRADE SYMBOLS IN SQLite ===")
    
    for symbol in symbols:
        for tf_str in ["M1", "M5"]:
            rows = cur.execute(
                "SELECT time, open, high, low, close, volume FROM candles "
                "WHERE symbol=? AND timeframe=? AND provider='weltrade' ORDER BY time ASC",
                (symbol, tf_str),
            ).fetchall()
            
            if not rows:
                print(f"[MISSING] {symbol} {tf_str}")
                continue
                
            expected_step = 60 if tf_str == "M1" else 300
            timestamps = [r[0] for r in rows]
            
            # Check strictly increasing
            strictly_increasing = all(b > a for a, b in zip(timestamps, timestamps[1:]))
            
            # Check diffs
            diffs = [b - a for a, b in zip(timestamps, timestamps[1:])]
            
            first_dt = datetime.fromtimestamp(timestamps[0], tz=timezone.utc)
            last_dt = datetime.fromtimestamp(timestamps[-1], tz=timezone.utc)
            
            gaps = [(i, timestamps[i], timestamps[i+1], diff) for i, diff in enumerate(diffs) if diff != expected_step]
            
            # Check 300th candle (train end if 500 candles total and 60% train)
            train_end_idx = int(len(timestamps) * 0.6) - 1
            train_start_dt = first_dt
            train_end_dt = datetime.fromtimestamp(timestamps[train_end_idx], tz=timezone.utc)
            
            print(f"{symbol:16} {tf_str:2} | Count: {len(rows):4} | StrictlyIncr: {strictly_increasing} | "
                  f"Range: {first_dt.isoformat()} -> {last_dt.isoformat()} | "
                  f"Train (idx 0..{train_end_idx}): {train_start_dt.isoformat()} -> {train_end_dt.isoformat()} | "
                  f"Gaps: {len(gaps)}")
            
            if gaps:
                for idx, t1, t2, diff in gaps:
                    dt1 = datetime.fromtimestamp(t1, tz=timezone.utc)
                    dt2 = datetime.fromtimestamp(t2, tz=timezone.utc)
                    print(f"    GAP at row {idx}: {dt1.isoformat()} -> {dt2.isoformat()} (jump: {diff}s = {diff/60:.1f}m = {diff/3600:.2f}h)")

if __name__ == "__main__":
    audit()
