# JQE — Weltrade Synthetic Research & Execution

JQE is a Python research and controlled execution platform for **Weltrade synthetic indices through a local Windows MetaTrader 5 terminal**. Weltrade is the only supported operator broker. MT5 is the terminal/API transport, not a second broker.

**Current status:** demo execution only. The previous execution/dashboard phase is committed at `d6d00e1`. The Weltrade migration is in progress. Existing research has not demonstrated positive expectancy; a professional platform is an engineering objective, not a claim of institutional certification or proven profit.

## Integration

```text
Dashboard → JQE FastAPI → strategy / risk / durable executor
                                      ↓ BrokerGateway
                              WeltradeGateway
                                      ↓ MetaTrader5 Python API
                              Local Weltrade MT5 terminal
```

Use the official `MetaTrader5` Python package and your exact terminal executable, account and server. There is no invented Weltrade REST trading API or API key in this integration. The terminal supplies candles, ticks, account state, symbol specifications, positions and trade history. Orders remain behind the durable execution boundary and demo verification.

References: [MetaTrader Python integration](https://www.mql5.com/en/docs/python_metatrader5), [terminal initialization](https://www.mql5.com/en/docs/python_metatrader5/mt5initialize_py), [Weltrade synthetic indices](https://help.weltrade.com/en/articles/13435121-what-are-synthetic-indices).

## Local setup

Use the existing Windows environment at `D:\JQE\venv`. Install dependencies with its Python if required. Copy `.env.example` to `.env` only for a new installation; preserve existing local credentials. Never commit secrets.

```dotenv
JQE_BROKER=weltrade_demo
JQE_MARKET_DATA_SOURCE=broker
JQE_BROKER_EXECUTION_ENABLED=false
JQE_WELTRADE_TERMINAL_PATH=C:\path\to\Weltrade\terminal64.exe
JQE_WELTRADE_DEMO_LOGIN=<your demo account number>
JQE_WELTRADE_DEMO_PASSWORD=<your demo password>
JQE_WELTRADE_DEMO_SERVER=<exact server shown in your terminal>
JQE_DEFAULT_SYMBOL=FX Vol 20
JQE_DEFAULT_TIMEFRAME=M5
```

The `WELTRADE_DEMO_*` values take precedence over `WELTRADE_*` aliases. Both `.env` and `.env.ai` are loaded; check for stale overrides locally without printing credentials. Real accounts remain rejected. Changing the broker alias to `weltrade` does not enable real-money trading.

A stored unsupported broker is rejected rather than silently replaced. Resolve outstanding intents before changing selection; never clear safety databases to get past a block.

```powershell
# Backend and API reference: http://127.0.0.1:8000/docs
& D:\JQE\venv\Scripts\python.exe -m uvicorn api.app:app --host 127.0.0.1 --port 8000

# Frontend, in D:\JQE\frontend
npm run dev

# Read-only terminal smoke check (explicit opt-in, no orders)
$env:JQE_RUN_LIVE_WELTRADE_TESTS='1'
& D:\JQE\venv\Scripts\python.exe -m tools.weltrade_demo_smoke
```

`main.py` is the execution cycle, **not an unconditional dry-run command**. Inspect effective settings before running it. Keep execution disabled while configuring or researching.

## Synthetic research

Use native terminal names such as `FX Vol 20`, `SFX Vol 20`, `PainX 400`, and `MAX PainX 1000`. Forex, metals and Deriv aliases such as `R_75` are outside deployment scope. Availability must be checked against the connected terminal; a name alone does not prove a tradable contract.

Research history requests use Weltrade MT5 and provider-partitioned storage. Tick volume is labelled tick volume, not exchange volume. Missing bars remain gaps; no synthetic fills or cross-broker substitution are allowed.

```powershell
# Cached historical replay; dates must be within your recorded dataset
& D:\JQE\venv\Scripts\python.exe -m backtesting.run --symbol 'FX Vol 20' --timeframe M5 --start '2026-09-01T00:00:00Z' --end '2026-09-02T00:00:00Z' --cached-only
# Replace --cached-only with --fetch-missing to request missing history via MT5.
```

Research simulation is retained as offline mathematics. It is not a selectable execution broker. Existing specialized research tools include `tools/weltrade_scope_backtest.py` and `tools/weltrade_mtf_backtest.py`; their candidate strategies are experimental and are not automatically the live pipeline.

See [research standards and roadmap](docs/weltrade-roadmap.md) before interpreting results or changing a strategy.

## Safety and tests

The mandatory signal bridge is `strategy.pipeline.generate_trading_signal`. `RiskEngine` approves account-currency risk; Weltrade sizing uses terminal contract economics and MT5 lots. `execution.policy.ExecutionPolicy` is pure and fail-closed. `AsyncTradeExecutor` owns durable intents, duplicate prevention and reconciliation. Broker positions/history remain authoritative.

```powershell
& D:\JQE\venv\Scripts\python.exe -m pytest -q
# In D:\JQE\frontend
npm test
npm run build
```

Tests must use isolated fake terminal/gateway state, never a live order connection. [AGENTS.md](AGENTS.md) is the current implementation guide. Older multi-broker documents and adapters are historical migration material, not supported deployment instructions.

For bounded offline validation on Windows, run
`D:\JQE\venv\Scripts\python.exe tools/check_backend_groups.py`.
It isolates configured stores, blocks real MT5 mutation/session calls, and runs
every backend module in groups with a 120-second deadline. Each run saves verbose
tracebacks, JUnit XML, and aggregate results in a new `reports/backend-*` directory.
Use positional test paths and `--size` for focused reruns; existing evidence is
not overwritten. See [the latest validation handoff](docs/weltrade-validation-2026-09-27.md).

The three archived paper-forensics tests are opt-in with
`JQE_ARCHIVED_FORENSICS_ROOT` pointing to an immutable fixture directory containing
`xauusd_m15_5000_final.json`, `paper_diagnostics.sqlite3`, and `historical.sqlite3`.
They retain their original hash and outcome assertions. Live MT5 diagnostics
remain separately opt-in. Neither is required to open the read-only dashboard.

## Future access model

Commercial access remains planned: verified registration through the owner's [Weltrade partner link](https://track.gowt.me/visit/?bta=44132&brand=weltrade) **or** a paid JQE licence. Hosted Supabase authentication, manual referral review and server-enforced AI quotas are implemented. A referral click is not verification, and approval alone grants no entitlement. The premium catalog lists USD 20 for 24 hours, USD 1,500 monthly and USD 5,000 lifetime. Checkout remains disabled at the owner's request. The hosted free-trial activation route is blocked; the old direct database RPC is also blocked by verified production permissions. Existing trials and owner access are preserved. See [premium access status](docs/premium-access-2026-10-06.md) and [hosted authentication deployment](docs/hosted-auth-deployment.md). Do not invent affiliate APIs, promise returns, or unlock trading from a client-side flag.

## Hosted dashboard access

For the current local demo test session, open
[the workstation](http://127.0.0.1:5173/workstation) while the loopback API and Vite
development server are running. This development-only entry has live terminal
ticks/charts and **Journal** for UTC analysis and decision evidence. The separately
armed demo supervisor is independent of the read-only API. See
[demo supervisor operations](docs/weltrade-execution-supervisor.md) for the verified
2026-10-04 launch, current guards, forward cache and restart limitations.

The workstation API must remain bound to `127.0.0.1`; do not expose its port, MT5 terminal, or credentials directly to the internet. The local API trusts only the local Vite development/preview origins. A hosted `jqe.vercel.app` page cannot connect to the workstation API directly.

Phone access requires a separately configured HTTPS backend boundary: an outbound-only tunnel from the workstation to a protected edge, user authentication (OIDC/SSO), server-side token validation, per-user authorization, TLS, rate limiting, and an explicit read-only route allowlist. The Vercel client must not contain a long-lived backend token, and the edge must not proxy MT5 credentials or order-submission routes. Keep the API bound to loopback behind that boundary; do not enable wildcard CORS. Until that authenticated path is implemented and tested, hosted access is intentionally unavailable. The API itself continues to force JQE broker execution off.
