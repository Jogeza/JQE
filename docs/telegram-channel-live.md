# JQE Telegram and guarded demo operation — 2026-10-04

Owner approval: @jqetrading trade/chart messages; 08:00, 12:00 and 18:00
Africa/Kampala daily market/educational posts; maximum five simultaneous demo
positions at verified USD equity >= 50, no further scaling. Below the floor,
unverified equity or other currencies retain the one-position cap.

The canonical main.py execution policy and read-only preflight share
execution.position_limits.demo_position_cap. The supervisor is launched with
JQE_WELTRADE_DEMO_MAX_OPEN_POSITIONS=5 and
JQE_WELTRADE_DEMO_POSITION_EQUITY_FLOOR_USD=50 in its own process environment.
Per-trade risk, daily loss, daily trade limits, same-symbol blocking, durable
recovery and demo-only checks remain. Five is a maximum, never a required count.

The enabled supervisor checks broker closes and refreshes prerequisite safety
observations every ten seconds while waiting for M5 closes. Only the known
OPEN_POSITION_LIMIT_REACHED block with authoritative daily history keeps the
loop alive. Other safety failures still stop execution; no safety marker is
cleared automatically. It re-checks before every canonical watchlist cycle.

API market refresh uses the existing dedicated
D:/JQE/data/live_monitoring_20261004.sqlite3 through a process-local override.
The earlier restart accidentally omitted this override and reopened an older
conflicting cache; it has been restored. All databases remain intact. Current
read-only checks report BROKER candles with stale=false and degraded=false.
Network/terminal failures are labelled unavailable/stale rather than fabricated.

Telegram bot @Jqe_monitor_bot is a verified channel administrator with Post
Messages permission. Real sendMessage was accepted as message 8. Market-chart
preview was accepted as message 9; an existing-position chart with actual broker
entry, stop-loss and take-profit was accepted as message 11:
https://t.me/jqetrading/11. Neither preview submits an order.

POSITION_OPENED alerts attach the cycle's PNG chart: closed candles, warmed
EMA50/EMA200 when sufficient bars exist, UTC candle labels, planned entry/SL/TP,
direction and regime. Closed/rejected events remain factual text when no chart
exists. Delivery uses a bounded queue, durable per-destination event claims and
bounded 429 retries; enqueue alone is not delivery confirmation. Network failure
can prevent delivery. The existing at-most-once claim design does not guarantee
retry after an ambiguous timeout or process crash.

The separate tools.run_telegram_channel_schedule process has execution disabled,
JQE_TELEGRAM_CHANNEL_ENABLED=true and JQE_TELEGRAM_CHANNEL_CHAT_ID=@jqetrading.
It checks every minute during the scheduled hour, with durable one-post-per-date
and slot deduplication. No catch-up flood outside the scheduled hour. Posts use
fresh closed broker candles or explicitly state that fresh evidence is unavailable.
Educational facts are clearly labelled Did you know; no invented quotes,
attributions, signals or prices. Schedule heartbeat:
state/telegram_channel_schedule.json. Next post: 2026-10-05 08:00 Kampala.

Keep this PC, MT5, API, relay, connector, demo supervisor and channel scheduler
running. These processes are not installed as automatic reboot services. Shared
.env/.env.ai execution gates and Telegram destinations were not edited. Hosted
observation orders remain disabled; the live UI separately reports demo supervisor
status. Production deployment: dpl_EhJcVSxrJrNYpRBVqFR7TaGktT6U.

Proof screenshots: reports/monitor-setup-20261004/telegram-strategy-markings.jpg
and hosted-demo-armed-fresh.jpg. Changes remain uncommitted.

Validation and runtime verification: 2,493 backend passed, four skipped, all 18
bounded groups exit zero (reports/backend-channel-five-positions-20261004);
168 frontend passed and production build passed. The restarted supervisor
completed its first four-pair cycle at 23:00 Kampala and stayed RUNNING with
execution_enabled=true. All four results were NO_TRADE; no new order was forced.
# Branding and scheduling update — 4 October 2026

Telegram chart rendering now follows the dashboard JQE wordmark and activity-line emblem, with a faint central JQE watermark, a JQE Engine header, and jqe.jokiholdings.com / @jqetrading footer links. Candles, EMA lines and strategy levels remain readable. Branded preview accepted by Telegram as message 13: https://t.me/jqetrading/13.

The running channel scheduler was refreshed. Daily posts vary their minute within the 08:00, 12:00 and 18:00 Kampala hours. Each date/slot has a restart-stable minute and a durable claim. Feature messages promote JQE's research AI and engine without promising profit or automatic strategy retraining.

Latest execution health: the supervisor stopped at approximately 23:11 Kampala with CLOSE_UNCONFIRMED. Read-only broker evidence showed no open positions and confirmed closes for tickets 562375715 (-1.02 USD before any separate fees) and 562440699 (+1.58 USD before any separate fees). A current tick established a 10,800-second broker offset; an unshifted four-hour history query returned zero deals, while the shifted query returned the two opening and two closing deals. No safety state was cleared and no supervisor was restarted. Earlier RUNNING evidence below is historical.

Cloud/VPS preparation is documented in docs/cloud-vps-setup.md. It does not yet enable PC-off execution.

Validation: all 18 backend groups were run in reports/backend-cloud-brand-20261004. A temporary chart font typo caused two failures in group 03; after correction, the complete 146-test group passed in reports/backend-cloud-brand-repaired-20261004. Combined final coverage is 2,494 passed and four skipped. Focused schedule/chart checks passed 74 tests. Frontend passed 168 tests and production build; existing React act and bundle-size warnings remain. Prepared SQL has not been applied or validated against a live database, and GitHub CI has not run remotely.
