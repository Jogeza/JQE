# Chart refresh latency — 6 October 2026

Timeframe switches now request only active market analysis, terminal observation
and market risk. Initial loads, manual refreshes and normal four-second polling
retain the full workspace profile. Superseded requests continue to be aborted
and request IDs prevent stale responses from replacing a newer timeframe.

Read-only local measurements before the change: nine concurrent resources took
approximately 2.4–4.5 seconds each. The reduced three-resource workload took
approximately 1.6 seconds each in the comparison sample. This is local evidence,
not a hosted latency guarantee.

Production deployment dpl_DkqGtHRFkAw5ZWTQo1rozFTVYPpJ is READY. Hosted loading
and M1/M15 chart switching were previously verified. No broker, execution gate,
risk threshold, supervisor process or safety state changed.

Validation: 2,567 backend passed/four skipped across 19 groups in
reports/backend-latency-20261006; 181 frontend passed and the production build
passed. Existing bundle-size and dependency-audit warnings remain.

Recommended next: collect authenticated hosted request timings by resource and
inspect relay DNS timeouts before attempting further optimization.
