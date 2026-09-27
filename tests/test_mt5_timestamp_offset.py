"""Regression tests for the MT5 server UTC+3 timestamp offset correction.

Weltrade's MT5 server reports bar timestamps in server-local time (UTC+3).
Before the fix (2026-09-27) the gateway stored these raw values treating them
as UTC, producing candles whose times were 3 hours ahead of UTC.

Kept separate from test_mt5_gateway.py so the CRLF/LF line-ending mix in that
file does not complicate replacement.  Both files exercise the same gateway.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from broker.mt5_gateway import (
    MT5Gateway,
    _MT5_SERVER_UTC_OFFSET_SECONDS,
    _mt5_ts_to_utc,
)
from broker.types import Timeframe
from tests.mt5_stubs import configure_sdk


@pytest.fixture
def gateway() -> MT5Gateway:
    return MT5Gateway()


class TestMT5TimestampUTCOffset:
    """Regression tests for MT5 server-time -> UTC conversion.

    Three invariants that must hold after the fix:
    1. _mt5_ts_to_utc subtracts exactly _MT5_SERVER_UTC_OFFSET_SECONDS.
    2. Both get_candles code paths (copy_rates_from_pos and copy_rates_from) use
       the helper so their Candle.time values are corrected.
    3. No cached weltrade candle has a timestamp in the future (offline check).
    """

    # --- Unit tests for the helper function ---

    def test_helper_subtracts_offset(self) -> None:
        """_mt5_ts_to_utc must subtract exactly 3 h from the raw server epoch."""
        raw_server_ts = 1_700_000_000  # arbitrary realistic value
        expected_utc = datetime.fromtimestamp(
            raw_server_ts - _MT5_SERVER_UTC_OFFSET_SECONDS, tz=timezone.utc
        )
        assert _mt5_ts_to_utc(raw_server_ts) == expected_utc

    def test_offset_constant_is_three_hours(self) -> None:
        """Constant must be exactly 10 800 s (3 h)."""
        assert _MT5_SERVER_UTC_OFFSET_SECONDS == 3 * 3600

    def test_helper_result_is_utc_aware(self) -> None:
        """Returned datetime must be timezone-aware with UTC tzinfo."""
        result = _mt5_ts_to_utc(1_700_000_000)
        assert result.tzinfo is timezone.utc

    def test_corrected_time_is_earlier_than_raw_utc(self) -> None:
        """Applying the offset must shift the time 3 h into the past."""
        raw_ts = 1_750_000_000
        corrected = _mt5_ts_to_utc(raw_ts)
        raw_as_utc = datetime.fromtimestamp(raw_ts, tz=timezone.utc)
        diff = (raw_as_utc - corrected).total_seconds()
        assert diff == _MT5_SERVER_UTC_OFFSET_SECONDS

    # --- Integration: gateway uses the helper ---

    @patch("broker.mt5_gateway.mt5")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_get_candles_pos_applies_utc_offset(
        self, mock_connect: MagicMock, mock_mt5: MagicMock, gateway: MT5Gateway
    ) -> None:
        """get_candles (copy_rates_from_pos path) applies the UTC offset."""
        configure_sdk(mock_mt5)
        await gateway.connect()
        gateway._resolve_symbol = MagicMock(return_value="FX Vol 20")
        mock_mt5.TIMEFRAME_M1 = 1

        raw_ts = 1_800_000_000
        mock_mt5.copy_rates_from_pos.return_value = [
            {"time": raw_ts, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05,
             "tick_volume": 42}
        ]

        candles = await gateway.get_candles("FX Vol 20", Timeframe.M1, 1)
        expected_utc = datetime.fromtimestamp(
            raw_ts - _MT5_SERVER_UTC_OFFSET_SECONDS, tz=timezone.utc
        )
        assert candles[0].time == expected_utc
        # Must NOT equal raw ts naively treated as UTC (pre-fix behaviour)
        assert candles[0].time < datetime.fromtimestamp(raw_ts, tz=timezone.utc)

    @patch("broker.mt5_gateway.mt5")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_get_candles_with_end_applies_utc_offset(
        self, mock_connect: MagicMock, mock_mt5: MagicMock, gateway: MT5Gateway
    ) -> None:
        """get_candles (copy_rates_from path) also applies the UTC offset."""
        configure_sdk(mock_mt5)
        await gateway.connect()
        gateway._resolve_symbol = MagicMock(return_value="FX Vol 40")
        mock_mt5.TIMEFRAME_M5 = 5

        raw_ts = 1_800_010_000
        mock_mt5.copy_rates_from.return_value = [
            {"time": raw_ts, "open": 2.0, "high": 2.5, "low": 1.8, "close": 2.2,
             "tick_volume": 7}
        ]

        end = datetime(2027, 1, 1, tzinfo=timezone.utc)
        candles = await gateway.get_candles("FX Vol 40", Timeframe.M5, 1, end=end)
        expected_utc = datetime.fromtimestamp(
            raw_ts - _MT5_SERVER_UTC_OFFSET_SECONDS, tz=timezone.utc
        )
        assert candles[0].time == expected_utc
        assert candles[0].time < datetime.fromtimestamp(raw_ts, tz=timezone.utc)

    # --- Offline database check ---

    def test_stored_timestamps_do_not_exceed_now(self) -> None:
        """Regression: after the offset fix, no stored weltrade candle should
        have a timestamp in the future.  Offline structural check; skips if
        the local SQLite cache is absent (CI environments)."""
        import sqlite3
        from pathlib import Path

        db = Path("data/historical.sqlite3")
        if not db.exists():
            pytest.skip("No local SQLite cache present — skipping offline check")

        now_utc = datetime.now(tz=timezone.utc)
        con = sqlite3.connect(str(db))
        rows = con.execute(
            "SELECT symbol, timeframe, MAX(time) FROM candles "
            "WHERE provider='weltrade' GROUP BY symbol, timeframe"
        ).fetchall()
        con.close()

        if not rows:
            pytest.skip("No weltrade candles in cache — skipping")

        future_rows = [
            (sym, tf, datetime.fromtimestamp(mx, tz=timezone.utc))
            for sym, tf, mx in rows
            if mx is not None
            and datetime.fromtimestamp(mx, tz=timezone.utc) > now_utc
        ]
        assert future_rows == [], (
            f"{len(future_rows)} weltrade series have max timestamps in the future: "
            + "; ".join(f"{s} {t} @ {d.isoformat()}" for s, t, d in future_rows)
        )
