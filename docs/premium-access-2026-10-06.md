# Premium access — 6 October 2026

Owner-authorized production changes: jogezamosha@gmail.com has an ACTIVE
server-side override with no expiry. This grants non-expiring access through
the existing ADMIN_GRANTED entitlement; it does not raise AI quotas or risk
limits. Pre-change evidence is preserved in ignored state/backups.

The server catalog prices are USD 20 for 24 hours, USD 1,500 monthly and
USD 5,000 lifetime. All remain NOT_CONFIGURED for checkout. The premium page
reads this catalog and cannot collect payment or activate access.

The hosted legacy trial activation route now rejects authenticated requests
with PAID_ACCESS_CHECKOUT_UNAVAILABLE. Existing trials remain intact.

IMPORTANT: migration 20261006000100_retire_free_trial.sql is prepared but has
not been applied to production: no authorized SQL management connection was
available. Until applied, the old direct authenticated Supabase RPC can still
activate a free trial. The hosted route alone does not close that direct path.

The migration is transactional and aborts if inherited grants still allow
authenticated or anonymous execution. Apply it once in the configured project's
Supabase SQL Editor, then run supabase/verify_paid_access_gate.sql. Both permission
checks must return true, and catalog rows must retain NOT_CONFIGURED. Do not
rerun the base migration. These SQL changes do not alter existing entitlements,
trials, usage counters or trading state. Production SQL validation is pending.

The owner confirmed that payment-provider selection is deferred and checkout
must stay disabled. No payment provider implementation is authorized yet.

Next: apply the migration through the project SQL administration interface,
choose the payment provider and implement verified, idempotent server webhooks
before enabling purchases or activating any paid 24-hour access. Define refund,
renewal and lifetime-support terms before sales. No payment integration is
invented and no payment was collected.

Validation: all 19 backend groups exited zero, 2,565 passed and four skipped
(reports/backend-plans-20261006). Frontend: 178 passed; production build passed.
Deployment dpl_9oyH7GUubDXgyhJHY5arRKcMeuC5 is READY. The custom-domain root
and deployed premium JavaScript asset returned HTTP 200. An unauthenticated
Python request to /upgrade returned HTTP 403; authenticated browser visual
validation was unavailable. Existing build warnings remain: bundle size and
the deployment's dependency audit (three moderate, one high).
