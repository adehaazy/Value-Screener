"""
utils/helpers.py — Shared low-level utilities.

Consolidates the _f() / _clamp() helpers that were previously duplicated
across scoring.py, verdicts.py and app.py, plus the common numeric formatters
that were scattered across app.py, deep_analysis.py and briefing.py.

Import style (internal modules):
    from utils.helpers import _f, _clamp
"""

from __future__ import annotations

import math


# ── Core numeric helpers ──────────────────────────────────────────────────────

def _f(v) -> float | None:
    """
    Safely coerce *v* to float.
    Returns None for None, NaN, infinity, and anything non-numeric.
    """
    if v is None:
        return None
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Clamp *v* to [lo, hi]."""
    return max(lo, min(hi, v))


# ── Percentage / ratio formatters ─────────────────────────────────────────────

def _pct(v, decimals: int = 1) -> str:
    """Format a decimal fraction as a percentage string (e.g. 0.15 → '15.0%')."""
    if v is None:
        return "N/A"
    return f"{float(v) * 100:.{decimals}f}%"


def _x(v, decimals: int = 1) -> str:
    """Format a value as a multiple string (e.g. 12.3 → '12.3x')."""
    if v is None:
        return "N/A"
    return f"{float(v):.{decimals}f}x"


def _fmt_pct(v, d: int = 1) -> str:
    """
    Format a plain percentage value with sign (e.g. -3.5 → '-3.5%').
    Used for price-change / return columns.
    Returns '—' for None.
    """
    v = _f(v)
    if v is None:
        return "—"
    if abs(v) < 0.05:
        return "0.0%"
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.{d}f}%"


def _fmt_ratio(v, d: int = 1) -> str:
    """Format a ratio / multiple (e.g. 12.3 → '12.3x'). Returns '—' for None."""
    v = _f(v)
    if v is None:
        return "—"
    return f"{v:.{d}f}x"


def _fmt_price(v, cur: str = "") -> str:
    """Format a price with optional currency prefix. Returns '—' for None."""
    v = _f(v)
    if v is None:
        return "—"
    return f"{cur}{v:,.2f}"


def _fmt_aum(v) -> str:
    """Format a large asset-value as bn/m with dollar sign. Returns '—' for None."""
    v = _f(v)
    if v is None:
        return "—"
    if v >= 1e9:
        return f"${v / 1e9:.1f}bn"
    if v >= 1e6:
        return f"${v / 1e6:.0f}m"
    return f"${v:,.0f}"
