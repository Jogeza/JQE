# JQE Trading Platform

JQE is an institutional-grade algorithmic trading platform for
MetaTrader 5, built in Python. It's being developed toward: live MT5
execution, multiple trading strategies, portfolio and risk management,
performance analytics, professional backtesting with walk-forward
optimization, trade journaling, a REST API, and a dashboard.

**Status:** early-stage. Milestone 1 (Foundation — configuration,
logging, exceptions, docs) is complete. See
[`docs/roadmap.md`](docs/roadmap.md) for what's done and what's next,
and [`docs/architecture.md`](docs/architecture.md) for design
rationale, including an important discovery about the current state of
`main.py`'s trading pipeline.

## Architecture

```
config/          Validated runtime settings (Pydantic Settings, .env)
core/            Shared kernel — logging, exceptions, MT5 connection,
                 market data, indicators, regime detection, engine
strategy/        Signal generation
risk/            Position sizing and trade approval
execution/       Order/trade simulation
analytics/       Performance measurement
backtesting/     Historical replay
```

Full details, including dependency direction and the rationale behind
each Foundation-layer decision, are in
[`docs/architecture.md`](docs/architecture.md).

## Installation

Requires Python 3.13+ (developed/tested against 3.12; 3.13 not yet
verified in this environment).

```bash
git clone https://github.com/Jogeza/JQE.git
cd JQE
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # then fill in real values
```

**Note on `MetaTrader5`:** it's a Windows-only package. On Linux/macOS,
`pip install -r requirements.txt` will skip it automatically (see the
platform marker in `requirements.txt`), and the test suite stubs it via
`tests/conftest.py` so the rest of the codebase remains testable
cross-platform. Live trading against a real MT5 terminal still requires
Windows.

## Configuration

All configuration lives in `config/settings.py` (a `pydantic-settings`
`Settings` model) and can be overridden via environment variables
(prefixed `JQE_`) or a `.env` file. See
[`.env.example`](.env.example) for the full list of supported
variables and their defaults.

```python
from config import settings

settings.default_symbol   # "XAUUSD"
settings.risk_percent     # 1.0
```

## Running

```bash
python main.py                  # one market-analysis cycle
python -m backtesting.backtest  # historical data load + indicators
```

Both currently stop after market analysis / data preparation — see
"A significant discovery" in `docs/architecture.md` for why the
signal → risk → execution stage isn't wired in yet.

## Development workflow

1. Read `docs/architecture.md` and `docs/roadmap.md` before starting —
   know what already exists and what's next.
2. Check `docs/coding-standards.md` for type hints, docstrings,
   logging, exceptions, and test conventions.
3. Format and lint before committing:
   ```bash
   black --line-length 100 .
   ruff check .
   ```
4. Run the test suite:
   ```bash
   pytest -q
   ```
   Some pre-existing test files fail independent of your change — see
   "Known test debt" below. New/modified code should always have a
   fully passing, isolated test file.
5. Commit in small, logical units using conventional prefixes (`feat:`,
   `fix:`, `refactor:`, `docs:`, `test:`, `perf:`, `ci:`, `build:`).

### Known test debt

Nine pre-existing test files fail independent of the Foundation
milestone (tracked as Milestone 4 in `docs/roadmap.md`):

* `tests/test_data_manager.py`, `tests/test_indicators.py`,
  `tests/test_market_loader.py`, `tests/test_market_regime.py`,
  `tests/test_signal_engine.py`, `tests/test_signal_scorer.py` import a
  `data` package that doesn't exist in the repository.
* `tests/test_core_engine.py` and `tests/test_autonomous_scanner.py`
  are manual debug scripts (no `test_*` functions, module-level
  `print()`s) that fail at runtime without a real MT5 connection.

## Repository structure

```
JQE/
├── analytics/           Performance & scoring metrics
├── backtesting/          Historical replay engine
├── config/                Settings (Pydantic Settings + .env)
├── core/                   Shared kernel (logging, exceptions, engine,
│                           MT5 connection, market data, indicators,
│                           regime detection, decision pipeline)
├── docs/                    architecture.md, roadmap.md,
│                           coding-standards.md
├── execution/             Order/trade simulation
├── risk/                   Position sizing & trade approval
├── strategy/                Signal generation & scoring
├── tests/                 Test suite (pytest)
├── .env.example
├── main.py                 Entry point
└── requirements.txt
```

## License

Not yet specified.
