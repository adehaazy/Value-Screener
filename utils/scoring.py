"""
scoring_v2.py — Deep Value scoring model with sector-aware logic.

Key changes from v1:
  • Financials (banks, insurers, asset managers) use a separate metric set —
    P/Tangible Book and ROE vs cost-of-equity instead of EV/EBITDA and D/E.
  • Non-financials weight EV/EBITDA and P/FCF more heavily; P/E less.
  • All valuation metrics are scored sector-relative (vs sector median),
    not against hard absolute thresholds — so a stock only needs to be cheap
    *for its sector*, which stops naturally low-multiple sectors (utilities,
    telcos) from dominating and naturally high-multiple sectors from being
    excluded entirely.
  • Quality gate keeps ROE and FCF positivity, but D/E is only applied to
    non-financials.
  • A mean-reversion component (52w position) is kept as a contrarian signal.
"""

from __future__ import annotations

import math
from typing import Any

from utils.helpers import _f, _clamp  # shared helpers — do not redefine locally

# ── Sectors treated as financial services ─────────────────────────────────────
FINANCIAL_SECTORS = {
    "Financial Services",
    "Banks",
    "Insurance",
    "Asset Management",
    "Diversified Financials",
    "Capital Markets",
    "Thrifts & Mortgage Finance",
    "Consumer Finance",
    "Financial",           # yfinance sometimes returns this generic label
}

# ── Default quality thresholds (non-financials) ───────────────────────────────
DEFAULT_QUALITY_THRESHOLDS = {
    # Stocks — non-financial
    "min_roe":              8,    # % — lower bar than before; focus on trend not level
    "max_de":               3,    # ratio — relaxed; we care more about FCF coverage
    "min_profit_margin":    2,    # %
    "require_pos_fcf":      True,

    # Stocks — financial (D/E gate removed; use these instead)
    "fin_min_roe":          6,    # % — banks earn less but consistently
    "fin_max_price_book":  2.0,   # P/Tangible Book — above 2x rarely deep value
    "fin_require_pos_fcf": False, # FCF is less meaningful for financials
}

DEFAULT_WEIGHTS = {
    # ── Non-financial stocks — weights sum to 100 ────────────────────
    # EV/EBITDA: best single measure of enterprise cheapness vs peers
    "wt_evebitda":   25,   # Phase 2: reduced from 30 to accommodate ROIC
    # P/FCF: rewards real cash generation, harder to manipulate
    "wt_pfcf":       20,   # Phase 2: reduced from 25
    # P/E: useful but noisy — kept for familiarity
    "wt_pe":         12,   # Phase 2: reduced from 15
    # Sector-relative P/B: useful as floor / asset backing check
    "wt_pb":          8,   # Phase 2: reduced from 10
    # Dividend yield: income signal + management confidence
    "wt_divyield":    7,   # Phase 2: reduced from 10
    # 12-month momentum (Phase 1 rename of 52w position)
    "wt_52w":         8,   # Phase 2: reduced from 10
    # ROIC: measures capital efficiency — how well mgmt deploys capital
    "wt_roic":       20,   # Phase 2: new — 20% weight

    # ── Financial stocks ─────────────────────────────────────────────
    # Price / Tangible Book: primary valuation anchor for financials
    "wt_fin_ptb":    35,
    # ROE vs sector median: quality at a reasonable price
    "wt_fin_roe":    30,
    # Dividend yield: especially meaningful for banks / insurers
    "wt_fin_yield":  20,
    # 52w position: contrarian signal
    "wt_fin_52w":    15,

    # ── ETFs (unchanged from v1) ─────────────────────────────────────
    "wt_etf_aum":    35,
    "wt_etf_ter":    35,
    "wt_etf_ret":    20,
    "wt_etf_mom":    10,

    # ── Money market (unchanged from v1) ─────────────────────────────
    "wt_mm_yield":   60,
    "wt_mm_aum":     25,
    "wt_mm_ter":     15,
}


# ── Helpers (_f and _clamp imported from utils.helpers) ───────────────────────


def _is_financial(inst: dict) -> bool:
    sector = inst.get("sector", "") or ""
    return sector in FINANCIAL_SECTORS


# ── Phase 1: Risk metric helpers ──────────────────────────────────────────────

def _altman_z_score(inst: dict) -> float | None:
    """
    Altman Z-Score for bankruptcy/distress prediction (non-financials only).
      Z >= 3.0  : Safe zone
      1.8-3.0   : Grey zone
      Z <  1.8  : Distress zone — high bankruptcy risk
    Returns None if insufficient data.
    """
    total_assets = _f(inst.get("total_assets") or inst.get("aum"))
    if not total_assets or total_assets <= 0:
        return None

    mkt_cap   = _f(inst.get("market_cap"))
    total_debt = _f(inst.get("total_debt"))
    revenue   = _f(inst.get("revenue") or inst.get("total_revenue"))
    ebit      = _f(inst.get("ebit"))
    wc        = _f(inst.get("working_capital"))
    re        = _f(inst.get("retained_earnings"))

    # Need at least market cap, debt, and revenue
    if mkt_cap is None or total_debt is None or revenue is None:
        return None

    x1 = (wc / total_assets) if wc is not None else 0.0          # Working capital / Assets
    x2 = (re / total_assets)  if re is not None else 0.0          # Retained earnings / Assets
    x3 = (ebit / total_assets) if ebit is not None else 0.0       # EBIT / Assets
    x4 = (mkt_cap / total_debt) if total_debt > 0 else 3.0        # Market cap / Total debt
    x5 = revenue / total_assets                                     # Revenue / Assets

    return round(1.2*x1 + 1.4*x2 + 3.3*x3 + 0.6*x4 + 1.0*x5, 2)


def _accrual_ratio(inst: dict) -> float | None:
    """
    Accrual ratio = (Net Income - Operating Cash Flow) / Total Assets.
    Measures earnings quality — how much profit is 'paper' vs real cash.
      < 0    : Cash earnings exceed accounting earnings (best)
      0-0.05 : Normal range
      > 0.10 : Elevated concern — earnings may be overstated
    Returns None if insufficient data.
    """
    net_income = _f(inst.get("net_income"))
    op_cf      = _f(inst.get("operating_cashflow"))
    assets     = _f(inst.get("total_assets") or inst.get("aum"))

    if net_income is None or op_cf is None or not assets or assets <= 0:
        return None

    return round((net_income - op_cf) / assets, 3)



def _roic(inst: dict) -> float | None:
    """
    Return on Invested Capital = NOPAT / Invested Capital.
    NOPAT  = EBIT × (1 - effective tax rate)   [default tax rate 21%]
    IC     = Total Equity + Total Debt - Cash
    Returns a decimal (e.g. 0.15 = 15% ROIC).  Returns None if data insufficient.
    Skipped for financials (capital structure makes IC meaningless).
    """
    ebit   = _f(inst.get("ebit"))
    equity = _f(inst.get("total_equity"))
    debt   = _f(inst.get("total_debt"))
    cash   = _f(inst.get("total_cash"))
    tax    = _f(inst.get("effective_tax_rate"))

    if ebit is None or equity is None:
        return None

    # Use effective tax rate if available; fall back to 21% (reasonable global avg)
    tax_rate = max(0.0, min(0.50, tax)) if tax is not None else 0.21
    nopat    = ebit * (1.0 - tax_rate)

    ic = (equity) + (debt or 0) - (cash or 0)
    if ic <= 0:
        return None  # negative/zero IC is uninterpretable

    return round(nopat / ic, 4)   # e.g. 0.1547 = 15.5%


def _earnings_quality_composite(inst: dict) -> tuple:
    """
    Returns (eq_score: float|None, nudge: int).
    eq_score : 0-100 composite of accrual ratio + cash conversion ratio.
    nudge    : +5 if high quality, -5 if low quality, 0 if neutral/missing.

    Components:
      Accrual ratio (lower = better):
        < 0    → 80  (cash earnings exceed reported)
        0–0.05 → 65  (normal)
        0.05–0.10 → 50 (watch)
        > 0.10 → 30  (concern)
      Cash conversion  = Operating CF / Net Income  (higher = better):
        > 1.2  → 80  (strong cash backing)
        0.8–1.2 → 60 (normal)
        0.5–0.8 → 40 (weak)
        < 0.5  → 20  (poor — earnings not converting to cash)
    """
    ar  = _accrual_ratio(inst)
    ocf = _f(inst.get("operating_cashflow"))
    ni  = _f(inst.get("net_income"))

    components = []

    if ar is not None:
        if ar < 0:        components.append(80)
        elif ar < 0.05:   components.append(65)
        elif ar < 0.10:   components.append(50)
        else:             components.append(30)

    if ocf is not None and ni is not None and abs(ni) > 0:
        cc = ocf / ni
        if cc > 1.2:      components.append(80)
        elif cc > 0.8:    components.append(60)
        elif cc > 0.5:    components.append(40)
        else:             components.append(20)

    if not components:
        return None, 0

    eq_score = sum(components) / len(components)

    if   eq_score >= 65: nudge = +5
    elif eq_score <= 40: nudge = -5
    else:                nudge = 0

    return round(eq_score, 1), nudge



def _normalised_earnings_flag(inst: dict) -> dict | None:
    """
    Returns a risk_flag dict if trailing earnings are significantly above
    the 3-year historical average — a sign of above-cycle peak earnings.
    Only fires when net_income_avg_3y is available (Phase 3 fetch).
    Returns None if data is insufficient or earnings are not elevated.
    """
    ni_avg   = _f(inst.get("net_income_avg_3y"))
    ni_trail = _f(inst.get("net_income"))
    mkt_cap  = _f(inst.get("market_cap"))

    if not ni_avg or not ni_trail or not mkt_cap:
        return None
    if ni_avg <= 0 or ni_trail <= 0 or mkt_cap <= 0:
        return None

    # Only flag when trailing earnings are >25% above 3-year average
    if ni_trail <= ni_avg * 1.25:
        return None

    pct_above  = (ni_trail / ni_avg - 1) * 100
    norm_pe    = round(mkt_cap / ni_avg,   1)
    trail_pe   = round(mkt_cap / ni_trail, 1)
    return {
        "type":   "cycle",
        "label":  f"↑ Above-cycle earnings (+{pct_above:.0f}%)",
        "detail": (
            f"Trailing earnings are {pct_above:.0f}% above their 3-year average. "
            f"Normalised P/E {norm_pe}x vs trailing {trail_pe}x — "
            f"valuation may look cheaper than it really is through the cycle."
        ),
    }


def _capital_allocation_score(inst: dict) -> float | None:
    """
    Capital allocation score 0–100.  Two components, equally weighted:

    1. Total shareholder yield  = dividend yield + buyback yield
       (rewards companies returning cash; penalises hoarders)
       ≥ 6% → 90 | 4–6% → 75 | 2–4% → 55 | 1–2% → 40 | < 1% → 20

    2. Capex intensity  = capex / revenue
       (moderate reinvestment is healthy; extremes in either direction score lower)
       3–15% → 70 | ≤ 1% → 40 | 15–25% → 55 | > 25% → 30

    Returns None if neither component can be computed.
    """
    mkt_cap    = _f(inst.get("market_cap"))
    revenue    = _f(inst.get("revenue"))
    div_yield  = _f(inst.get("div_yield"))   # stored as % e.g. 3.0 = 3 %
    buyback_1y = _f(inst.get("buyback_1y"))
    capex_1y   = _f(inst.get("capex_1y"))

    components = []

    # ── Shareholder yield ─────────────────────────────────────────────
    if mkt_cap and mkt_cap > 0:
        buyback_yield = (buyback_1y / mkt_cap * 100) if buyback_1y else 0.0
        total_yield   = (div_yield or 0.0) + buyback_yield
        if   total_yield >= 6: components.append(90)
        elif total_yield >= 4: components.append(75)
        elif total_yield >= 2: components.append(55)
        elif total_yield >= 1: components.append(40)
        else:                  components.append(20)

    # ── Capex intensity ───────────────────────────────────────────────
    if capex_1y and revenue and revenue > 0:
        capex_pct = capex_1y / revenue * 100
        if   capex_pct <= 1:   components.append(40)   # under-investing
        elif capex_pct <= 15:  components.append(70)   # healthy reinvestment
        elif capex_pct <= 25:  components.append(55)   # capital heavy, ok
        else:                  components.append(30)   # very capital intensive

    if not components:
        return None

    return round(sum(components) / len(components), 1)


def _sector_median(sector_medians: dict, sector: str, key: str) -> float | None:
    """Return the median value of `key` for instruments in the same sector."""
    return sector_medians.get(sector, {}).get(key)


# ── Sector-relative scoring helper ───────────────────────────────────────────

def _score_vs_median(
    value: float | None,
    sector_med: float | None,
    lower_is_better: bool = True,
    sensitivity: float = 1.0,
) -> float | None:
    """
    Score a metric relative to its sector median, returning 0–100.

    A value equal to the sector median scores 50.  A value 50% below the median
    (i.e. much cheaper) scores ~83 when lower_is_better=True.  Sensitivity
    controls how quickly the score moves — higher = more aggressive differentiation.

    Falls back to a simple absolute-threshold score if no sector median available.
    """
    if value is None:
        return None

    if sector_med is None or sector_med == 0:
        # No median — can't do sector-relative; return neutral
        return 50.0

    ratio = value / sector_med   # 1.0 = at median, <1.0 = cheaper (if lower_is_better)

    _EXP_CLAMP = 500.0  # math.exp(709) overflows; clamp well below that

    if lower_is_better:
        # ratio < 1 → cheaper than median → score > 50
        k = 3.0 * sensitivity
        exponent = min(k * (ratio - 1.0), _EXP_CLAMP)
        score = 100.0 / (1.0 + math.exp(exponent))
    else:
        # Higher is better (e.g. ROE)
        k = 3.0 * sensitivity
        exponent = max(-k * (ratio - 1.0), -_EXP_CLAMP)
        score = 100.0 / (1.0 + math.exp(exponent))

    return _clamp(score)


# ── Quality gate ──────────────────────────────────────────────────────────────

def _passes_quality(inst: dict, qt: dict,
                    sector_medians: dict | None = None) -> tuple[bool, list[str]]:
    """
    Return (passes, list_of_failure_reasons).
    Applies different criteria for financial vs non-financial stocks.
    Phase 1: debt threshold is now industry-adjusted (vs sector median D/E).
    """
    failures = []
    is_fin = _is_financial(inst)
    sector = inst.get("sector", "") or "Unknown"
    sm     = (sector_medians or {}).get(sector, {})

    roe = _f(inst.get("roe"))
    fcf = _f(inst.get("free_cashflow") or inst.get("freeCashflow"))
    pm  = _f(inst.get("profit_margin") or inst.get("profitMargins"))

    if is_fin:
        # Financial quality gate
        min_roe = qt.get("fin_min_roe", 6)
        if roe is not None and roe * 100 < min_roe:
            failures.append(f"ROE {roe*100:.1f}% < {min_roe}%")

        ptb = _f(inst.get("price_to_book") or inst.get("priceToBook"))
        max_ptb = qt.get("fin_max_price_book", 2.0)
        if ptb is not None and ptb > max_ptb:
            failures.append(f"P/Book {ptb:.2f} > {max_ptb}")

        if qt.get("fin_require_pos_fcf", False) and fcf is not None and fcf < 0:
            failures.append("Negative FCF")

    else:
        # Non-financial quality gate
        min_roe = qt.get("min_roe", 8)
        if roe is not None and roe * 100 < min_roe:
            failures.append(f"ROE {roe*100:.1f}% < {min_roe}%")

        # Phase 1: industry-adjusted debt filter
        # Compare D/E against sector median — flag if >150% of peer median
        de = _f(inst.get("debt_to_equity") or inst.get("debtToEquity"))
        max_de = qt.get("max_de", 3)
        if de is not None:
            sm_de = _f(sm.get("de"))
            if sm_de and sm_de > 0:
                de_ratio = de / 100  # yfinance gives e.g. 150 = 1.5x
                sm_de_ratio = sm_de / 100
                if de_ratio > sm_de_ratio * 1.5:
                    failures.append(
                        f"D/E {de_ratio:.1f}x > 1.5x sector median ({sm_de_ratio:.1f}x)"
                    )
            elif de > max_de * 100:   # fallback: absolute cap if no sector data
                failures.append(f"D/E {de/100:.1f}x > {max_de}x")

        min_pm = qt.get("min_profit_margin", 2)
        if pm is not None and pm * 100 < min_pm:
            failures.append(f"Margin {pm*100:.1f}% < {min_pm}%")

        if qt.get("require_pos_fcf", True) and fcf is not None and fcf < 0:
            failures.append("Negative FCF")

        # Phase 1: Altman Z-Score distress screen (non-financials only)
        z = _altman_z_score(inst)
        if z is not None and z < 1.8:
            failures.append(f"Altman Z-Score {z:.1f} (distress zone)")

    return (len(failures) == 0), failures


# ── Non-financial stock scoring ───────────────────────────────────────────────

def _score_stock(inst: dict, sector_medians: dict, weights: dict) -> dict:
    """Score a non-financial stock using sector-relative deep value metrics."""
    sector = inst.get("sector", "Unknown")
    sm = sector_medians.get(sector, {})

    wt_ev   = weights.get("wt_evebitda", 25)   # Phase 2: rebalanced
    wt_fcf  = weights.get("wt_pfcf",     20)
    wt_pe   = weights.get("wt_pe",       12)
    wt_pb   = weights.get("wt_pb",        8)
    wt_div  = weights.get("wt_divyield",  7)
    wt_52w  = weights.get("wt_52w",       8)
    wt_roic = weights.get("wt_roic",     20)   # Phase 2: ROIC
    total_wt = wt_ev + wt_fcf + wt_pe + wt_pb + wt_div + wt_52w + wt_roic  # = 100

    scores = {}
    used_wt = 0.0
    weighted_sum = 0.0

    def _add(key, val, med_key, lower_is_better=True, sensitivity=1.0, wt=0):
        nonlocal used_wt, weighted_sum
        s = _score_vs_median(val, sm.get(med_key), lower_is_better, sensitivity)
        scores[key] = s
        if s is not None:
            used_wt += wt
            weighted_sum += s * wt

    ev_ebitda  = _f(inst.get("ev_ebitda")    or inst.get("enterpriseToEbitda"))
    pe         = _f(inst.get("pe")           or inst.get("trailingPE") or inst.get("forwardPE"))
    pb         = _f(inst.get("pb")           or inst.get("priceToBook"))
    div_yield  = _f(inst.get("div_yield")    or inst.get("dividendYield"))
    pos_52w    = _f(inst.get("pos_52w"))     # 0–1, where stock sits in 52w range

    # P/FCF — derived from market cap and free cash flow if not directly available
    mkt_cap = _f(inst.get("market_cap") or inst.get("marketCap"))
    fcf     = _f(inst.get("free_cashflow") or inst.get("freeCashflow"))
    p_fcf   = (mkt_cap / fcf) if (mkt_cap and fcf and fcf > 0) else None

    _add("ev_ebitda_score", ev_ebitda,  "ev_ebitda",  lower_is_better=True,  sensitivity=1.2, wt=wt_ev)
    _add("pfcf_score",      p_fcf,      "pfcf",       lower_is_better=True,  sensitivity=1.2, wt=wt_fcf)
    _add("pe_score",        pe,         "pe",         lower_is_better=True,  sensitivity=0.8, wt=wt_pe)
    _add("pb_score",        pb,         "pb",         lower_is_better=True,  sensitivity=0.8, wt=wt_pb)

    # Dividend yield: higher is better; compare vs sector median
    if div_yield is not None:
        div_score = _score_vs_median(div_yield, sm.get("div_yield"), lower_is_better=False, sensitivity=1.0)
        scores["div_score"] = div_score
        if div_score is not None:
            used_wt += wt_div
            weighted_sum += div_score * wt_div

    # Phase 1: 6-12 month momentum (replaces 52w low contrarian signal)
    # Positive absolute return = buying strength; score >50 = above zero return
    return_1y = _f(inst.get("return_1y") or inst.get("yr1_pct"))
    if return_1y is not None:
        # Normalise: 0% return → 50; +30% → ~100; -30% → ~0
        # If yr1_pct is stored as a percentage (e.g. 15.0), scale accordingly
        r = return_1y if abs(return_1y) <= 1.0 else return_1y / 100
        mom_score = _clamp(50.0 + r * 166.7)
        scores["momentum_score"] = mom_score
        used_wt += wt_52w
        weighted_sum += mom_score * wt_52w
    elif pos_52w is not None:
        # Fallback: if no return data, keep 52w position as neutral momentum proxy
        scores["momentum_score"] = 50.0   # neutral, not contrarian
        used_wt += wt_52w
        weighted_sum += 50.0 * wt_52w


    # Phase 2: ROIC — higher is better, compare vs sector median
    roic = _roic(inst)
    if roic is not None and not _is_financial(inst):
        roic_score = _score_vs_median(roic, sm.get("roic"), lower_is_better=False, sensitivity=2.0)
        if roic_score is None:
            # No sector median yet — score absolutely: 15%+ ROIC is excellent
            if   roic >= 0.20: roic_score = 90
            elif roic >= 0.15: roic_score = 75
            elif roic >= 0.10: roic_score = 60
            elif roic >= 0.05: roic_score = 45
            else:              roic_score = 25
        scores["roic_score"] = roic_score
        used_wt += wt_roic
        weighted_sum += roic_score * wt_roic


    if used_wt == 0:
        return {**inst, "score": None, "score_components": scores,
                "score_coverage": 0.0, "is_financial": False}

    raw_score = weighted_sum / used_wt
    # Coverage penalty: if we're missing data, shade the score toward 50 (neutral)
    coverage = used_wt / total_wt
    score = raw_score * coverage + 50.0 * (1.0 - coverage)

    # Phase 1: compute and attach risk flags (don't affect score, surface in UI)
    risk_flags = []
    z = _altman_z_score(inst)
    if z is not None:
        if z < 1.8:
            risk_flags.append({"type": "distress", "label": f"⚠ Distress risk (Z={z:.1f})", "detail": "Altman Z-Score below 1.8 — elevated bankruptcy risk"})
        elif z < 3.0:
            risk_flags.append({"type": "grey_zone", "label": f"○ Z-Score grey zone ({z:.1f})", "detail": "Altman Z-Score 1.8–3.0 — monitor closely"})

    ar = _accrual_ratio(inst)
    if ar is not None and ar > 0.10:
        risk_flags.append({"type": "accruals", "label": f"⚠ Earnings quality ({ar:+.2f})", "detail": f"Accrual ratio {ar:.2f} — paper profits may exceed cash earnings"})

    # Phase 3: normalised earnings flag (risk flag only, no score change)
    norm_flag = _normalised_earnings_flag(inst)
    if norm_flag:
        risk_flags.append(norm_flag)

    # Phase 3: capital allocation score → minor nudge (±3 pts)
    ca_score = _capital_allocation_score(inst)
    if ca_score is not None:
        if   ca_score >= 72: ca_nudge = +3
        elif ca_score <= 35: ca_nudge = -3
        else:                ca_nudge =  0
    else:
        ca_nudge = 0

    # Phase 2: earnings quality composite → score nudge + flag
    eq_score, eq_nudge = _earnings_quality_composite(inst)
    final_score = _clamp(score + eq_nudge + ca_nudge)

    return {
        **inst,
        "score":          round(final_score, 1),
        "score_nudge":    eq_nudge,          # shown as (+5)/(-5) badge on card
        "score_components": scores,
        "score_coverage": round(coverage, 2),
        "is_financial":   False,
        "p_fcf":          p_fcf,
        "roic":           roic,
        "altman_z":       z,
        "accrual_ratio":  ar,
        "eq_score":       eq_score,          # 0-100 earnings quality composite
        "ca_score":       ca_score,          # 0-100 capital allocation score
        "ca_nudge":       ca_nudge,
        "risk_flags":     risk_flags,
    }


# ── Financial stock scoring ───────────────────────────────────────────────────

def _score_financial(inst: dict, sector_medians: dict, weights: dict) -> dict:
    """Score a financial sector stock using P/TangibleBook, ROE, yield, momentum."""
    sector = inst.get("sector", "Unknown")
    sm = sector_medians.get(sector, {})

    wt_ptb  = weights.get("wt_fin_ptb",   35)
    wt_roe  = weights.get("wt_fin_roe",   30)
    wt_div  = weights.get("wt_fin_yield", 20)
    wt_52w  = weights.get("wt_fin_52w",   15)
    total_wt = wt_ptb + wt_roe + wt_div + wt_52w

    scores = {}
    used_wt = 0.0
    weighted_sum = 0.0

    ptb     = _f(inst.get("price_to_book") or inst.get("priceToBook"))
    roe     = _f(inst.get("roe"))
    div_y   = _f(inst.get("div_yield") or inst.get("dividendYield"))
    pos_52w = _f(inst.get("pos_52w"))

    # P/Tangible Book — lower is better vs sector peers
    ptb_score = _score_vs_median(ptb, sm.get("price_to_book") or sm.get("pb"),
                                  lower_is_better=True, sensitivity=1.3)
    scores["ptb_score"] = ptb_score
    if ptb_score is not None:
        used_wt += wt_ptb
        weighted_sum += ptb_score * wt_ptb

    # ROE — higher is better; compare vs sector (rewards quality financials)
    roe_pct = roe * 100 if roe is not None else None
    sm_roe  = sm.get("roe")
    sm_roe_pct = sm_roe * 100 if sm_roe is not None else None
    roe_score = _score_vs_median(roe_pct, sm_roe_pct, lower_is_better=False, sensitivity=1.0)
    scores["roe_score"] = roe_score
    if roe_score is not None:
        used_wt += wt_roe
        weighted_sum += roe_score * wt_roe

    # Dividend yield — higher is better
    div_score = _score_vs_median(div_y, sm.get("div_yield"), lower_is_better=False, sensitivity=0.8)
    scores["div_score"] = div_score
    if div_score is not None:
        used_wt += wt_div
        weighted_sum += div_score * wt_div

    # Phase 1: 6-12 month momentum (replaces 52w low contrarian signal)
    return_1y = _f(inst.get("return_1y") or inst.get("yr1_pct"))
    if return_1y is not None:
        r = return_1y if abs(return_1y) <= 1.0 else return_1y / 100
        mom_score = _clamp(50.0 + r * 166.7)
        scores["momentum_score"] = mom_score
        used_wt += wt_52w
        weighted_sum += mom_score * wt_52w
    elif pos_52w is not None:
        scores["momentum_score"] = 50.0
        used_wt += wt_52w
        weighted_sum += 50.0 * wt_52w

    if used_wt == 0:
        return {**inst, "score": None, "score_components": scores,
                "score_coverage": 0.0, "is_financial": True}

    raw_score = weighted_sum / used_wt
    coverage  = used_wt / total_wt
    score     = raw_score * coverage + 50.0 * (1.0 - coverage)

    # Phase 1: risk flags for financials (Z-Score not applicable; use accruals)
    risk_flags = []
    ar = _accrual_ratio(inst)
    if ar is not None and ar > 0.10:
        risk_flags.append({"type": "accruals", "label": f"⚠ Earnings quality ({ar:+.2f})", "detail": f"Accrual ratio {ar:.2f} — paper profits may exceed cash earnings"})

    return {
        **inst,
        "score": round(_clamp(score), 1),
        "score_components": scores,
        "score_coverage": round(coverage, 2),
        "is_financial": True,
        "accrual_ratio": ar,
        "risk_flags": risk_flags,
    }


# ── ETF scoring (unchanged from v1) ──────────────────────────────────────────

def _score_etf(inst: dict, weights: dict) -> dict:
    wt_aum = weights.get("wt_etf_aum", 35)
    wt_ter = weights.get("wt_etf_ter", 35)
    wt_ret = weights.get("wt_etf_ret", 20)
    wt_mom = weights.get("wt_etf_mom", 10)

    def _score_aum(v):
        if v is None: return None
        # log scale: >10bn = 100, 1bn = 75, 100m = 50, <10m = 0
        if v <= 0: return 0.0
        return _clamp((math.log10(v / 1e7)) / math.log10(1000) * 100)

    def _score_ter(v):
        # 0% = 100, 0.1% = 90, 0.5% = 50, 1.5% = 0
        if v is None: return None
        return _clamp(100 - (v / 0.015) * 100)

    def _score_ret(v):
        # 1y return: +20% = 100, 0% = 50, -20% = 0
        if v is None: return None
        return _clamp(50 + v * 250)

    def _score_mom(v):
        # Same as ret but tighter range for momentum
        if v is None: return None
        return _clamp(50 + v * 300)

    s_aum = _score_aum(_f(inst.get("aum") or inst.get("totalAssets")))
    s_ter = _score_ter(_f(inst.get("ter") or inst.get("annualReportExpenseRatio")))
    s_ret = _score_ret(_f(inst.get("return_1y")))
    s_mom = _score_mom(_f(inst.get("return_3m")))

    components = [
        (s_aum, wt_aum), (s_ter, wt_ter), (s_ret, wt_ret), (s_mom, wt_mom)
    ]
    used, total = 0.0, 0.0
    for s, w in components:
        if s is not None:
            used += s * w
            total += w
    if total == 0:
        return {**inst, "score": None}

    score = used / total
    return {**inst, "score": round(_clamp(score), 1)}


# ── Money market scoring (unchanged from v1) ──────────────────────────────────

def _score_money_market(inst: dict, weights: dict) -> dict:
    wt_yield = weights.get("wt_mm_yield", 60)
    wt_aum   = weights.get("wt_mm_aum",   25)
    wt_ter   = weights.get("wt_mm_ter",   15)

    def _s_yield(v):
        # 5%+ yield = 100; 0% = 0
        if v is None: return None
        return _clamp(v / 0.05 * 100)

    def _s_aum(v):
        if v is None or v <= 0: return None
        return _clamp(math.log10(max(v, 1e6) / 1e6) / 4 * 100)

    def _s_ter(v):
        if v is None: return None
        return _clamp(100 - (v / 0.005) * 100)

    s_y = _s_yield(_f(inst.get("div_yield") or inst.get("dividendYield")))
    s_a = _s_aum(_f(inst.get("aum") or inst.get("totalAssets")))
    s_t = _s_ter(_f(inst.get("ter") or inst.get("annualReportExpenseRatio")))

    components = [(s_y, wt_yield), (s_a, wt_aum), (s_t, wt_ter)]
    used, total = 0.0, 0.0
    for s, w in components:
        if s is not None:
            used += s * w
            total += w
    if total == 0:
        return {**inst, "score": None}
    return {**inst, "score": round(_clamp(used / total), 1)}


# ── Public API ────────────────────────────────────────────────────────────────

def score_instrument(
    inst: dict,
    sector_medians: dict,
    quality_thresholds: dict | None = None,
    weights: dict | None = None,
) -> dict:
    """Score a single instrument. Returns inst dict with 'score' and quality fields added."""
    qt = quality_thresholds or DEFAULT_QUALITY_THRESHOLDS
    wt = weights or DEFAULT_WEIGHTS
    ac = inst.get("asset_class", "Stock")

    if ac == "ETF":
        return _score_etf(inst, wt)
    if ac == "Money Market":
        return _score_money_market(inst, wt)

    # Stock path
    passes, failures = _passes_quality(inst, qt, sector_medians)
    result = inst.copy()
    result["quality_passes"]       = passes
    result["quality_fail_reasons"] = failures

    if _is_financial(inst):
        scored = _score_financial(result, sector_medians, wt)
    else:
        scored = _score_stock(result, sector_medians, wt)

    return scored


def score_all(
    instruments: list[dict],
    sector_medians: dict,
    quality_thresholds: dict | None = None,
    weights: dict | None = None,
) -> list[dict]:
    """Score all instruments in one pass."""
    return [
        score_instrument(inst, sector_medians, quality_thresholds, weights)
        for inst in instruments
    ]


def compute_sector_medians(instruments: list[dict]) -> dict:
    """
    Compute per-sector medians for valuation metrics used in sector-relative scoring.
    Returns {sector: {metric: median_value}}.
    """
    from collections import defaultdict
    import statistics

    buckets: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))

    METRICS = [
        ("ev_ebitda",    lambda i: _f(i.get("ev_ebitda") or i.get("enterpriseToEbitda"))),
        ("pe",           lambda i: _f(i.get("pe") or i.get("trailingPE"))),
        ("pb",           lambda i: _f(i.get("pb") or i.get("priceToBook"))),
        ("price_to_book",lambda i: _f(i.get("price_to_book") or i.get("priceToBook"))),
        ("div_yield",    lambda i: _f(i.get("div_yield") or i.get("dividendYield"))),
        ("roe",          lambda i: _f(i.get("roe"))),
        ("pfcf",         lambda i: _compute_pfcf(i)),
        ("de",           lambda i: _f(i.get("debt_to_equity") or i.get("debtToEquity"))),
        # Phase 2: ROIC sector median for comparative scoring
        ("roic",         lambda i: _roic(i)),
    ]

    def _compute_pfcf(inst):
        mkt = _f(inst.get("market_cap") or inst.get("marketCap"))
        fcf = _f(inst.get("free_cashflow") or inst.get("freeCashflow"))
        if mkt and fcf and fcf > 0:
            return mkt / fcf
        return None

    for inst in instruments:
        if not inst.get("ok") or inst.get("asset_class") != "Stock":
            continue
        sector = inst.get("sector") or "Unknown"
        for key, extractor in METRICS:
            v = extractor(inst)
            if v is not None and v > 0:
                buckets[sector][key].append(v)

    result = {}
    for sector, metrics in buckets.items():
        result[sector] = {}
        for key, vals in metrics.items():
            if vals:
                sorted_vals = sorted(vals)
                n = len(sorted_vals)
                mid = n // 2
                result[sector][key] = (
                    sorted_vals[mid] if n % 2 == 1
                    else (sorted_vals[mid - 1] + sorted_vals[mid]) / 2
                )

    return result


# ── Score display helpers (unchanged API) ─────────────────────────────────────

def score_label(score) -> str:
    if score is None: return "—"
    s = float(score)
    if s >= 80: return "Strong Buy"
    if s >= 65: return "Buy"
    if s >= 50: return "Watch"
    if s >= 35: return "Avoid"
    return "Strong Avoid"


def score_colour(score) -> str:
    """Text/foreground colour for a score value (light theme)."""
    if score is None: return "#6B7D92"
    s = float(score)
    if s >= 80: return "#1E5C38"   # deep green
    if s >= 65: return "#2A6B44"   # green
    if s >= 50: return "#9B6B1A"   # amber
    if s >= 35: return "#B85C20"   # orange-brown
    return "#8B2635"               # deep red


def score_bg(score) -> str:
    """Background tint colour for a score badge (light theme)."""
    if score is None: return "#F4F1EC"
    s = float(score)
    if s >= 80: return "#D6EDDF"   # green tint
    if s >= 65: return "#EAF3EE"   # light green
    if s >= 50: return "#FBF3E4"   # amber tint
    if s >= 35: return "#FAEEE6"   # orange tint
    return "#FAECEE"               # red tint

