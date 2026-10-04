# Owner monitoring setup — 2026-10-04

Cloudflare domain jokiholdings.com is active. Tunnel jqe-monitor has ID
71002a83-abde-4681-966f-e6d88637ead5. Access application JQE owner monitoring
protects monitor.jokiholdings.com with a single email allow policy for the owner.

The separate relay in api/monitor_relay.py binds to 127.0.0.1:8766 and verifies
Cloudflare Access RS256 signatures, issuer, audience, expiry and the owner email.
Only GET journal, candle and observation-health routes are allowed. No execution,
broker configuration, assistant, notification or research mutation route is
available. It forwards to a fixed 127.0.0.1:8000 origin without credentials,
redirects or arbitrary headers. Every response is non-cacheable. Rate limits and
bounded response sizes apply. The local API, MT5, supervisor and safety state are
unchanged.

The monitor has a small mobile-friendly journal and candle-close chart. It is an
owner observation page, not integration with the Vercel dashboard. Provider,
stale/degraded evidence and observation fetch times are displayed. Prices are not
generated, decisions are not retrained, and execution is unavailable here.

Runtime configuration is kept in ignored state/monitor-config.json. Connector
credentials belong in ignored state/monitor-tunnel.token, restricted to the owner
and SYSTEM. Never paste them into chat or commit them.

Initial activation blocker: the browser supplies only shortened connector token
text and its copy control did not populate the automation clipboard. The owner
must copy the full token through Cloudflare and paste it into the hidden prompt:

```powershell
& D:\JQE\tools\connect_monitor.ps1
```

Verified at 21:26 Africa/Kampala on 2026-10-04: connector logs show four registered
QUIC connections and the saved hostname route to HTTP 127.0.0.1:8766. An unsigned
browser request was intercepted by Cloudflare Access. Signing in using the existing
owner Cloudflare identity loaded the HTTPS monitor with 60 journal events,
supervisor RUNNING, and FX VOL 20 M5 candles marked BROKER/CURRENT with
stale=false and degraded=false. Evidence screenshot:
reports/monitor-setup-20261004/monitor-connected.jpg.

The relay was started with tools/start_monitor.py. It and the connector are session
processes, not automatic Windows startup services. After reboot, start the relay
with the repository Python and restart the connector using --token-file. Do not
restart or arm the trading supervisor as a side effect of monitoring setup.

Validation: all 18 bounded backend groups exited zero; 2,469 tests passed, four
skipped. Frontend 168 passed; production build passed (existing chunk warning).
Nine new relay tests cover missing configuration, identity/signature/claim rejection,
mutation and route blocks, throttling and unavailable-origin handling. Real owner
browser login and full tunnel delivery have now been verified. Vercel integration
remains separate and production has not been redeployed.
