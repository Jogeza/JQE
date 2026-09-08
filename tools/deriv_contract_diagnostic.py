"""Non-mutating by default; bounded DEMO read/proposal with --demo-network."""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
from typing import Any, Mapping

from broker.deriv_auth import DerivAuthConfig, DerivPATOTPSession, DerivPATOTPTransport
from broker.deriv_contract_spec import (
    current_deriv_multiplier_specification,
    evaluate_deriv_quantity_capability,
)
from broker.deriv_demo_proposal import discover_demo_proposal
from config.settings import Settings
from data.market_observation import provider_symbol_for


class SequentialSocketTransport:
    """Single-session request/response transport with no mutation methods."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection
        self._ids = itertools.count(1)

    async def request(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        request_id = next(self._ids)
        body = dict(payload)
        body["req_id"] = request_id
        await self._connection.send(json.dumps(body))
        while True:
            response = json.loads(await self._connection.recv())
            if response.get("req_id") == request_id:
                if response.get("error"):
                    raise RuntimeError("Deriv diagnostic request rejected")
                return response


async def run_demo_network() -> int:
    settings = Settings()
    if (
        settings.deriv_expected_environment != "demo"
        or not settings.deriv_options_account_id
        or not settings.deriv_api_token
    ):
        print("DEMO_IDENTITY=BLOCKED")
        return 2
    session = DerivPATOTPSession(
        DerivAuthConfig(
            settings.deriv_app_id, settings.deriv_api_token,
            settings.deriv_options_account_id, "demo",
        ),
        DerivPATOTPTransport(),
    )
    try:
        identity = await session.connect()
        if identity.environment != "demo" or identity.account_id != settings.deriv_options_account_id:
            print("DEMO_IDENTITY=BLOCKED")
            return 2
        print("DEMO_IDENTITY=VERIFIED")
        provider_symbol = provider_symbol_for(
            canonical_symbol=settings.default_symbol, source="deriv_public"
        )
        transport = SequentialSocketTransport(session.connection)
        balance_response = await transport.request({"balance": 1})
        balance = balance_response.get("balance")
        if (
            not isinstance(balance, dict)
            or balance.get("loginid") != settings.deriv_options_account_id
            or not isinstance(balance.get("currency"), str)
            or not balance["currency"].strip()
        ):
            print("DEMO_IDENTITY=BLOCKED")
            return 2
        evidence = await discover_demo_proposal(
            transport,
            provider_symbol=provider_symbol,
            currency=balance["currency"].strip(),
        )
        print(f"PROVIDER_SYMBOL={evidence.symbol.provider_symbol}")
        print(f"CONTRACT_TYPE={evidence.capability.contract_type}")
        print(f"MULTIPLIER_COUNT={len(evidence.capability.multiplier_values)}")
        print("PROPOSAL=VERIFIED")
        print("SUBMISSION=BLOCKED")
        return 0
    except ValueError as exc:
        print("PROPOSAL=BLOCKED")
        print(f"REASON={str(exc)}")
        print("SUBMISSION=BLOCKED")
        return 1
    except Exception:
        print("PROPOSAL=BLOCKED")
        print("REASON=NETWORK_OR_AUTHENTICATION_FAILURE")
        print("SUBMISSION=BLOCKED")
        return 1
    finally:
        await session.close()


def offline_report() -> int:
    specification = current_deriv_multiplier_specification()
    capability = evaluate_deriv_quantity_capability(specification)
    print(f"CONTRACT_SEMANTICS={specification.verification_state.value}")
    print("SUBMISSION=BLOCKED")
    print(f"LOSS_MODEL={'VERIFIED' if capability.stop_risk_authorizable else 'UNVERIFIED'}")
    print("NETWORK=NOT_CONTACTED")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo-network", action="store_true")
    args = parser.parse_args()
    return asyncio.run(run_demo_network()) if args.demo_network else offline_report()


if __name__ == "__main__":
    raise SystemExit(main())
