# Advisory daily balance accounting

`analytics.daily_balance` provides pure accounting for a UTC day. Complete
broker balance movements reconstruct starting balance as current balance minus
all day movements. Trading profit, commission, swap and fees are separate from
funding and other adjustments; deposits do not become trading returns. Duplicate,
nonfinite, out-of-window or incomplete evidence rejects the calculation.

`tools.capture_daily_balance` verifies the existing Weltrade demo session,
resolves the server offset and reads complete history from 00:00 UTC. It never
logs in, submits orders, changes safety state or modifies risk settings. An
account/balance change during retrieval rejects publication. Unsupported deal
categories also reject; credit and other ambiguous account economics are not
silently interpreted. Account-currency results exclude floating position P&L.

Snapshots append to `state/daily_balance_observations.sqlite3`, scoped by account,
with a separate report in `reports/daily-balance-latest.json`. This is a manual
capture utility, not a midnight scheduler or an execution input. The baseline
is labelled RECONSTRUCTED_FROM_COMPLETE_BROKER_HISTORY rather than implying an
actual midnight observation. The 20% target remains advisory and never affects
order frequency, sizing or risk authorization.

Verified at 13:14 Kampala on 5 October: reconstructed starting/current balance
143.91 USD, realized daily net P&L 0.00, funding 0.00. The advisory 20% amount is
28.782 USD (28.78 displayed to cents). The production UI is not yet connected to
this observation and still explicitly states its current-balance target basis.
No deployment or supervisor restart occurred. This result does not establish
profitability or guarantee target achievement.

Validation: 2,561 backend passed, four skipped, all 19 group exit codes zero
(`reports/backend-daily-balance-20261005`); frontend 172 passed and build passed.

## Dashboard integration

The broker read-only daily-accounting reader is now available through the
existing terminal-observation endpoint. It validates the account, complete
server-offset history and stable account snapshot; failures leave daily
accounting unavailable without hiding the terminal connection. The Workspace
shows the reconstructed UTC starting balance, realized net P&L and advisory
target. It no longer substitutes current balance when daily history is missing.
Opening commissions and swap/fees incurred today are included as daily net
trading cash movements; floating P&L and deposits are excluded from this total.

Deployment `dpl_9N6uLeK1dpsoUjh3idFB1gv6L7wE` is READY. Initial CLI deployment
used the wrong default scope; explicitly selecting the verified Joki Holdings
team resolved authorization. No production credentials or entitlement rules
were changed. Local live API returned starting/current balance 143.91 USD and
realized net P&L zero. Authenticated browser display remains unverified.

Final validation: 2,565 backend passed, four skipped, all 19 exits zero
(`reports/backend-daily-ui-20261005`), plus 50 focused API/accounting tests;
174 frontend passed and build passed. Existing build chunk/dependency warnings
remain. The demo supervisor remains running; its execution settings were not
changed or restarted for this observation/dashboard update.
