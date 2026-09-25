"""Run one fresh, simulation-only JQE paper cycle and print its audit trail."""

from __future__ import annotations

import asyncio
import json

from api.service import ApplicationService
from broker.simulation_gateway import SimulationGateway
from config.settings import settings


async def run() -> dict[str, object]:
    if settings.broker_execution_enabled:
        raise RuntimeError("operational paper cycle requires broker execution disabled")

    gateway = SimulationGateway(starting_balance=settings.account_balance)
    service = ApplicationService(gateway=gateway, market_data_source=gateway)
    analysis = await service.get_active_market_analysis(
        settings.default_symbol, settings.default_timeframe, settings.default_candle_count
    )
    outcome = await service.execute_market_setup(analysis.setup.setup_id)
    monitoring = service.get_offline_monitoring()

    return {
        "mode": "SIMULATION_ONLY",
        "gateway_class": type(gateway).__name__,
        "gateway_account": "SIMULATED",
        "broker_execution_enabled": settings.broker_execution_enabled,
        "market_data": {
            "source": analysis.context.data_source,
            "status": analysis.candles.market_data_status,
            "latest_closed_candle": analysis.setup.candle_close_time.isoformat(),
            "freshness": analysis.setup.data_freshness.status,
        },
        "signal": {
            "direction": analysis.signal.signal,
            "confidence": analysis.signal.confidence,
            "setup_state": analysis.setup.setup_state,
        },
        "risk": analysis.setup.risk_authorization.model_dump(mode="json"),
        "policy": analysis.setup.execution_authorization.model_dump(mode="json"),
        "paper_outcome": outcome.model_dump(mode="json"),
        "api_projection": {
            "mode": monitoring.mode,
            "open_paper_positions": monitoring.open_paper_positions,
            "latest_paper_outcome": (
                monitoring.latest_paper_outcome.model_dump(mode="json")
                if monitoring.latest_paper_outcome else None
            ),
            "research_status": monitoring.research_status,
        },
    }


def main() -> int:
    print(json.dumps(asyncio.run(run()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
