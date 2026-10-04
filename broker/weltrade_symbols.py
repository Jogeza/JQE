"""Explicit research/execution universe, using native Weltrade terminal names."""
from __future__ import annotations

import re

from core.exceptions import MarketDataError

_SCOPE_PATTERN = re.compile(
    r"(?:S?FX\s+VOL\.?\s*\d+|(?:MAX\s+)?(?:PAINX|GAINX)\s+\d+|"
    r"FLIPX\s+\d+|SWITCHX\s+\d+|BREAKX\s+\d+|FIBOX)",
    re.IGNORECASE,
)

# Rendering of the names WeltradeGateway._resolve_symbol reads back from the
# terminal catalogue and writes into the candle store. Layers that cannot query
# the terminal (watchlist, cache lookup, research API, frontend) must share this
# spelling, otherwise one instrument fragments into several cached datasets that
# no exact-equality match can reunite.
_CANONICAL_FAMILIES = {
    "FXVOL": "FX Vol",
    "SFXVOL": "SFX Vol",
    "PAINX": "PainX",
    "GAINX": "GainX",
    "FLIPX": "FlipX",
    "SWITCHX": "SwitchX",
    "BREAKX": "BreakX",
    "FIBOX": "FiboX",
}

_CANONICAL_PATTERN = re.compile(
    r"^(?:(?P<prefix>MAX)\s+)?"
    r"(?P<family>S?FX\s*VOL\.?|PAINX|GAINX|FLIPX|SWITCHX|BREAKX|FIBOX)"
    r"(?:\s*(?P<number>\d+))?$",
    re.IGNORECASE,
)


def is_weltrade_synthetic(symbol: str) -> bool:
    """Reject cross-broker aliases and non-synthetic instruments fail closed.

    This is a scope check, not evidence of availability. The gateway must also
    find the exact normalized name in the connected terminal catalogue.
    """
    return _SCOPE_PATTERN.fullmatch(symbol.strip()) is not None


def weltrade_symbol_key(symbol: str) -> str:
    """Case- and punctuation-insensitive identity for comparing spellings."""
    return re.sub(r"[^A-Z0-9]", "", symbol.upper())


def canonical_weltrade_symbol(symbol: str) -> str:
    """Render an in-scope symbol in Weltrade terminal catalogue casing.

    Raises for anything outside the synthetic scope, so this never widens what
    `is_weltrade_synthetic` accepts.
    """
    clean = symbol.strip()
    if not is_weltrade_synthetic(clean):
        raise MarketDataError("Only native Weltrade synthetic indices are supported", symbol=symbol)
    match = _CANONICAL_PATTERN.match(re.sub(r"\s+", " ", clean))
    if match is None:
        raise MarketDataError("Only native Weltrade synthetic indices are supported", symbol=symbol)
    family = _CANONICAL_FAMILIES[weltrade_symbol_key(match.group("family"))]
    if family == "FiboX":
        return family
    prefix = "MAX " if match.group("prefix") else ""
    return f"{prefix}{family} {match.group('number')}"


def require_weltrade_synthetic(symbol: str) -> str:
    """Assert Weltrade synthetic scope and return the canonical spelling."""
    return canonical_weltrade_symbol(symbol)


def weltrade_symbol_family_id(symbol: str) -> str:
    """Return a programmatic identifier for the symbol's synthetic family."""
    canonical = canonical_weltrade_symbol(symbol)
    key = weltrade_symbol_key(canonical)
    if "MAXPAINX" in key:
        return "max_painx"
    if "PAINX" in key:
        return "painx"
    if "MAXGAINX" in key:
        return "max_gainx"
    if "GAINX" in key:
        return "gainx"
    if "SFXVOL" in key:
        return "sfx_vol"
    if "FXVOL" in key:
        return "fx_vol"
    if "FLIPX" in key:
        return "flipx"
    if "SWITCHX" in key:
        return "switchx"
    if "BREAKX" in key:
        return "breakx"
    if "FIBOX" in key:
        return "fibox"
    return "other"


def weltrade_symbol_family_name(symbol: str) -> str:
    """Return a human-readable family title for UI presentation."""
    fam_id = weltrade_symbol_family_id(symbol)
    names = {
        "fx_vol": "FX Volatility",
        "sfx_vol": "SFX Volatility",
        "painx": "PainX (Crash)",
        "max_painx": "MAX PainX",
        "gainx": "GainX (Boom)",
        "max_gainx": "MAX GainX",
        "flipx": "FlipX (Regime Flip)",
        "switchx": "SwitchX",
        "breakx": "BreakX (Breakout)",
        "fibox": "FiboX (Fibonacci)",
    }
    return names.get(fam_id, "Synthetic Index")


SUPPORTED_WELTRADE_SYNTX: tuple[str, ...] = (
    "FX Vol 20", "FX Vol 40", "FX Vol 60", "FX Vol 80", "FX Vol 99",
    "SFX Vol 20", "SFX Vol 40", "SFX Vol 60", "SFX Vol 80", "SFX Vol 99",
    "PainX 400", "PainX 600", "PainX 800", "PainX 999", "PainX 1200",
    "MAX PainX 1000", "MAX PainX 2000",
    "GainX 400", "GainX 600", "GainX 800", "GainX 999", "GainX 1200",
    "MAX GainX 1000", "MAX GainX 2000",
    "FlipX 1", "FlipX 2", "FlipX 3", "FlipX 4", "FlipX 5",
    "SwitchX 600", "SwitchX 1200", "SwitchX 1800",
    "BreakX 600", "BreakX 1200", "BreakX 1800",
    "FiboX",
)


SYNTX_FAMILIES: tuple[dict[str, str], ...] = (
    {"id": "all", "name": "All SyntX", "description": "Complete Weltrade SyntX synthetic universe"},
    {"id": "fx_vol", "name": "FX Volatility", "description": "Constant step volatility index series"},
    {"id": "sfx_vol", "name": "SFX Volatility", "description": "Smooth volatility continuous indices"},
    {"id": "painx", "name": "PainX (Crash)", "description": "Crash / jump down price shock indices"},
    {"id": "max_painx", "name": "MAX PainX", "description": "High frequency crash indices"},
    {"id": "gainx", "name": "GainX (Boom)", "description": "Boom / jump up price shock indices"},
    {"id": "max_gainx", "name": "MAX GainX", "description": "High frequency boom indices"},
    {"id": "flipx", "name": "FlipX", "description": "Regime switching flip indices"},
    {"id": "switchx", "name": "SwitchX", "description": "Discrete mean reversion switch indices"},
    {"id": "breakx", "name": "BreakX", "description": "High volatility breakout indices"},
    {"id": "fibox", "name": "FiboX", "description": "Fibonacci retracement synthetic index"},
)


def list_supported_weltrade_synthetics() -> list[str]:
    """Return all in-scope Weltrade SyntX symbols in canonical spelling."""
    return list(SUPPORTED_WELTRADE_SYNTX)


def list_syntx_families() -> list[dict[str, str]]:
    """Return synthetic family categories for filtering and navigation."""
    return list(SYNTX_FAMILIES)


def get_weltrade_symbol_specs(symbol: str) -> dict[str, object]:
    """Return verified broker terminal specifications for a Weltrade SyntX instrument.

    Preserves terminal properties (digits, point, volume_min, volume_step)
    without inferring precision from floating point representations.
    """
    canonical = canonical_weltrade_symbol(symbol)
    fam_id = weltrade_symbol_family_id(canonical)

    # MAX PainX and MAX GainX instruments use 3 decimal digits and 0.001 point
    if fam_id in {"max_painx", "max_gainx"}:
        return {
            "symbol": canonical,
            "family_id": fam_id,
            "family_name": weltrade_symbol_family_name(canonical),
            "digits": 3,
            "point": 0.001,
            "volume_min": 0.01,
            "volume_step": 0.01,
            "volume_max": 3.0,
            "contract_size": 1.0,
        }

    # PainX and GainX standard series use min volume 0.1, digits 2, point 0.01
    if fam_id in {"painx", "gainx"}:
        return {
            "symbol": canonical,
            "family_id": fam_id,
            "family_name": weltrade_symbol_family_name(canonical),
            "digits": 2,
            "point": 0.01,
            "volume_min": 0.1,
            "volume_step": 0.01,
            "volume_max": 15.0,
            "contract_size": 1.0,
        }

    # SwitchX and BreakX use min volume 0.1, digits 2, point 0.01
    if fam_id in {"switchx", "breakx"}:
        return {
            "symbol": canonical,
            "family_id": fam_id,
            "family_name": weltrade_symbol_family_name(canonical),
            "digits": 2,
            "point": 0.01,
            "volume_min": 0.1,
            "volume_step": 0.01,
            "volume_max": 15.0,
            "contract_size": 1.0,
        }

    # Default for FX Vol, SFX Vol, FlipX, FiboX: digits 2, point 0.01, volume_min 0.01
    return {
        "symbol": canonical,
        "family_id": fam_id,
        "family_name": weltrade_symbol_family_name(canonical),
        "digits": 2,
        "point": 0.01,
        "volume_min": 0.01,
        "volume_step": 0.01,
        "volume_max": 50.0,
        "contract_size": 1.0,
    }
