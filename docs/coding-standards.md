# JQE Coding Standards

## Type hints

Every function/method signature — parameters and return type — gets a
type hint. Use `from __future__ import annotations` at the top of every
module so hints can use modern syntax (`str | None`, `list[str]`) on
any supported Python version. Prefer precise types; fall back to
`typing.Any` only when the real type genuinely isn't known yet (and say
why in the docstring or a comment), not as a default.

## Docstrings

Google-style docstrings on every public module, class, and function:

```python
def calculate_lot_size(balance: float, risk_percent: float, stop_distance: float) -> float:
    """Calculates position size from account risk parameters.

    Args:
        balance: Account balance in account currency.
        risk_percent: Percentage of balance to risk on this trade.
        stop_distance: Distance from entry to stop loss, in price units.

    Returns:
        The position size in lots.

    Raises:
        RiskViolationError: If the computed size exceeds account limits.
    """
```

Module-level docstrings explain *why the module exists*, not just what
it contains. Class docstrings document constructor-set attributes.

## Logging, not print

No `print()` in production code. Import the shared logger:

```python
from core.logger import logger

logger.info("Order placed: {}", order_id)
logger.error("Order rejected: {}", reason)
```

Use loguru's `{}`-style placeholders (not f-strings) for log messages
so formatting only happens if the sink's level would actually emit the
line. Log level guide: `DEBUG` for developer detail, `INFO` for normal
lifecycle events, `WARNING` for recoverable/unexpected situations,
`ERROR` for failures that abort the current operation.

## Exceptions

Raise a typed exception from `core.exceptions` instead of returning
`None`/a sentinel dict, or using a bare `except:`. Catch narrowly where
you can do something about the specific failure; catch `JQEError`
broadly only at composition boundaries (a `main()` function, a future
API endpoint) where the only thing left to do is log and stop.

```python
from core.exceptions import MarketDataError

if df is None:
    raise MarketDataError("Market data unavailable", symbol=symbol)
```

Never use a bare `except:` — always name the exception type(s) you
expect, even if that's `except Exception:` at a true top-level
boundary.

## Configuration

Never hardcode a value that's plausibly an operational parameter
(symbols, risk percentages, account balances, log paths). Add it to
`config/settings.py` with a validated default, then read it from
`config.settings` at the call site.

## Formatting & linting

* `black` (line length 100) for formatting.
* `ruff` for linting.
* Run both before committing:

  ```bash
  black --line-length 100 .
  ruff check .
  ```

## Testing

* `pytest`, tests under `tests/`, named `test_<module>.py`.
* Every new/modified module gets tests in the same commit.
* Mock at the boundary (external services, other modules' behavior),
  not the thing under test.
* `MetaTrader5` is Windows-only; `tests/conftest.py` stubs it
  automatically so tests remain runnable on any platform. Don't
  re-implement that stubbing per-test — it's already applied globally.
* Group related tests in a class (`TestSomething`) with descriptive
  method names (`test_raises_x_when_y`), not one flat function per
  behavior.

## Commits

Conventional commit prefixes: `feat:`, `fix:`, `refactor:`, `docs:`,
`test:`, `perf:`, `ci:`, `build:`. One logical change per commit — don't
bundle an unrelated fix into a feature commit.

## Naming

* Modules and functions: `snake_case`.
* Classes: `PascalCase`.
* Constants: `UPPER_SNAKE_CASE`, module-level.
* No abbreviations that aren't immediately obvious (`cfg` → `config`,
  `mkt` → `market`).

## Imports

Group in the standard order (standard library, third-party, local),
one blank line between groups, alphabetized within a group. No wildcard
imports. No unused imports — `ruff check` enforces this.
