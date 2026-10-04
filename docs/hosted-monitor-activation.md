# Hosted JQE activation — 2026-10-04

Production deployment dpl_228oPG5p187u61Hqv7nrtyki9zJk is READY at
https://jqe.jokiholdings.com and https://jqe.vercel.app.

Owner browser verification passed: live Weltrade demo terminal values, ticks,
closed-candle charts, positions, history and the journal render through the
owner-only read-only Cloudflare relay. Proof images: reports/monitor-setup-20261004/
hosted-workspace-working.jpg, hosted-journal-working.jpg, hosted-ai-working.jpg.

Vercel verifies Supabase authentication, exact owner email and server-side
entitlements. Only 21 explicit GET routes reach the fixed HTTPS monitor origin.
Service credentials remain server-only. The relay independently verifies Access
JWT signatures, issuer, audience, expiry and exact service identity. Browser
credentials are not forwarded to the PC. Writes and arbitrary routes reject.

Bot Fight Mode was disabled with owner approval; Access and HTTPS remain enabled.
Cloudflare also rejected Python's default client identifier; authenticated relay
requests now identify themselves as JQE-Owner-Monitor/1.0. Stale PC DNS was cleared.

Hosted JQE AI uses the owner's approved existing OpenRouter-compatible Meta key
in server-only OPENROUTER_API_KEY, with inclusionai/ling-3.0-flash-sante:free.
A real question returned an answer. This general knowledge assistant does not
receive workstation/account context or authorize trades. Groq was not needed.

Supabase now persists sessions in localStorage and refreshes tokens automatically.
Owner login survived reload and a separate tab. Logout, cleared storage or server
session revocation still requires sign-in. JQE does not store the password.

An open position exposed a DTO bug: Position.id was used instead of canonical
Position.position_id. Both display paths were fixed, with a nonempty-position
regression fixture. Only the read-only API and relay were restarted, not MT5.

The supervisor stopped after 25 cycles at 19:20 UTC. Current read-only preflight
reports OPEN_POSITION_LIMIT_REACHED. Journal ORDER_ACCEPTED at 19:15:17 UTC is an
SFX Vol 99 M5 BUY, and MT5 reports one open SFX Vol 99 position. New orders remain
blocked. No order was forced, position closed, halt cleared or risk limit expanded.
Close/profit verification remains outstanding. No real-money trading is authorized.

Keep this PC, MT5, API, relay and connector running. Automatic reboot startup is
not installed. The supervisor is stopped, not armed; shared dotenv gates remain
disabled. Journaling does not retrain the strategy.

Final validation: 2,474 backend passed, four skipped, all 18 group exits zero
(reports/backend-live-final-20261004/totals.json); 168 frontend passed; production
build passed. Existing chunk-size and dependency audit warnings remain.
Changes remain uncommitted.

Update following owner approval: the guarded demo supervisor is now running,
with the five-position/USD-50 equity cap and Telegram channel schedule described
in docs/telegram-channel-live.md. The earlier stopped-supervisor snapshot above
is historical. Production is now dpl_EhJcVSxrJrNYpRBVqFR7TaGktT6U.
