# JQE cloud and VPS preparation

Prepared 4 October 2026. No VPS has been purchased or provisioned. The current PC remains the live Weltrade terminal host. Keep it and MT5 running until the cutover below is verified.

## Responsibilities

| Service | Responsibility | PC-off status |
| --- | --- | --- |
| Vercel | jqe.jokiholdings.com dashboard and server-side research AI | Hosted independently; terminal monitoring still depends on the PC |
| Supabase | Authentication and access controls | Hosted independently |
| Cloudflare | HTTPS, owner Access protection and tunnel | Tunnel origin currently runs on the PC |
| GitHub | Source review and offline CI | Workflow prepared locally; not pushed or run remotely |
| Windows VPS | Weltrade MT5, canonical demo supervisor, observation API and chart posts | Required; not provisioned |

GitHub Actions is validation infrastructure, not a persistent trading host. Vercel and Cloudflare functions do not replace the Windows MT5/Python integration. Use a full Windows desktop VPS rather than assuming the MQL5 virtual-hosting service runs arbitrary Python processes.

## Prepared cloud changes

`.github/workflows/validate.yml` validates the backend on Windows with real MT5 calls blocked and the frontend on Linux. It requires no broker or production credentials. Its first hosted run remains pending a reviewed commit and push.

`supabase/migrations/20261004000300_jqe_cloud_preparation.sql` prepares owner-isolated Weltrade snapshots and server-only Telegram post claims. It is not applied. It does not make monitoring work offline by itself: the snapshot publisher, authenticated fallback reader, retention rules and stale-data UI must be implemented and tested before activation. A saved snapshot must display its observation time and must never be presented as fresh data or used to authorize orders.

The current Telegram process varies the minute within 08:00–08:59, 12:00–12:59 and 18:00–18:59 Kampala time. The minute is stable for a date and slot across restarts, and changes between days. Existing durable claims limit duplicate posts. Posts promote JQE research AI and invite readers to explore the dashboard and share @jqetrading. Missing fresh evidence results in a research message without invented prices. This process still runs on the PC.

## VPS selection and installation

Choose a provider offering a full Windows desktop with administrator access, persistent storage, outbound HTTPS, backups and a region with reasonable broker latency. Start evaluation at 2 vCPU, 4 GB RAM and 60 GB disk; this is a starting specification, not a measured capacity guarantee. Confirm Windows licensing and the actual monthly price before purchase. No provider or paid plan is selected.

1. Restrict RDP to your IP or VPN. Enable updates and backups. Create a dedicated operator account for the terminal and Python processes; keep passwords out of source control.
2. Install the official Weltrade MT5 terminal and Python matching the supported environment. Place the reviewed repository at `D:\JQE`, create `venv`, and install requirements using `D:\JQE\venv\Scripts\python.exe`.
3. Configure the exact demo login/server/terminal path privately with execution disabled. Start MT5 under the dedicated Windows user and verify native Weltrade symbols, account identity, trade permissions, fresh ticks and terminal contract economics.
4. Run the offline validation suite and frontend tests/build. Establish a read-only connection before moving any execution process.
5. Provision the Cloudflare connector privately on the VPS. Preserve the existing Access owner/service policies. Bind API ports 8000 and 8766 to loopback only; do not expose MT5 or Python API ports publicly.

## Controlled cutover

1. Keep the VPS supervisor disabled. Record the current broker positions and reconcile pending/unknown order intents on the PC.
2. Stop only the PC supervisor and channel scheduler deliberately. Never run two supervisors against the same account.
3. After writers stop, take consistent backups of all execution/recovery/idempotency, risk, journal, channel-claim and candle stores, plus private configuration. Preserve original evidence and checksums. Never reset safety state or copy a live SQLite file without its consistent backup protocol.
4. Restore the reviewed configuration and durable state on the VPS. Reconcile authoritative broker positions/history, including existing positions, before enabling any new submissions. Keep the maximum at five only for verified USD equity of at least $50; retain the one-position fallback and all existing risk limits.
5. Verify the hosted dashboard through the VPS tunnel, with current timestamps and the existing owner login. Start exactly one canonical supervisor only after demo verification and recovery checks pass. NO_TRADE remains a valid result.
6. Start exactly one Telegram scheduler using the restored durable claims. Verify a single annotated chart delivery and verify that stale/unavailable data is reported accurately.
7. Configure supervised startup/restart under the same Windows user session that owns MT5. Test logout, disconnect and reboot behavior explicitly; an installed cloudflared service alone does not start MT5 or JQE. Keep execution fail-closed when terminal ownership, identity, history or freshness checks fail.
8. Once fresh hosted monitoring, heartbeat, reconciliation and Telegram delivery survive a controlled reboot, turn off the original PC and verify again. Keep rollback backups; stop VPS execution before restoring execution to the PC.

## Remaining inputs and acceptance

Owner budget: up to $20/month. Initial shortlist checked against provider pages on 4 October 2026:

- MyForexVPS Gold advertises a $19.99 monthly price and 2 cores / 4 GB RAM / 70 GB SSD with Windows 2019/2022. The page also displays annual discount figures; confirm the monthly checkout total, Windows licensing, unrestricted administrator/Python access, tax and renewal before buying: https://myforexvps.com/ . This matches the initial resource target on paper; JQE has not been tested there.
- IONOS Windows M+ advertises 2 cores / 4 GB / 120 GB, $16 for three months with a one-year term and $25 displayed regular pricing. Do not select it under a strict recurring $20 budget without a confirmed lower renewal quote: https://www.ionos.com/servers/windows-vps .
- AccuWeb's comparison page mixes regional variants and pricing rows; its lowest-tier memory is below the initial 4 GB target. Obtain a concrete checkout quote rather than relying on the headline discount: https://www.accuwebhosting.com/vps-hosting/windows/vps-forex/forex-plans-comparison .

No checkout or purchase was performed.

A selected Windows VPS/provider, private installation access, and the Supabase project's database administration access are still needed. The budget is confirmed at up to $20/month. No new cloud secret has been requested or exposed. Server-only credentials will be configured privately when the relevant runtime is ready.

Completion requires tested VPS reboot recovery, one active executor, current Weltrade evidence, owner-protected monitoring, durable journal/history access and cloud post deduplication. This preparation does not claim PC-off live trading or profitability.
