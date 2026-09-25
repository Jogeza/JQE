from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import api.service as service_module
import main
from api.service import ApplicationService


@pytest.mark.asyncio
async def test_live_cycle_requires_explicit_confirmation() -> None:
    service = object.__new__(ApplicationService)

    with pytest.raises(ValueError, match="Explicit confirmation"):
        await service.execute_live_cycle(confirmed=False)


@pytest.mark.asyncio
async def test_live_cycle_delegates_to_canonical_main_run(monkeypatch: pytest.MonkeyPatch) -> None:
    service = object.__new__(ApplicationService)
    monkeypatch.setattr(
        service_module,
        "settings",
        SimpleNamespace(effective_broker="mt5", broker_execution_enabled=True),
    )
    run = AsyncMock(
        return_value=main.CycleExecutionResult(
            status="ORDER_ACCEPTED",
            broker="mt5",
            symbol="EURUSD",
            side="BUY",
            order_id="demo-order-1",
            decision_code="ALLOWED",
            reason="Order accepted",
        )
    )
    monkeypatch.setattr(main, "run", run)

    response = await service.execute_live_cycle(confirmed=True)

    run.assert_awaited_once_with()
    assert response.status == "ORDER_ACCEPTED"
    assert response.order_id == "demo-order-1"
    assert response.symbol == "EURUSD"
