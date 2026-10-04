"""Append-only decision evidence; no strategy, broker or execution authority."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3


class DecisionJournal:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("""CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY, observed_at TEXT NOT NULL,
                symbol TEXT NOT NULL, timeframe TEXT NOT NULL,
                stage TEXT NOT NULL, payload TEXT NOT NULL)""")

    def append(self, *, symbol, timeframe, stage, facts):
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute("INSERT INTO decisions(observed_at,symbol,timeframe,stage,payload) VALUES(?,?,?,?,?)",
                       (datetime.now(timezone.utc).isoformat(), symbol, timeframe, stage,
                        json.dumps(facts, allow_nan=False, default=str)))


def read_journal(path, *, limit=100, symbol=None):
    """Missing evidence stays unavailable; reads never create or migrate stores."""
    path = Path(path).resolve()
    if not path.is_file():
        return {"state": "UNAVAILABLE", "items": []}
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT * FROM decisions WHERE (? IS NULL OR upper(symbol)=upper(?)) ORDER BY id DESC LIMIT ?",
            (symbol, symbol, min(max(limit, 1), 500)),
        ).fetchall()
    return {"state": "OBSERVED", "items": [
        {"id": row["id"], "observed_at": row["observed_at"], "symbol": row["symbol"],
         "timeframe": row["timeframe"], "stage": row["stage"], "facts": json.loads(row["payload"])}
        for row in rows
    ]}
