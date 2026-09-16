"""Bounded deterministic explanations derived only from MarketSetup facts."""

from __future__ import annotations

from execution.market_setup import AnalystExplanation, MarketSetup


def explain_setup(setup: MarketSetup) -> AnalystExplanation:
    if not setup.evidence:
        return AnalystExplanation(state="UNAVAILABLE")
    supporting = [
        f"{item.factor.replace('_', ' ').title()}: {item.assessment} ({item.score}/{item.maximum_score})"
        for item in setup.evidence if item.score > 0
    ]
    conflicting = list(setup.conflicts)
    conflicting.extend(
        f"{item.factor.replace('_', ' ').title()}: {item.assessment}"
        for item in setup.evidence if item.score == 0
    )
    if setup.direction == "NO_TRADE":
        summary = "JQE found no strategy-approved trade on the analyzed closed candle."
    else:
        summary = f"JQE classified the setup as {setup.direction} with state {setup.setup_state}."
    additional = []
    if setup.direction == "NO_TRADE" or setup.setup_state != "READY":
        additional = [
            f"Improvement in {item.factor.replace('_', ' ')} beyond {item.assessment}"
            for item in setup.evidence if item.score < item.maximum_score
        ]
        if setup.data_freshness.status != "CURRENT":
            additional.append("A current fully closed candle within the configured tolerance")
    warning = None if setup.data_freshness.status == "CURRENT" else setup.data_freshness.reason
    return AnalystExplanation(
        state="AVAILABLE", decision_summary=summary,
        supporting_evidence=supporting, conflicting_evidence=list(dict.fromkeys(conflicting)),
        freshness_warning=warning, invalidation_condition=setup.invalidation_condition,
        additional_evidence_required=list(dict.fromkeys(additional)),
    )
