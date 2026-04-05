"""
Plain-English verdict generator.
Fully rule-based — no LLM, no API calls, deterministic.
Produces a 2–3 sentence summary per instrument that explains
what the data is saying in plain language.
"""

from utils.helpers import _f, _pct, _x  # shared helpers — do not redefine locally


# ══════════════════════════════════════════════════════════════════════════════
# STOCK VERDICTS
# ══════════════════════════════════════════════════════════════════════════════

def stock_verdict(row: dict, sector_medians: dict) -> str:
    """Generate a plain-English verdict for a stock."""

    passes = row.get("quality_passes", False)
    reasons = row.get("quality_fail_reasons", [])  # written by scoring.py as quality_fail_reasons
    flags   = row.get("quality_flags", [])
    score   = _f(row.get("score"))
    sector  = row.get("sector", "")
    sm      = sector_medians.get(sector, {})

    # ── Failed quality gate ────────────────────────────────────────────────
    if not passes:
        if not reasons:
            return "Business quality concerns — not scored on valuation."
        short_reasons = []
        for r in reasons:
            if "ROE" in r:       short_reasons.append("weak returns on equity")
            elif "Debt" in r:    short_reasons.append("excessive leverage")
            elif "margin" in r:  short_reasons.append("thin profit margins")
            elif "cash" in r:    short_reasons.append("negative free cash flow")
            else:                short_reasons.append(r.split("—")[0].strip().lower())
        reason_str = " and ".join(short_reasons[:2])
        return (f"Does not pass the quality filter ({reason_str}). "
                f"Excluded from value scoring — a cheap price alone doesn't make this attractive.")

    # ── Passed quality gate ────────────────────────────────────────────────
    roe    = _f(row.get("roe"))
    pe     = _f(row.get("pe"))
    pb     = _f(row.get("pb"))
    de     = _f(row.get("debt_equity"))
    div    = _f(row.get("div_yield"))
    pct_h  = _f(row.get("pct_from_high"))
    pm     = _f(row.get("profit_margin"))

    sm_pe  = _f(sm.get("pe"))
    sm_pb  = _f(sm.get("pb"))

    # Quality sentence
    if roe and roe >= 0.20:
        quality = f"High-quality business with strong {_pct(roe)} return on equity"
    elif roe and roe >= 0.15:
        quality = f"Solid business with {_pct(roe)} return on equity"
    elif roe:
        quality = f"Adequate business ({_pct(roe)} ROE)"
    else:
        quality = "Quality business"

    if de and de < 0.3:
        quality += ", near debt-free"
    elif de and de < 1.0:
        quality += ", conservative balance sheet"
    elif de:
        quality += f", moderate leverage ({de:.1f}x D/E)"

    quality += "."

    # Valuation sentence
    if sm_pe and pe:
        pe_multiple = pe / sm_pe
        if pe_multiple < 0.80:
            val = f"Trading at a meaningful discount to sector peers (P/E {pe:.1f}x vs sector {sm_pe:.1f}x)"
        elif pe_multiple < 0.95:
            val = f"Modestly below sector median on P/E ({pe:.1f}x vs {sm_pe:.1f}x)"
        elif pe_multiple < 1.05:
            val = f"In line with sector valuation (P/E {pe:.1f}x vs sector {sm_pe:.1f}x)"
        elif pe_multiple < 1.20:
            val = f"Carrying a slight premium to sector peers (P/E {pe:.1f}x vs {sm_pe:.1f}x)"
        else:
            val = f"Expensive vs sector peers (P/E {pe:.1f}x vs sector median {sm_pe:.1f}x)"
    elif pe:
        if pe < 12:   val = f"Low P/E of {pe:.1f}x — appears cheap on earnings"
        elif pe < 18: val = f"Reasonable P/E of {pe:.1f}x"
        elif pe < 25: val = f"P/E of {pe:.1f}x — moderate premium"
        else:         val = f"High P/E of {pe:.1f}x — demands strong future growth"
    else:
        val = "Valuation data limited"

    # Income / price sentence
    # div_yield is stored as a percentage (e.g. 4.0 = 4%) — use directly, no conversion needed
    div_pct = div
    extras = []
    if div_pct and div_pct >= 3.0:
        extras.append(f"{div_pct:.1f}% dividend yield adds income appeal")
    elif div_pct and div_pct >= 1.0:
        extras.append(f"{div_pct:.1f}% dividend yield")

    if pct_h and pct_h < -20:
        extras.append(f"{abs(pct_h):.0f}% below its 52-week high — potential entry opportunity")
    elif pct_h and pct_h < -10:
        extras.append(f"has pulled back {abs(pct_h):.0f}% from recent highs")

    if flags:
        extras.append(flags[0].lower())

    extra_str = (". " + ". ".join(extras[:2]).capitalize()) if extras else ""

    return f"{quality} {val}{extra_str}."


# ══════════════════════════════════════════════════════════════════════════════
# ETF VERDICTS
# ══════════════════════════════════════════════════════════════════════════════

def etf_verdict(row: dict) -> str:
    """Generate a plain-English verdict for an ETF."""
    ter  = _f(row.get("ter"))
    aum  = _f(row.get("aum"))
    ret  = _f(row.get("yr1_pct"))
    div  = _f(row.get("div_yield"))

    # Cost sentence
    if ter is None:
        cost_str = "Cost data unavailable"
    elif ter < 0.001:
        cost_str = f"Exceptionally low cost at {ter*100:.2f}% TER"
    elif ter < 0.002:
        cost_str = f"Very low cost at {ter*100:.2f}% TER"
    elif ter < 0.003:
        cost_str = f"Low cost at {ter*100:.2f}% TER"
    elif ter < 0.005:
        cost_str = f"Moderate cost at {ter*100:.2f}% TER"
    else:
        cost_str = f"Relatively expensive at {ter*100:.2f}% TER — look for cheaper alternatives"

    # Size sentence
    if aum is None:
        size_str = ""
    elif aum >= 10_000_000_000:
        size_str = f"Large, highly liquid fund (${aum/1e9:.1f}bn AUM)"
    elif aum >= 2_000_000_000:
        size_str = f"Established fund (${aum/1e9:.1f}bn AUM)"
    elif aum >= 500_000_000:
        size_str = f"Decent-sized fund (${aum/1e6:.0f}m AUM)"
    else:
        size_str = f"Smaller fund (${aum/1e6:.0f}m AUM) — monitor for closure risk"

    # Return note
    ret_str = ""
    if ret is not None:
        if ret > 15:   ret_str = f"Strong 1-year return of {ret:.1f}%."
        elif ret > 5:  ret_str = f"Solid 1-year return of {ret:.1f}%."
        elif ret > 0:  ret_str = f"Modest {ret:.1f}% 1-year return."
        else:          ret_str = f"Down {abs(ret):.1f}% over the past year."

    parts = [p for p in [cost_str, size_str] if p]
    base = ". ".join(parts) + "."
    if ret_str:
        base += " " + ret_str

    return base


# ══════════════════════════════════════════════════════════════════════════════
# MONEY MARKET VERDICTS
# ══════════════════════════════════════════════════════════════════════════════

def money_market_verdict(row: dict) -> str:
    """Generate a plain-English verdict for a money market / short duration fund."""
    yld   = _f(row.get("div_yield"))
    ter   = _f(row.get("ter"))
    aum   = _f(row.get("aum"))

    # div_yield is stored as a percentage (e.g. 4.0 = 4%) — use directly
    # ter is stored as a decimal from yfinance (e.g. 0.002 = 0.2%) — convert to %
    yld_pct = yld
    ter_pct = ter * 100 if ter is not None else None
    net_yld = (yld_pct - ter_pct) if (yld_pct is not None and ter_pct is not None) else yld_pct

    # Yield sentence
    if net_yld is None:
        yld_str = "Yield data unavailable"
    elif net_yld >= 4.5:
        yld_str = f"Excellent net yield of ~{net_yld:.1f}% — strong income case"
    elif net_yld >= 3.5:
        yld_str = f"Good net yield of ~{net_yld:.1f}%"
    elif net_yld >= 2.0:
        yld_str = f"Modest net yield of ~{net_yld:.1f}%"
    else:
        yld_str = f"Low net yield of ~{net_yld:.1f}% — limited income benefit"

    # Size sentence
    if aum and aum >= 5_000_000_000:
        size_str = f"large, stable fund (${aum/1e9:.1f}bn)"
    elif aum and aum >= 1_000_000_000:
        size_str = f"established fund (${aum/1e9:.1f}bn)"
    elif aum:
        size_str = f"smaller fund (${aum/1e6:.0f}m) — some concentration risk"
    else:
        size_str = ""

    parts = [yld_str]
    if size_str:
        parts.append(size_str[0].upper() + size_str[1:])

    return ". ".join(parts) + "."


# ══════════════════════════════════════════════════════════════════════════════
# DISPATCHER
# ══════════════════════════════════════════════════════════════════════════════

def generate_verdict(row: dict, sector_medians: dict) -> str:
    ac = row.get("asset_class", "")
    if not row.get("ok", False):
        return "Data unavailable for this instrument."
    if ac == "Stock":
        return stock_verdict(row, sector_medians)
    if ac == "ETF":
        return etf_verdict(row)
    if ac == "Money Market":
        return money_market_verdict(row)
    return "—"


def add_verdicts(instruments: list[dict], sector_medians: dict) -> list[dict]:
    for inst in instruments:
        inst["verdict"] = generate_verdict(inst, sector_medians)
    return instruments
