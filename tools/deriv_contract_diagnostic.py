"""Non-mutating report of JQE's current Deriv contract evidence state."""

from broker.deriv_contract_spec import (
    current_deriv_multiplier_specification,
    evaluate_deriv_quantity_capability,
)


def main() -> int:
    specification = current_deriv_multiplier_specification()
    capability = evaluate_deriv_quantity_capability(specification)
    print(f"CONTRACT_SEMANTICS={specification.verification_state.value}")
    print("SUBMISSION=BLOCKED")
    print(f"LOSS_MODEL={'VERIFIED' if capability.stop_risk_authorizable else 'UNVERIFIED'}")
    print("NETWORK=NOT_CONTACTED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
