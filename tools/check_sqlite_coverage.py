"""Quick check of SQLite candle timestamp coverage for weltrade provider."""
import sqlite3
import datetime
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "historical.sqlite3"

if not DB.exists():
    print(f"No database at {DB}")
    sys.exit(1)

con = sqlite3.connect(str(DB))
cur = con.cursor()

rows = cur.execute(
    "SELECT symbol, timeframe, MIN(time), MAX(time), COUNT(*) "
    "FROM candles WHERE provider='weltrade' GROUP BY symbol, timeframe "
    "ORDER BY symbol, timeframe"
).fetchall()

now_utc = datetime.datetime.now(tz=datetime.timezone.utc)
print(f"Current system UTC: {now_utc.isoformat()}")
print(f"Current local time (system): {datetime.datetime.now().isoformat()}")
print()
print(f"{'Symbol':22} {'TF':3} | {'Bars':>5} | {'Min timestamp (as UTC)':30} | Max timestamp (as UTC)")
print("-" * 110)
for row in rows:
    sym, tf, mn, mx, cnt = row
    mn_dt = datetime.datetime.fromtimestamp(mn, tz=datetime.timezone.utc)
    mx_dt = datetime.datetime.fromtimestamp(mx, tz=datetime.timezone.utc)
    print(f"{sym:22} {tf:3} | {cnt:5} | {mn_dt.isoformat():30} | {mx_dt.isoformat()}")

con.close()
