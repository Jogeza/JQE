"""Live MT5 broker-diagnostic tests.

QUARANTINE — these tests require a real MT5 terminal and real credentials.

They are **disabled by default** and MUST NOT run during ordinary CI or
developer test runs.  The gate is evaluated before any broker contact.

Opt-in explicitly:

    JQE_RUN_LIVE_MT5_TESTS=1 pytest tests/test_mt5_connection_live.py

Any other value (absent, empty, "0", "false", …) keeps the tests skipped.
"""

from __future__ import annotations

import os

import pytest

# ---------------------------------------------------------------------------
# Fail-closed gate — evaluated at collection time, before any MT5 contact.
# ---------------------------------------------------------------------------

_LIVE_MT5_ENABLED: bool = os.environ.get("JQE_RUN_LIVE_MT5_TESTS", "") == "1"

_skip_unless_live = pytest.mark.skipif(
    not _LIVE_MT5_ENABLED,
    reason=(
        "Live MT5 diagnostics are disabled by default. "
        "Set JQE_RUN_LIVE_MT5_TESTS=1 to opt in."
    ),
)


# ---------------------------------------------------------------------------
# Live diagnostic — only reachable when gate is explicitly opened.
# ---------------------------------------------------------------------------


@_skip_unless_live
def test_mt5_connection() -> None:
    """Verify a real MT5 terminal accepts initialize() and exposes account info."""
    import MetaTrader5 as mt5  # noqa: PLC0415 — import inside opt-in guard

    connected = mt5.initialize()
    assert connected is True, "MT5 connection failed"

    account = mt5.account_info()
    assert account is not None

    print(account)

    mt5.shutdown()