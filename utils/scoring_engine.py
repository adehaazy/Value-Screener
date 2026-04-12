"""
scoring_engine.py — Value Screener Core Scoring Engine v3.0
============================================================
Philosophy: Quality at a fair price. Medium-to-long-term, global, value investing.

Design principles:
  • Multi-factor model: Value + Quality + Momentum + Capital Allocation.
  • Separate factor sets for: Non-Financials, Financials, ETFs, Money Market Funds.
  • All stock factors scored sector-relative (percentile-style sigmoid), not on
    absolute thresholds — so the engine is valid globally, across cycles.
  • Hard filters / score penalties protect against value traps.
  • Missing data handled conservatively via tiered completeness penalty.
  • Backtest-ready: score_instruments(date, universe, snapshot) -> results.
  • All weights and thresholds are centralised in CONFIG — tune without touching logic.

Score meaning:
  50  = exactly at sector median (neutral vs peers)
  >50 = better than peers on that metric
  <50 = worse than peers

Labels:
  80-100 : Strong Buy
  65-79  : Buy
  50-64  : Watch
  35-49  : Avoid
   0-34  : Strong Avoid
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: INPUT SCHEMAS (Data Interfaces)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class InstrumentInput:
    """
    Universal input record for a single instrument.
    All monetary values in the instrument's reporting currency.
    Ratios stored as decimals (e.g. ROE = 0.15, not 15%).
    Percentages stored as decimals unless noted otherwise.
    Fields may be None when data is unavailable.
    """

    # ── Identification ────────────────────────────────────────────────────────
    ticker:          str  = ""
    isin:            str  = ""
    name:            str  = ""
    country:         str  = ""           # ISO-2 e.g. "US", "GB", "DE"
    exchange:        str  = ""           # e.g. "LSE", "NYSE", "XETRA"
    sector:          str  = ""           # GICS sector label
    industry:        str  = ""           # GICS industry label
    asset_class:     str  = "Stock"      # "Stock" | "ETF" | "Money Market"
    is_cyclical:     bool = False        # override: treat as cyclical

    # ── Price & Returns ───────────────────────────────────────────────────────
    price:           Optional[float] = None
    market_cap:      Optional[float] = None   # in reporting currency (absolute)
    return_1y:       Optional[float] = None   # total return, decimal (0.15 = +15%)
    return_6m:       Optional[float] = None
    return_3m:       Optional[float] = None
    return_1m:       Optional[float] = None

    # ── Core Fundamentals (TTM) ───────────────────────────────────────────────
    revenue:         Optional[float] = None
    ebitda:          Optional[float] = None
    ebit:            Optional[float] = None
    net_income:      Optional[float] = None
    operating_cashflow: Optional[float] = None
    free_cashflow:   Optional[float] = None
    capex:           Optional[float] = None

    # ── Balance Sheet ─────────────────────────────────────────────────────────
    total_assets:    Optional[float] = None
    current_assets:  Optional[float] = None
    current_liabilities: Optional[float] = None
    total_debt:      Optional[float] = None
    cash:            Optional[float] = None
    book_equity:     Optional[float] = None   # total equity / book value
    goodwill:        Optional[float] = None
    intangibles:     Optional[float] = None
    retained_earnings: Optional[float] = None

    # ── Valuation Multiples ───────────────────────────────────────────────────
    pe:              Optional[float] = None   # trailing or forward P/E
    pb:              Optional[float] = None   # price-to-book
    ev_ebitda:       Optional[float] = None
    ev_ebit:         Optional[float] = None
    ev:              Optional[float] = None   # enterprise value

    # ── Capital Allocation ────────────────────────────────────────────────────
    div_yield:       Optional[float] = None   # decimal (0.03 = 3%)
    div_per_share:   Optional[float] = None
    shares_outstanding: Optional[float] = None
    shares_3y_ago:   Optional[float] = None   # for dilution/buyback check
    payout_ratio:    Optional[float] = None   # dividends / net income

    # ── Quality / History ─────────────────────────────────────────────────────
    roe:             Optional[float] = None   # decimal
    roa:             Optional[float] = None   # decimal
    effective_tax_rate: Optional[float] = None  # decimal
    net_income_avg_3y:  Optional[float] = None  # 3-year avg net income
    revenue_avg_5y:     Optional[float] = None  # 5-7yr avg revenue (cyclicals)
    ebit_margin_avg_5y: Optional[float] = None  # 5-7yr avg EBIT margin (cyclicals)
    roic_avg_3y:        Optional[float] = None  # multi-year ROIC average

    # ── Goodwill Risk ────────────────────────────────────────────────────────
    goodwill_impairment_3y: Optional[float] = None  # cumulative impairment last 3y

    # ── Financials-specific ───────────────────────────────────────────────────
    tier1_capital_ratio:  Optional[float] = None  # decimal (0.12 = 12%)
    npl_ratio:            Optional[float] = None  # non-performing loans / total loans
    loan_loss_coverage:   Optional[float] = None  # reserves / NPLs
    npl_trend:            Optional[str]   = None  # "improving" | "stable" | "deteriorating"

    # ── ETF-specific ──────────────────────────────────────────────────────────
    aum:             Optional[float] = None
    ter:             Optional[float] = None   # total expense ratio, decimal
    tracking_error:  Optional[float] = None
    return_3y:       Optional[float] = None
    inception_date:  Optional[date]  = None

    # ── Money Market ──────────────────────────────────────────────────────────
    yield_7d:        Optional[float] = None   # 7-day yield, decimal
    currency:        str = ""

    # ── Risk Flags ───────────────────────────────────────────────────────────
    regulatory_flag:   bool = False  # sanctions, major fines
    litigation_flag:   bool = False  # major active litigation
    esg_controversy:   bool = False  # severe ESG controversy
    flag_severity:     str  = "low"  # "low" | "medium" | "high"

    # ── Raw dict pass-through (for backward compatibility) ───────────────────
    extra: dict = field(default_factory=dict)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: CONFIGURATION — WEIGHTS & THRESHOLDS
# ══════════════════════════════════════════════════════════════════════════════

CONFIG = {

    # ── Non-Financial Weights (must sum to 100) ───────────────────────────────
    "weights_stock": {
        "ev_earnings":          25,   # EV/EBIT or EV/EBITDA; lower = better
        "fcf_yield":            20,   # FCF / Market Cap; higher = better
        "pe":                   10,   # trailing P/E; lower = better
        "pb":                    5,   # P/B; lower = better
        "roic":                 15,   # NOPAT / Invested Capital; higher = better
        "earnings_quality":     10,   # accruals + cash conversion composite
        "momentum":             10,   # 12M (ex last month) return
        "capital_allocation":    5,   # buybacks, dividends, capex quality
        # total = 100
    },

    # ── Cyclical overrides (added delta only; engine merges at scoring time) ──
    "weights_stock_cyclical_delta": {
        "ev_earnings":          +5,   # normalised earnings get extra weight
        "momentum":             +5,   # momentum matters more for timing cyclicals
        "earnings_quality":     -5,   # cyclical accruals are noisier
        "capital_allocation":   -5,
    },

    # ── Financial Weights (must sum to 100) ───────────────────────────────────
    "weights_financial": {
        "pb":                   25,   # P/TangibleBook
        "roe":                  35,   # ROE vs peers
        "div_yield":            15,   # dividend yield
        "div_stability":         5,   # dividend growth/consistency
        "momentum":             10,   # 12M return
        "asset_quality":        10,   # NPL, coverage, Tier1 composite
        # total = 100
    },

    # ── ETF Weights ───────────────────────────────────────────────────────────
    "weights_etf": {
        "aum":                  35,
        "ter":                  35,
        "performance":          20,   # 1Y / 3Y return blend
        "momentum":             10,
        # optional: if tracking_error available, partially replaces performance
    },

    # ── Money Market Weights ──────────────────────────────────────────────────
    "weights_money_market": {
        "yield":                60,
        "aum":                  25,
        "fees":                 15,
    },

    # ── Hard Filter Thresholds ────────────────────────────────────────────────
    "filters": {
        # Altman Z (non-financials)
        "altman_z_distress":    1.8,   # below this → cap score at 40
        "altman_z_grey":        3.0,   # below this → add warning flag

        # Leverage vs industry
        "de_vs_sector_penalty_ratio": 1.5,  # if D/E > 1.5× sector median
        "de_leverage_penalty":  15,    # points deducted

        # Earnings manipulation (Beneish proxy)
        "beneish_m_threshold": -2.22,  # above this → manipulation risk
        "manipulation_penalty": 20,    # points deducted

        # Accrual ratio
        "accrual_high":         0.10,   # above this → elevated concern
        "accrual_penalty":      10,     # points deducted

        # Regulatory / ESG flag penalties
        "flag_penalty_low":      5,
        "flag_penalty_medium":  10,
        "flag_penalty_high":    15,

        # Goodwill impairment (as % of book equity)
        "goodwill_impairment_pct": 0.05,  # 5% of equity
        "goodwill_penalty":     8,         # points deducted

        # Financials: bank below book + deteriorating asset quality
        "bank_below_book_with_bad_quality_penalty": 15,
    },

    # ── Cross-Market Sector Adjustment ───────────────────────────────────────
    "cross_market": {
        "sector_premium_threshold": 1.30,   # sector P/E 30% above market → -5
        "sector_discount_threshold": 0.70,  # sector P/E 30% below market → +5
        "max_adjustment":            10,     # absolute max ±points
        "base_adjustment":            5,     # adjustment applied when threshold hit
    },

    # ── Data Completeness Thresholds ─────────────────────────────────────────
    "data_completeness": {
        "threshold_full":       1.00,   # 100%+ → no penalty
        "threshold_limited":    0.80,   # 80–99% → -5 pts, flag "Limited Data"
        "threshold_uncertain":  0.60,   # 60–79% → -10 pts, flag "High Uncertainty"
        "threshold_insufficient": 0.60, # <60% → not scored, "Insufficient Data"
        "penalty_limited":       5,
        "penalty_uncertain":    10,
    },

    # ── Sensitivity of sector-relative scoring ────────────────────────────────
    # Controls sigmoid steepness: higher = faster differentiation from median.
    "sensitivity": {
        "ev_earnings":    1.2,
        "fcf_yield":      1.2,
        "pe":             0.8,
        "pb":             0.8,
        "roic":           2.0,
        "roe":            1.0,
        "div_yield":      1.0,
        "momentum":       1.0,
        "ptb_financial":  1.3,
    },

    # ── ROIC cost-of-capital proxy ─────────────────────────────────────────────
    "wacc_proxy":  0.08,   # 8% — if ROIC < this, penalise quality score

    # ── Cyclical sectors ──────────────────────────────────────────────────────
    "cyclical_sectors": {
        "Energy", "Basic Materials", "Materials", "Metals & Mining",
        "Oil & Gas", "Chemicals", "Paper & Forest Products",
        "Industrials",   # partially; engine checks is_cyclical flag too
    },

    # ── Financial sectors ─────────────────────────────────────────────────────
    "financial_sectors": {
        "Financial Services", "Banks", "Insurance", "Asset Management",
        "Diversified Financials", "Capital Markets",
        "Thrifts & Mortgage Finance", "Consumer Finance", "Financial",
    },

    # ── Tax rate fallback ─────────────────────────────────────────────────────
    "default_tax_rate": 0.21,
}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: LOW-LEVEL HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _f(v: Any) -> Optional[float]:
    """Safe float coercion. Returns None for None, NaN, inf."""
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _sigmoid_score(
    value: float,
    sector_med: Optional[float],
    lower_is_better: bool,
    sensitivity: float = 1.0,
) -> Optional[float]:
    """
    Score a metric sector-relatively on a 0–100 scale using a sigmoid curve.
    • value == sector_med  → 50 (exactly neutral)
    • lower_is_better=True: value << median → close to 100 (cheapest)
    • lower_is_better=False: value >> median → close to 100 (best)
    • Falls back to 50 (neutral) if no sector median is available.
    """
    if value is None:
        return None
    if sector_med is None or sector_med == 0:
        return 50.0   # can't rank without a peer group — report neutral

    ratio = value / sector_med   # 1.0 = at median
    k = 3.0 * sensitivity
    _MAX_EXP = 500.0

    if lower_is_better:
        exp = min(k * (ratio - 1.0), _MAX_EXP)
    else:
        exp = min(k * (1.0 - ratio), _MAX_EXP)

    score = 100.0 / (1.0 + math.exp(exp))
    return _clamp(score)


def _percentile_score(value: float, peer_values: list[float], lower_is_better: bool) -> float:
    """
    True percentile rank across a list of peer values.
    Returns 0–100 where 100 = best in cohort.
    Used when we have the full universe (e.g. cross-market adjustment).
    """
    if not peer_values or value is None:
        return 50.0
    below = sum(1 for p in peer_values if p < value)
    rank = (below / len(peer_values)) * 100.0
    return rank if not lower_is_better else (100.0 - rank)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4: DERIVED METRICS
# ══════════════════════════════════════════════════════════════════════════════

def compute_roic(inst: InstrumentInput, cfg: dict = CONFIG) -> Optional[float]:
    """
    ROIC = NOPAT / Invested Capital
    NOPAT = EBIT × (1 – effective_tax_rate)
    IC    = Book Equity + Total Debt – Cash
    Skipped for financials (IC concept is not meaningful for banks).
    """
    ebit   = _f(inst.ebit)
    equity = _f(inst.book_equity)
    debt   = _f(inst.total_debt) or 0.0
    cash   = _f(inst.cash) or 0.0
    tax    = _f(inst.effective_tax_rate)

    if ebit is None or equity is None:
        return None

    tax_rate = max(0.0, min(0.50, tax)) if tax is not None else cfg["default_tax_rate"]
    nopat = ebit * (1.0 - tax_rate)
    ic    = equity + debt - cash

    if ic <= 0:
        return None   # negative IC is uninterpretable

    return round(nopat / ic, 4)


def compute_altman_z(inst: InstrumentInput) -> Optional[float]:
    """
    Altman Z-Score (non-financials only).
    Z >= 3.0  : Safe
    1.8-3.0   : Grey zone
    Z < 1.8   : Distress — high bankruptcy risk
    """
    ta = _f(inst.total_assets)
    if not ta or ta <= 0:
        return None

    mkt  = _f(inst.market_cap)
    debt = _f(inst.total_debt)
    rev  = _f(inst.revenue)
    ebit = _f(inst.ebit)
    wc   = (_f(inst.current_assets) or 0.0) - (_f(inst.current_liabilities) or 0.0)
    re   = _f(inst.retained_earnings) or 0.0

    if mkt is None or debt is None or rev is None:
        return None

    x1 = wc  / ta
    x2 = re  / ta
    x3 = (ebit / ta) if ebit is not None else 0.0
    x4 = (mkt / debt) if debt > 0 else 3.0   # 3.0 = low leverage proxy
    x5 = rev / ta

    return round(1.2*x1 + 1.4*x2 + 3.3*x3 + 0.6*x4 + 1.0*x5, 2)


def compute_accrual_ratio(inst: InstrumentInput) -> Optional[float]:
    """
    Accrual ratio = (Net Income – Operating Cash Flow) / Total Assets
    < 0    : cash earnings exceed accounting (excellent)
    0–0.05 : normal
    0.05–0.10: caution
    > 0.10 : elevated manipulation / earnings quality risk
    """
    ni   = _f(inst.net_income)
    ocf  = _f(inst.operating_cashflow)
    ta   = _f(inst.total_assets)

    if ni is None or ocf is None or not ta or ta <= 0:
        return None

    return round((ni - ocf) / ta, 3)


def compute_beneish_proxy(inst: InstrumentInput) -> Optional[float]:
    """
    Simplified Beneish M-Score proxy using available ratios.
    Full M-Score needs 8 indices; we approximate with 3 key signals:
      1. Days Sales Receivable Index  (DSRI) — rising = risk
      2. Asset Quality Index (AQI)   — rising = risk
      3. Sales Growth Index  (SGI)   — very high growth = risk

    Returns a proxy score. Values above -2.22 suggest manipulation risk.
    Returns None if insufficient data.
    NOTE: This is a best-effort proxy; full Beneish requires multi-year financials.
    """
    # Without multi-year data we can only approximate
    ar       = compute_accrual_ratio(inst)
    ocf      = _f(inst.operating_cashflow)
    ni       = _f(inst.net_income)
    rev      = _f(inst.revenue)
    rev_avg  = _f(inst.revenue_avg_5y)

    if ar is None:
        return None

    # Synthetic M-score proxy: start from a base and adjust
    # Base assumption: M = -3.0 (not at risk) then nudge based on signals
    m_proxy = -3.0

    # Signal 1: High accruals → push toward risk
    if   ar > 0.15:  m_proxy += 1.5
    elif ar > 0.10:  m_proxy += 0.8
    elif ar > 0.05:  m_proxy += 0.3

    # Signal 2: Poor cash conversion → push toward risk
    if ocf is not None and ni is not None and ni > 0:
        cc = ocf / ni
        if   cc < 0.5:  m_proxy += 1.0
        elif cc < 0.8:  m_proxy += 0.4

    # Signal 3: Revenue growth anomaly (rapid acceleration can signal manipulation)
    if rev is not None and rev_avg is not None and rev_avg > 0:
        sgi = rev / rev_avg
        if sgi > 1.6:   m_proxy += 0.5   # >60% growth is unusual
        elif sgi > 1.3: m_proxy += 0.2

    return round(m_proxy, 2)


def compute_earnings_quality(inst: InstrumentInput) -> tuple[Optional[float], int]:
    """
    Earnings Quality Composite (0–100) and a score nudge.

    Components:
      Accrual ratio:
        < 0        → 80 (cash > accounting earnings)
        0–0.05     → 65 (normal)
        0.05–0.10  → 50 (watch)
        > 0.10     → 30 (concern)
      Cash conversion (OCF / Net Income):
        > 1.2      → 80 (strong backing)
        0.8–1.2    → 60 (normal)
        0.5–0.8    → 40 (weak)
        < 0.5      → 20 (poor)
      Beneish proxy (if available):
        M < -2.5   → 80 (safe)
        -2.5–-2.22 → 60 (caution zone)
        > -2.22    → 20 (high risk)

    Returns (eq_score 0–100, nudge ±5).
    """
    ar  = compute_accrual_ratio(inst)
    ocf = _f(inst.operating_cashflow)
    ni  = _f(inst.net_income)
    bp  = compute_beneish_proxy(inst)

    parts = []

    if ar is not None:
        if   ar < 0:     parts.append(80)
        elif ar < 0.05:  parts.append(65)
        elif ar < 0.10:  parts.append(50)
        else:            parts.append(30)

    if ocf is not None and ni is not None and abs(ni) > 1e-9:
        cc = ocf / ni
        if   cc > 1.2:   parts.append(80)
        elif cc > 0.8:   parts.append(60)
        elif cc > 0.5:   parts.append(40)
        else:            parts.append(20)

    if bp is not None:
        if   bp < -2.5:  parts.append(80)
        elif bp < -2.22: parts.append(60)
        else:            parts.append(20)

    if not parts:
        return None, 0

    eq = sum(parts) / len(parts)

    if   eq >= 65: nudge = +5
    elif eq <= 40: nudge = -5
    else:          nudge =  0

    return round(eq, 1), nudge


def compute_normalised_earnings(inst: InstrumentInput) -> Optional[float]:
    """
    Normalised / mid-cycle earnings for cyclical companies.
    Uses 5–7 year average EBIT margin × current revenue.
    Falls back to 3-year average net income if margin history is unavailable.
    """
    rev          = _f(inst.revenue)
    margin_avg5y = _f(inst.ebit_margin_avg_5y)
    ni_avg3y     = _f(inst.net_income_avg_3y)

    if rev is not None and margin_avg5y is not None:
        return rev * margin_avg5y   # normalised EBIT

    if ni_avg3y is not None:
        return ni_avg3y   # fallback: 3-year average net income

    return None


def compute_capital_allocation_score(inst: InstrumentInput) -> Optional[float]:
    """
    Capital Allocation Score 0–100. Three components equally weighted:

    1. Shareholder yield (dividends + buybacks):
       ≥6% → 90 | 4–6% → 75 | 2–4% → 55 | 1–2% → 40 | <1% → 20

    2. FCF payout discipline (dividends / FCF):
       0–60% → 85 (sustainable) | 60–80% → 65 | 80–100% → 45 | >100% → 15

    3. Share count trend (buybacks vs dilution):
       shares declined over 3–5y → 80 (buybacks)
       stable → 55 | increased → 25 (dilution)
    """
    mkt    = _f(inst.market_cap)
    fcf    = _f(inst.free_cashflow)
    dy     = _f(inst.div_yield)         # decimal
    payout = _f(inst.payout_ratio)
    shares_now = _f(inst.shares_outstanding)
    shares_old = _f(inst.shares_3y_ago)

    parts = []

    # Component 1: shareholder yield
    if mkt and mkt > 0:
        total_yield_pct = (dy or 0.0) * 100
        if   total_yield_pct >= 6: parts.append(90)
        elif total_yield_pct >= 4: parts.append(75)
        elif total_yield_pct >= 2: parts.append(55)
        elif total_yield_pct >= 1: parts.append(40)
        else:                      parts.append(20)

    # Component 2: FCF payout discipline
    if fcf is not None and fcf > 0 and inst.net_income and inst.net_income > 0:
        # compute dividends paid = payout_ratio × net_income (or use div_yield × mkt_cap)
        divs = None
        if payout is not None:
            divs = payout * (inst.net_income or 0)
        elif dy is not None and mkt is not None:
            divs = dy * mkt
        if divs is not None:
            fcf_payout = divs / fcf
            if   fcf_payout <= 0.60: parts.append(85)
            elif fcf_payout <= 0.80: parts.append(65)
            elif fcf_payout <= 1.00: parts.append(45)
            else:                    parts.append(15)   # not covered by FCF

    # Component 3: share count trend
    if shares_now is not None and shares_old is not None and shares_old > 0:
        delta = (shares_now - shares_old) / shares_old
        if   delta <= -0.02: parts.append(80)   # buyback ≥2%
        elif delta <=  0.02: parts.append(55)   # roughly stable
        else:                parts.append(25)   # dilution

    if not parts:
        return None

    return round(sum(parts) / len(parts), 1)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5: SECTOR MEDIANS
# ══════════════════════════════════════════════════════════════════════════════

SECTOR_MEDIAN_KEYS = [
    "ev_ebitda", "ev_ebit", "pe", "pb", "div_yield", "roe", "pfcf",
    "de", "roic", "price_to_book",
]


def build_sector_medians(instruments: list[InstrumentInput]) -> dict[str, dict[str, float]]:
    """
    Compute per-sector medians for all key valuation metrics.
    Returns {sector: {metric: median}}.
    Only stocks with valid (non-None, positive) values contribute to medians.
    """
    buckets: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))

    def _med(vals: list[float]) -> float:
        s = sorted(v for v in vals if v is not None)
        n = len(s)
        if n == 0:
            return None
        return s[n // 2] if n % 2 == 1 else (s[n // 2 - 1] + s[n // 2]) / 2

    for inst in instruments:
        if inst.asset_class != "Stock":
            continue
        s = inst.sector or "Unknown"

        # Valuation multiples
        for key, val in [
            ("ev_ebitda",    _f(inst.ev_ebitda)),
            ("ev_ebit",      _f(inst.ev_ebit)),
            ("pe",           _f(inst.pe)),
            ("pb",           _f(inst.pb)),
            ("div_yield",    _f(inst.div_yield)),
            ("roe",          _f(inst.roe)),
            ("price_to_book",_f(inst.pb)),
        ]:
            if val is not None and val > 0:
                buckets[s][key].append(val)

        # P/FCF (derived)
        mc = _f(inst.market_cap)
        fc = _f(inst.free_cashflow)
        if mc and fc and fc > 0:
            buckets[s]["pfcf"].append(mc / fc)

        # D/E
        de = _f(inst.total_debt)
        eq = _f(inst.book_equity)
        if de is not None and eq and eq > 0:
            buckets[s]["de"].append(de / eq)

        # ROIC
        roic = compute_roic(inst)
        if roic is not None and roic > 0:
            buckets[s]["roic"].append(roic)

    result = {}
    for sector, metrics in buckets.items():
        result[sector] = {k: _med(v) for k, v in metrics.items() if _med(v) is not None}

    return result


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6: SCORING — NON-FINANCIAL STOCKS
# ══════════════════════════════════════════════════════════════════════════════

def _is_cyclical(inst: InstrumentInput, cfg: dict) -> bool:
    return inst.is_cyclical or (inst.sector in cfg.get("cyclical_sectors", set()))


def _is_financial(inst: InstrumentInput, cfg: dict) -> bool:
    return inst.sector in cfg.get("financial_sectors", set())


def _weighted_score(components: list[tuple[Optional[float], float]]) -> tuple[float, float, float]:
    """
    Given [(score, weight), ...], return (weighted_avg, used_weight, total_weight).
    Scores of None are skipped (weight not included in denominator).
    """
    total_wt  = sum(w for _, w in components)
    used_wt   = sum(w for s, w in components if s is not None)
    w_sum     = sum(s * w for s, w in components if s is not None)
    if used_wt == 0:
        return 50.0, 0.0, total_wt
    return w_sum / used_wt, used_wt, total_wt


def score_stock(
    inst: InstrumentInput,
    sector_medians: dict,
    cfg: dict = CONFIG,
) -> dict:
    """
    Score a non-financial stock using the full multi-factor model.
    Returns a detailed result dict.
    """
    sector = inst.sector or "Unknown"
    sm     = sector_medians.get(sector, {})
    w      = dict(cfg["weights_stock"])   # copy — may be modified for cyclicals
    sens   = cfg["sensitivity"]
    filt   = cfg["filters"]

    # ── Cyclical weight override ──────────────────────────────────────────────
    is_cyc = _is_cyclical(inst, cfg)
    if is_cyc:
        for k, delta in cfg["weights_stock_cyclical_delta"].items():
            if k in w:
                w[k] = max(0, w[k] + delta)

    # ── Derived metrics ───────────────────────────────────────────────────────
    mc      = _f(inst.market_cap)
    fcf     = _f(inst.free_cashflow)
    p_fcf   = (mc / fcf) if (mc and fcf and fcf > 0) else None

    # Normalised earnings for cyclicals
    norm_earn = None
    if is_cyc:
        norm_earn = compute_normalised_earnings(inst)

    # EV/Earnings: prefer EV/EBIT; fall back to EV/EBITDA; for cyclicals use normalised
    ev_earn  = None
    ev_label = "ev_ebitda"
    if norm_earn is not None and _f(inst.ev) is not None and norm_earn > 0:
        ev_earn  = inst.ev / norm_earn
        ev_label = "ev_normalised"
        sm_ev    = sm.get("ev_ebit") or sm.get("ev_ebitda")
    elif _f(inst.ev_ebit) is not None and inst.ev_ebit > 0:
        ev_earn  = _f(inst.ev_ebit)
        ev_label = "ev_ebit"
        sm_ev    = sm.get("ev_ebit") or sm.get("ev_ebitda")
    else:
        ev_earn  = _f(inst.ev_ebitda)
        ev_label = "ev_ebitda"
        sm_ev    = sm.get("ev_ebitda")

    roic = compute_roic(inst)
    eq_score, eq_nudge = compute_earnings_quality(inst)
    ca_score = compute_capital_allocation_score(inst)

    # ── Factor scores ─────────────────────────────────────────────────────────
    s_ev    = _sigmoid_score(ev_earn,  sm_ev,              lower_is_better=True,  sensitivity=sens["ev_earnings"])
    s_fcf   = _sigmoid_score(p_fcf,   sm.get("pfcf"),      lower_is_better=True,  sensitivity=sens["fcf_yield"])
    s_pe    = _sigmoid_score(_f(inst.pe), sm.get("pe"),    lower_is_better=True,  sensitivity=sens["pe"])
    s_pb    = _sigmoid_score(_f(inst.pb), sm.get("pb"),    lower_is_better=True,  sensitivity=sens["pb"])
    s_roic  = _sigmoid_score(roic,    sm.get("roic"),      lower_is_better=False, sensitivity=sens["roic"])
    # Absolute ROIC fallback when no sector median exists
    if s_roic is None and roic is not None:
        if   roic >= 0.20: s_roic = 90
        elif roic >= 0.15: s_roic = 75
        elif roic >= 0.10: s_roic = 60
        elif roic >= 0.05: s_roic = 45
        else:              s_roic = 25
    # ROIC vs WACC penalty: below WACC proxy = capital destroyer
    wacc = cfg.get("wacc_proxy", 0.08)
    if roic is not None and roic < wacc and s_roic is not None:
        s_roic = max(0.0, s_roic - 15)

    s_eq    = eq_score   # 0–100 composite (already computed above)

    # Momentum: 12M return (exclude last month to avoid reversal bias)
    # Use return_1y; if return_1m available, approximate 11M by subtracting last month
    r12 = _f(inst.return_1y)
    r1  = _f(inst.return_1m)
    if r12 is not None and r1 is not None:
        # approximate 1M-ex return
        r12 = (1 + r12) / (1 + r1) - 1 if abs(1 + r1) > 1e-9 else r12
    s_mom = (_clamp(50.0 + r12 * 166.7) if r12 is not None else None)

    s_ca = ca_score   # 0–100 already

    # ── Weighted average ──────────────────────────────────────────────────────
    components = [
        (s_ev,  w["ev_earnings"]),
        (s_fcf, w["fcf_yield"]),
        (s_pe,  w["pe"]),
        (s_pb,  w["pb"]),
        (s_roic, w["roic"]),
        (s_eq,  w["earnings_quality"]),
        (s_mom, w["momentum"]),
        (s_ca,  w["capital_allocation"]),
    ]
    raw_score, used_wt, total_wt = _weighted_score(components)
    coverage = used_wt / total_wt if total_wt > 0 else 0.0

    # Missing data: shade toward neutral
    sector_rel_score = raw_score * coverage + 50.0 * (1.0 - coverage)

    # ── Apply earnings quality nudge ──────────────────────────────────────────
    sector_rel_score = _clamp(sector_rel_score + eq_nudge)

    # ── HARD FILTERS & PENALTIES ──────────────────────────────────────────────
    penalties = []
    flags     = []

    # Altman Z-Score
    z = compute_altman_z(inst)
    if z is not None:
        if z < filt["altman_z_distress"]:
            sector_rel_score = min(sector_rel_score, 40.0)
            flags.append({"type": "distress", "label": f"⚠ Distress (Z={z:.1f})",
                          "detail": "Altman Z below 1.8 — high bankruptcy risk"})
        elif z < filt["altman_z_grey"]:
            flags.append({"type": "grey_zone", "label": f"○ Z grey zone ({z:.1f})",
                          "detail": "Altman Z 1.8–3.0 — monitor closely"})

    # Leverage vs sector
    de = (_f(inst.total_debt) / _f(inst.book_equity)) if (
        _f(inst.book_equity) and _f(inst.book_equity) > 0 and _f(inst.total_debt) is not None
    ) else None
    sm_de = sm.get("de")
    if de is not None and sm_de and sm_de > 0 and de > sm_de * filt["de_vs_sector_penalty_ratio"]:
        p = filt["de_leverage_penalty"]
        sector_rel_score = _clamp(sector_rel_score - p)
        penalties.append(f"High leverage penalty −{p}pts (D/E {de:.1f}x vs sector {sm_de:.1f}x)")

    # Earnings manipulation proxy
    bp = compute_beneish_proxy(inst)
    if bp is not None and bp > filt["beneish_m_threshold"]:
        p = filt["manipulation_penalty"]
        sector_rel_score = _clamp(sector_rel_score - p)
        penalties.append(f"Manipulation risk penalty −{p}pts (M-proxy {bp:.2f})")
        flags.append({"type": "manipulation", "label": f"⚠ Manipulation risk (M={bp:.2f})",
                      "detail": "Beneish proxy above -2.22 — review carefully"})

    # Accrual ratio standalone check
    ar = compute_accrual_ratio(inst)
    if ar is not None and ar > filt["accrual_high"]:
        p = filt["accrual_penalty"]
        sector_rel_score = _clamp(sector_rel_score - p)
        penalties.append(f"Accrual penalty −{p}pts (ratio {ar:.2f})")
        flags.append({"type": "accruals", "label": f"⚠ Earnings quality ({ar:+.2f})",
                      "detail": f"Accrual ratio {ar:.2f} — paper profits exceed cash"})

    # Regulatory / ESG / Litigation flags
    if inst.regulatory_flag or inst.litigation_flag or inst.esg_controversy:
        sev = inst.flag_severity.lower()
        p = filt.get(f"flag_penalty_{sev}", filt["flag_penalty_medium"])
        sector_rel_score = _clamp(sector_rel_score - p)
        penalties.append(f"Regulatory/ESG/Litigation penalty −{p}pts (severity: {sev})")
        flags.append({"type": "regulatory", "label": "⚠ Regulatory/ESG overhang",
                      "detail": f"Severity: {sev}"})

    # Goodwill impairment
    gw      = _f(inst.goodwill)
    gw_imp  = _f(inst.goodwill_impairment_3y)
    bk_eq   = _f(inst.book_equity)
    if gw and gw_imp and bk_eq and bk_eq > 0:
        if gw_imp / bk_eq > filt["goodwill_impairment_pct"]:
            p = filt["goodwill_penalty"]
            sector_rel_score = _clamp(sector_rel_score - p)
            penalties.append(f"Goodwill impairment penalty −{p}pts")
            flags.append({"type": "goodwill", "label": "⚠ Goodwill impairment",
                          "detail": f"Impaired {gw_imp:,.0f} ({gw_imp/bk_eq*100:.1f}% of equity)"})

    sector_rel_score = _clamp(sector_rel_score)

    return {
        "sector_relative_score": round(sector_rel_score, 1),
        "score_components": {
            "ev_earnings_score":      s_ev,
            "fcf_yield_score":        s_fcf,
            "pe_score":               s_pe,
            "pb_score":               s_pb,
            "roic_score":             s_roic,
            "earnings_quality_score": s_eq,
            "momentum_score":         s_mom,
            "capital_allocation_score": s_ca,
            "ev_metric_used":         ev_label,
        },
        "derived": {
            "roic":           roic,
            "p_fcf":          p_fcf,
            "altman_z":       z,
            "accrual_ratio":  ar,
            "beneish_proxy":  bp,
            "eq_score":       eq_score,
            "eq_nudge":       eq_nudge,
            "ca_score":       ca_score,
            "normalised_earn": norm_earn,
            "is_cyclical":    is_cyc,
            "de_ratio":       de,
        },
        "penalties":       penalties,
        "flags":           flags,
        "score_coverage":  round(coverage, 3),
    }


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7: SCORING — FINANCIALS
# ══════════════════════════════════════════════════════════════════════════════

def _asset_quality_composite(inst: InstrumentInput) -> Optional[float]:
    """
    Asset quality score 0–100 for banks/insurers.
    Components: NPL ratio trend, loan loss coverage, Tier 1 capital.
    """
    parts = []

    # Tier 1 capital ratio: ≥12% → 85 | 10-12% → 65 | 8-10% → 45 | <8% → 20
    t1 = _f(inst.tier1_capital_ratio)
    if t1 is not None:
        if   t1 >= 0.14: parts.append(90)
        elif t1 >= 0.12: parts.append(75)
        elif t1 >= 0.10: parts.append(60)
        elif t1 >= 0.08: parts.append(40)
        else:            parts.append(20)

    # NPL ratio: lower is better; trend matters more
    npl = _f(inst.npl_ratio)
    if npl is not None:
        if   npl <= 0.01: parts.append(90)
        elif npl <= 0.03: parts.append(70)
        elif npl <= 0.06: parts.append(45)
        else:             parts.append(20)

    # NPL trend adjustment
    if inst.npl_trend:
        trend_adj = {"improving": +10, "stable": 0, "deteriorating": -15}
        t = trend_adj.get(inst.npl_trend.lower(), 0)
        if parts:
            parts[-1] = _clamp(parts[-1] + t)   # adjust last npl score

    # Loan loss coverage: ≥1.5× → 85 | 1.0–1.5 → 65 | <1.0 → 35
    llc = _f(inst.loan_loss_coverage)
    if llc is not None:
        if   llc >= 1.5: parts.append(85)
        elif llc >= 1.0: parts.append(65)
        else:            parts.append(35)

    if not parts:
        return None

    return round(sum(parts) / len(parts), 1)


def score_financial(
    inst: InstrumentInput,
    sector_medians: dict,
    cfg: dict = CONFIG,
) -> dict:
    """Score a bank, insurer, or asset manager."""
    sector = inst.sector or "Unknown"
    sm     = sector_medians.get(sector, {})
    w      = cfg["weights_financial"]
    sens   = cfg["sensitivity"]
    filt   = cfg["filters"]

    # Factor scores
    s_pb    = _sigmoid_score(_f(inst.pb), sm.get("pb") or sm.get("price_to_book"),
                              lower_is_better=True, sensitivity=sens["ptb_financial"])

    roe_pct    = (_f(inst.roe) * 100) if _f(inst.roe) is not None else None
    sm_roe_pct = (sm.get("roe") * 100) if sm.get("roe") is not None else None
    s_roe   = _sigmoid_score(roe_pct, sm_roe_pct, lower_is_better=False, sensitivity=sens["roe"])

    dy_pct  = (_f(inst.div_yield) * 100) if _f(inst.div_yield) is not None else None
    sm_dy_pct = (sm.get("div_yield") * 100) if sm.get("div_yield") is not None else None
    s_dy    = _sigmoid_score(dy_pct,   sm_dy_pct, lower_is_better=False, sensitivity=sens["div_yield"])

    # Dividend stability: reward consistency, penalise recent cuts
    # Encoded as simple rule (would need multi-year dividend history for full scoring)
    s_divstab = None
    if inst.payout_ratio is not None:
        pr = _f(inst.payout_ratio)
        if pr is not None:
            if   pr <= 0.50: s_divstab = 75   # conservative, plenty of cover
            elif pr <= 0.75: s_divstab = 60
            elif pr <= 1.00: s_divstab = 40
            else:            s_divstab = 15   # paying more than earns

    # Momentum
    r12 = _f(inst.return_1y)
    r1  = _f(inst.return_1m)
    if r12 is not None and r1 is not None:
        r12 = (1 + r12) / (1 + r1) - 1 if abs(1 + r1) > 1e-9 else r12
    s_mom = (_clamp(50.0 + r12 * 166.7) if r12 is not None else None)

    # Asset quality composite
    aq_score = _asset_quality_composite(inst)

    components = [
        (s_pb,     w["pb"]),
        (s_roe,    w["roe"]),
        (s_dy,     w["div_yield"]),
        (s_divstab, w["div_stability"]),
        (s_mom,    w["momentum"]),
        (aq_score, w["asset_quality"]),
    ]
    raw_score, used_wt, total_wt = _weighted_score(components)
    coverage = used_wt / total_wt if total_wt > 0 else 0.0
    sector_rel_score = raw_score * coverage + 50.0 * (1.0 - coverage)

    penalties = []
    flags     = []

    # Special: bank trading below book with deteriorating asset quality
    pb = _f(inst.pb)
    if pb is not None and pb < 1.0 and inst.npl_trend == "deteriorating":
        p = filt["bank_below_book_with_bad_quality_penalty"]
        sector_rel_score = _clamp(sector_rel_score - p)
        penalties.append(f"P/B<1 + deteriorating assets penalty −{p}pts")
        flags.append({"type": "value_trap_bank",
                      "label": "⚠ Cheap bank but deteriorating loans",
                      "detail": "P/B<1 combined with rising NPLs — classic bank value trap"})

    # Accrual flag (unusual for banks but still check)
    ar = compute_accrual_ratio(inst)
    if ar is not None and ar > filt["accrual_high"]:
        p = filt["accrual_penalty"]
        sector_rel_score = _clamp(sector_rel_score - p)
        penalties.append(f"Accrual penalty −{p}pts")
        flags.append({"type": "accruals", "label": f"⚠ Accrual concern ({ar:+.2f})"})

    # Regulatory flag
    if inst.regulatory_flag or inst.litigation_flag:
        sev = inst.flag_severity.lower()
        p   = filt.get(f"flag_penalty_{sev}", filt["flag_penalty_medium"])
        sector_rel_score = _clamp(sector_rel_score - p)
        penalties.append(f"Regulatory penalty −{p}pts (severity: {sev})")
        flags.append({"type": "regulatory", "label": "⚠ Regulatory/litigation overhang"})

    sector_rel_score = _clamp(sector_rel_score)

    return {
        "sector_relative_score": round(sector_rel_score, 1),
        "score_components": {
            "pb_score":             s_pb,
            "roe_score":            s_roe,
            "div_yield_score":      s_dy,
            "div_stability_score":  s_divstab,
            "momentum_score":       s_mom,
            "asset_quality_score":  aq_score,
        },
        "derived": {
            "accrual_ratio":  ar,
            "roe_pct":        roe_pct,
            "asset_quality":  aq_score,
            "is_financial":   True,
        },
        "penalties":       penalties,
        "flags":           flags,
        "score_coverage":  round(coverage, 3),
    }


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8: SCORING — ETFs & MONEY MARKET FUNDS
# ══════════════════════════════════════════════════════════════════════════════

def score_etf(inst: InstrumentInput, cfg: dict = CONFIG) -> dict:
    """Score an ETF on AUM, TER, performance, momentum."""
    w = cfg["weights_etf"]

    def _s_aum(v):
        if v is None or v <= 0: return None
        return _clamp((math.log10(v / 1e7)) / math.log10(1000) * 100)

    def _s_ter(v):
        if v is None: return None
        return _clamp(100 - (v / 0.015) * 100)   # 0% → 100, 1.5% → 0

    def _s_perf(v1y, v3y):
        if v1y is None and v3y is None: return None
        parts = []
        if v1y is not None: parts.append(_clamp(50 + v1y * 250))  # +20% → 100
        if v3y is not None: parts.append(_clamp(50 + v3y / 3 * 250))  # annualised
        return sum(parts) / len(parts)

    def _s_mom(v):
        if v is None: return None
        return _clamp(50 + v * 300)

    s_aum  = _s_aum(_f(inst.aum))
    s_ter  = _s_ter(_f(inst.ter))
    s_perf = _s_perf(_f(inst.return_1y), _f(inst.return_3y))
    s_mom  = _s_mom(_f(inst.return_3m))

    # Optional: tracking error subfactor (replaces part of performance weight if available)
    te = _f(inst.tracking_error)
    te_score = None
    if te is not None:
        te_score = _clamp(100 - te * 2000)   # 0% → 100, 5% → 0

    components = [
        (s_aum,  w["aum"]),
        (s_ter,  w["ter"]),
        (s_perf if te_score is None else (s_perf or 50) * 0.5 + te_score * 0.5,
         w["performance"]),
        (s_mom,  w["momentum"]),
    ]
    raw, used, total = _weighted_score(components)
    coverage = used / total if total > 0 else 0.0
    score = _clamp(raw * coverage + 50.0 * (1.0 - coverage))

    return {
        "sector_relative_score": round(score, 1),
        "score_components": {
            "aum_score":         s_aum,
            "ter_score":         s_ter,
            "performance_score": s_perf,
            "momentum_score":    s_mom,
            "tracking_error_score": te_score,
        },
        "score_coverage":  round(coverage, 3),
        "penalties":       [],
        "flags":           [],
    }


def score_money_market(inst: InstrumentInput, cfg: dict = CONFIG) -> dict:
    """Score a money market fund on yield, AUM, fees."""
    w = cfg["weights_money_market"]

    def _s_yield(v):
        if v is None: return None
        pct = v * 100 if abs(v) <= 1 else v   # normalise to %
        return _clamp(pct / 5.0 * 100)        # 5%+ → 100, 0% → 0

    def _s_aum(v):
        if v is None or v <= 0: return None
        return _clamp(math.log10(max(v, 1e6) / 1e6) / 4 * 100)

    def _s_fee(v):
        if v is None: return None
        pct = v * 100 if abs(v) <= 1 else v
        return _clamp(100 - (pct / 0.5) * 100)  # 0% → 100, 0.5%+ → 0

    yield_val = _f(inst.yield_7d) or _f(inst.div_yield)
    s_y = _s_yield(yield_val)
    s_a = _s_aum(_f(inst.aum))
    s_f = _s_fee(_f(inst.ter))

    components = [(s_y, w["yield"]), (s_a, w["aum"]), (s_f, w["fees"])]
    raw, used, total = _weighted_score(components)
    coverage = used / total if total > 0 else 0.0
    score = _clamp(raw * coverage + 50.0 * (1.0 - coverage))

    return {
        "sector_relative_score": round(score, 1),
        "score_components": {
            "yield_score":  s_y,
            "aum_score":    s_a,
            "fee_score":    s_f,
        },
        "score_coverage":  round(coverage, 3),
        "penalties":       [],
        "flags":           [],
    }


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 9: DATA COMPLETENESS
# ══════════════════════════════════════════════════════════════════════════════

REQUIRED_FIELDS_STOCK = [
    "market_cap", "revenue", "ebit", "net_income", "operating_cashflow",
    "free_cashflow", "total_assets", "total_debt", "book_equity",
    "pe", "pb", "ev_ebitda", "return_1y",
]
REQUIRED_FIELDS_FINANCIAL = [
    "market_cap", "pb", "roe", "div_yield", "return_1y",
    "tier1_capital_ratio", "npl_ratio", "total_assets",
]
REQUIRED_FIELDS_ETF        = ["aum", "ter", "return_1y"]
REQUIRED_FIELDS_MONEY_MKT  = ["yield_7d", "aum", "ter"]


def compute_data_completeness(inst: InstrumentInput) -> tuple[float, str, int]:
    """
    Returns (completeness_ratio, flag_label, penalty_points).
    completeness_ratio: 0.0–1.0
    flag_label: "" | "Limited Data" | "Limited Data – High Uncertainty" | "Insufficient Data"
    penalty_points: 0 | 5 | 10 | None (None = not scored)
    """
    ac = inst.asset_class
    if ac == "ETF":
        required = REQUIRED_FIELDS_ETF
    elif ac == "Money Market":
        required = REQUIRED_FIELDS_MONEY_MKT
    elif inst.sector in CONFIG["financial_sectors"]:
        required = REQUIRED_FIELDS_FINANCIAL
    else:
        required = REQUIRED_FIELDS_STOCK

    present = sum(1 for f in required if getattr(inst, f, None) is not None)
    ratio   = present / len(required) if required else 1.0

    dc = CONFIG["data_completeness"]

    if ratio >= dc["threshold_full"]:
        return ratio, "", 0
    elif ratio >= dc["threshold_limited"]:
        return ratio, "Limited Data", dc["penalty_limited"]
    elif ratio >= dc["threshold_uncertain"]:
        return ratio, "Limited Data – High Uncertainty", dc["penalty_uncertain"]
    else:
        return ratio, "Insufficient Data", None   # None = do not score


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 10: CROSS-MARKET SECTOR ADJUSTMENT
# ══════════════════════════════════════════════════════════════════════════════

def compute_cross_market_adjustment(
    sector: str,
    sector_medians: dict,
    global_pe_median: Optional[float],
    cfg: dict = CONFIG,
) -> float:
    """
    Compare sector median P/E to global median P/E.
    Returns an adjustment in range [-max_adj, +max_adj].
    """
    cm     = cfg["cross_market"]
    max_a  = cm["max_adjustment"]
    base_a = cm["base_adjustment"]

    if global_pe_median is None or global_pe_median <= 0:
        return 0.0

    sector_pe = sector_medians.get(sector, {}).get("pe")
    if sector_pe is None or sector_pe <= 0:
        return 0.0

    ratio = sector_pe / global_pe_median

    if   ratio >= cm["sector_premium_threshold"]:
        # Sector overvalued vs market
        overshoot = ratio - cm["sector_premium_threshold"]
        adj = -(base_a + min(overshoot * 20, max_a - base_a))
    elif ratio <= cm["sector_discount_threshold"]:
        # Sector undervalued vs market
        undershoot = cm["sector_discount_threshold"] - ratio
        adj = +(base_a + min(undershoot * 20, max_a - base_a))
    else:
        adj = 0.0

    return round(_clamp(adj, -max_a, max_a), 1)


def compute_global_pe_median(sector_medians: dict) -> Optional[float]:
    """Compute the global (cross-sector) P/E median from all sector medians."""
    pes = [v["pe"] for v in sector_medians.values() if v.get("pe")]
    if not pes:
        return None
    return statistics.median(pes)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 11: LABELS
# ══════════════════════════════════════════════════════════════════════════════

def score_label(score: Optional[float]) -> str:
    if score is None: return "Not Scored"
    s = float(score)
    if s >= 80: return "Strong Buy"
    if s >= 65: return "Buy"
    if s >= 50: return "Watch"
    if s >= 35: return "Avoid"
    return "Strong Avoid"


def score_colour(score: Optional[float]) -> str:
    if score is None: return "#6B7D92"
    s = float(score)
    if s >= 80: return "#1E5C38"
    if s >= 65: return "#2A6B44"
    if s >= 50: return "#9B6B1A"
    if s >= 35: return "#B85C20"
    return "#8B2635"


def score_bg(score: Optional[float]) -> str:
    if score is None: return "#F4F1EC"
    s = float(score)
    if s >= 80: return "#D6EDDF"
    if s >= 65: return "#EAF3EE"
    if s >= 50: return "#FBF3E4"
    if s >= 35: return "#FAE8DC"
    return "#F5D8DB"


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 12: TOP-LEVEL SCORING ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def score_instrument(
    inst: InstrumentInput,
    sector_medians: dict,
    global_pe_median: Optional[float] = None,
    cfg: dict = CONFIG,
) -> dict:
    """
    Score a single instrument. Returns a full result dict containing:
      - sector_relative_score (0–100)
      - cross_market_adjusted_score (0–100)
      - label
      - score_components (factor breakdown)
      - penalties / flags
      - data_completeness_ratio, data_flag, data_penalty
    """

    # ── Data completeness check ───────────────────────────────────────────────
    completeness, data_flag, data_penalty = compute_data_completeness(inst)
    if data_penalty is None:
        # Insufficient data — return placeholder
        return {
            "ticker":                     inst.ticker,
            "name":                       inst.name,
            "sector":                     inst.sector,
            "asset_class":                inst.asset_class,
            "sector_relative_score":      None,
            "cross_market_adjusted_score": None,
            "label":                      "Not Scored",
            "data_completeness_ratio":    round(completeness, 3),
            "data_flag":                  data_flag,
            "data_penalty":               data_penalty,
            "score_components":           {},
            "score_coverage":             0.0,
            "derived":                    {},
            "penalties":                  ["Insufficient Data — not scored"],
            "flags":                      [],
        }

    # ── Route to correct scorer ───────────────────────────────────────────────
    ac = inst.asset_class
    if ac == "ETF":
        raw = score_etf(inst, cfg)
    elif ac == "Money Market":
        raw = score_money_market(inst, cfg)
    elif _is_financial(inst, cfg):
        raw = score_financial(inst, sector_medians, cfg)
    else:
        raw = score_stock(inst, sector_medians, cfg)

    sr_score = raw["sector_relative_score"]

    # ── Data completeness penalty ─────────────────────────────────────────────
    if data_penalty and data_penalty > 0:
        sr_score = _clamp(sr_score - data_penalty)

    # ── Cross-market adjustment ───────────────────────────────────────────────
    cm_adj   = compute_cross_market_adjustment(inst.sector, sector_medians, global_pe_median, cfg)
    cm_score = _clamp(sr_score + cm_adj)

    label = score_label(cm_score)

    return {
        "ticker":                     inst.ticker,
        "name":                       inst.name,
        "sector":                     inst.sector,
        "industry":                   inst.industry,
        "asset_class":                inst.asset_class,
        "sector_relative_score":      round(sr_score, 1),
        "cross_market_adjusted_score": round(cm_score, 1),
        "cross_market_adj":           cm_adj,
        "label":                      label,
        "label_colour":               score_colour(cm_score),
        "data_completeness_ratio":    round(completeness, 3),
        "data_flag":                  data_flag,
        "data_penalty":               data_penalty,
        "score_components":           raw.get("score_components", {}),
        "derived":                    raw.get("derived", {}),
        "penalties":                  raw.get("penalties", []),
        "flags":                      raw.get("flags", []),
        "score_coverage":             raw.get("score_coverage", 0.0),
    }


def score_instruments(
    as_of_date: date,
    universe: list[InstrumentInput],
    raw_data_snapshot: Optional[dict] = None,
    cfg: dict = CONFIG,
) -> dict:
    """
    Backtest-ready entry point.

    Parameters
    ----------
    as_of_date        : date — scoring date (ensures no look-ahead if snapshot
                        contains only data available at that date)
    universe          : list of InstrumentInput records
    raw_data_snapshot : optional dict of {ticker: raw_dict} — if provided,
                        instruments are hydrated from it (for backtesting)
    cfg               : config dict

    Returns
    -------
    {
      "as_of_date": date,
      "scores": [result_dict, ...],
      "sector_medians": {sector: {metric: median}},
      "global_pe_median": float,
      "diagnostics": {
          "n_scored": int,
          "n_not_scored": int,
          "n_strong_buy": int,
          ...
      }
    }
    """
    # Hydrate from snapshot if provided
    if raw_data_snapshot:
        universe = _hydrate_from_snapshot(universe, raw_data_snapshot)

    sector_medians   = build_sector_medians(universe)
    global_pe_median = compute_global_pe_median(sector_medians)

    results = [
        score_instrument(inst, sector_medians, global_pe_median, cfg)
        for inst in universe
    ]

    # Diagnostics
    scored = [r for r in results if r["sector_relative_score"] is not None]
    label_counts = defaultdict(int)
    for r in scored:
        label_counts[r["label"]] += 1

    diagnostics = {
        "n_total":       len(results),
        "n_scored":      len(scored),
        "n_not_scored":  len(results) - len(scored),
        "label_counts":  dict(label_counts),
        "avg_score":     round(statistics.mean(r["cross_market_adjusted_score"]
                               for r in scored), 1) if scored else None,
    }

    return {
        "as_of_date":       as_of_date,
        "scores":           results,
        "sector_medians":   sector_medians,
        "global_pe_median": global_pe_median,
        "diagnostics":      diagnostics,
    }


def _hydrate_from_snapshot(
    universe: list[InstrumentInput],
    snapshot: dict,
) -> list[InstrumentInput]:
    """
    Merge snapshot raw_dict fields onto InstrumentInput records.
    Snapshot keys follow yfinance-style names; we map them to schema fields.
    This allows backtesting with historical data snapshots.
    """
    KEY_MAP = {
        "marketCap":              "market_cap",
        "trailingPE":             "pe",
        "forwardPE":              "pe",
        "priceToBook":            "pb",
        "enterpriseToEbitda":     "ev_ebitda",
        "enterpriseToEbit":       "ev_ebit",
        "enterpriseValue":        "ev",
        "returnOnEquity":         "roe",
        "freeCashflow":           "free_cashflow",
        "operatingCashflow":      "operating_cashflow",
        "totalDebt":              "total_debt",
        "totalAssets":            "total_assets",
        "totalEquity":            "book_equity",
        "cash":                   "cash",
        "netIncome":              "net_income",
        "totalRevenue":           "revenue",
        "ebit":                   "ebit",
        "ebitda":                 "ebitda",
        "dividendYield":          "div_yield",
        "payoutRatio":            "payout_ratio",
        "sharesOutstanding":      "shares_outstanding",
        "annualReportExpenseRatio": "ter",
        "totalAssets":            "aum",   # for ETFs
        "fiftyTwoWeekReturn":     "return_1y",
    }

    updated = []
    for inst in universe:
        raw = snapshot.get(inst.ticker, {})
        if not raw:
            updated.append(inst)
            continue
        d = {v: raw[k] for k, v in KEY_MAP.items() if k in raw}
        for field_name, val in d.items():
            if hasattr(inst, field_name) and val is not None:
                try:
                    object.__setattr__(inst, field_name, float(val))
                except (TypeError, ValueError):
                    pass
        updated.append(inst)
    return updated


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 13: BACKWARD-COMPATIBLE BRIDGE (drop-in for existing scoring.py API)
# ══════════════════════════════════════════════════════════════════════════════

def _inst_from_dict(d: dict) -> InstrumentInput:
    """
    Convert a legacy raw-dict (yfinance-style, from fetcher.py) to InstrumentInput.
    Allows the new engine to be called from existing app.py / score_all() callers.
    """
    def _g(k1, *aliases):
        for k in [k1, *aliases]:
            v = _f(d.get(k))
            if v is not None:
                return v
        return None

    mc  = _g("market_cap", "marketCap")
    fcf = _g("free_cashflow", "freeCashflow")
    de  = _g("debt_to_equity", "debtToEquity")  # already normalised in fetcher

    fin_sectors = CONFIG["financial_sectors"]
    sector = d.get("sector", "") or ""

    # Compute book_equity from D/E and total_debt if not directly available
    book_eq = _g("total_equity", "book_equity")
    td      = _g("total_debt", "totalDebt")
    if book_eq is None and de is not None and td is not None and de > 0:
        book_eq = td / de

    return InstrumentInput(
        ticker          = d.get("ticker", d.get("symbol", "")),
        name            = d.get("name", d.get("longName", "")),
        sector          = sector,
        industry        = d.get("industry", ""),
        asset_class     = d.get("asset_class", "Stock"),
        country         = d.get("country", ""),
        exchange        = d.get("exchange", ""),
        price           = _g("price", "currentPrice", "regularMarketPrice"),
        market_cap      = mc,
        return_1y       = _g("return_1y", "yr1_pct", "fiftyTwoWeekReturn"),
        return_6m       = _g("return_6m"),
        return_3m       = _g("return_3m"),
        return_1m       = _g("return_1m"),
        revenue         = _g("revenue", "total_revenue", "totalRevenue"),
        ebitda          = _g("ebitda", "EBITDA"),
        ebit            = _g("ebit", "EBIT"),
        net_income      = _g("net_income", "netIncome"),
        operating_cashflow = _g("operating_cashflow", "operatingCashflow"),
        free_cashflow   = fcf,
        capex           = _g("capex_1y"),
        total_assets    = _g("total_assets", "totalAssets"),
        current_assets  = _g("current_assets", "currentAssets"),
        current_liabilities = _g("current_liabilities", "currentLiabilities"),
        total_debt      = td,
        cash            = _g("total_cash", "cash", "cashAndCashEquivalents"),
        book_equity     = book_eq,
        goodwill        = _g("goodwill"),
        retained_earnings = _g("retained_earnings", "retainedEarnings"),
        pe              = _g("pe", "trailingPE", "forwardPE"),
        pb              = _g("pb", "price_to_book", "priceToBook"),
        ev_ebitda       = _g("ev_ebitda", "enterpriseToEbitda"),
        ev_ebit         = _g("ev_ebit", "enterpriseToEbit"),
        ev              = _g("ev", "enterpriseValue"),
        div_yield       = _g("div_yield", "dividendYield"),
        payout_ratio    = _g("payout_ratio", "payoutRatio"),
        shares_outstanding = _g("shares_outstanding", "sharesOutstanding"),
        roe             = _g("roe", "returnOnEquity"),
        roa             = _g("roa", "returnOnAssets"),
        effective_tax_rate = _g("effective_tax_rate", "effectiveTaxRate"),
        net_income_avg_3y = _g("net_income_avg_3y"),
        revenue_avg_5y  = _g("revenue_avg_5y"),
        ebit_margin_avg_5y = _g("ebit_margin_avg_5y"),
        aum             = _g("aum", "totalAssets") if d.get("asset_class") in ("ETF", "Money Market") else None,
        ter             = _g("ter", "annualReportExpenseRatio"),
        return_3y       = _g("return_3y"),
        yield_7d        = _g("div_yield", "dividendYield"),   # MMF: same field
        regulatory_flag = bool(d.get("regulatory_flag", False)),
        litigation_flag = bool(d.get("litigation_flag", False)),
        esg_controversy = bool(d.get("esg_controversy", False)),
        flag_severity   = d.get("flag_severity", "low"),
        # Financial-specific
        tier1_capital_ratio = _g("tier1_capital_ratio"),
        npl_ratio           = _g("npl_ratio"),
        loan_loss_coverage  = _g("loan_loss_coverage"),
        npl_trend           = d.get("npl_trend"),
        goodwill_impairment_3y = _g("goodwill_impairment_3y"),
        currency            = d.get("currency", ""),
    )


def score_all(
    instruments: list[dict],
    sector_medians: dict,
    quality_thresholds: Optional[dict] = None,
    weights: Optional[dict] = None,
) -> list[dict]:
    """
    Drop-in replacement for the old score_all() API.
    Accepts list of raw dicts (yfinance format), returns enriched dicts
    with 'score', 'score_components', 'risk_flags' etc — same shape as before,
    plus new fields from the full engine.
    """
    cfg = CONFIG
    if weights:
        # Merge custom weights into config copy
        cfg = dict(CONFIG)
        cfg["weights_stock"] = {**CONFIG["weights_stock"], **weights}

    inst_list = [_inst_from_dict(d) for d in instruments]
    # Build fresh sector medians from this batch
    sm = build_sector_medians(inst_list)
    gpe = compute_global_pe_median(sm)

    results = []
    for raw_d, inst in zip(instruments, inst_list):
        r = score_instrument(inst, sm, gpe, cfg)
        out = {
            **raw_d,   # preserve all original fields
            "score":              r["cross_market_adjusted_score"],
            "sector_rel_score":   r["sector_relative_score"],
            "label":              r["label"],
            "score_components":   r["score_components"],
            "score_coverage":     r["score_coverage"],
            "risk_flags":         r["flags"],
            "penalties":          r["penalties"],
            "data_flag":          r["data_flag"],
            "data_completeness":  r["data_completeness_ratio"],
            # Surface key derived metrics for the UI
            "roic":               r.get("derived", {}).get("roic"),
            "altman_z":           r.get("derived", {}).get("altman_z"),
            "accrual_ratio":      r.get("derived", {}).get("accrual_ratio"),
            "eq_score":           r.get("derived", {}).get("eq_score"),
            "ca_score":           r.get("derived", {}).get("ca_score"),
            "p_fcf":              r.get("derived", {}).get("p_fcf"),
            "is_financial":       r.get("derived", {}).get("is_financial", False),
            # Surface momentum_score at top level for frontend momentum filter
            "momentum_score":     r.get("score_components", {}).get("momentum_score"),
            # Backwards-compat fields for verdicts.py
            # New engine uses penalties instead of hard quality gates, so we
            # derive quality_passes from whether any severe penalties exist.
            "quality_passes":       len(r.get("penalties", [])) == 0,
            "quality_fail_reasons": r.get("penalties", []),
        }
        results.append(out)

    return results


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 14: UNIT TEST EXAMPLES
# ══════════════════════════════════════════════════════════════════════════════

def _run_examples():
    """
    Four illustrative test cases. Run with: python scoring_engine.py
    Demonstrates:
      1. High-quality compounder at a fair price  → Strong Buy
      2. Classic value trap                       → Avoid / Strong Avoid
      3. Cyclical with normalised earnings        → Watch / Buy
      4. Distressed bank below book               → Avoid / Strong Avoid
    """

    # ── Synthetic peer universe (needed for sector-relative scoring) ──────────
    # We create 6 sector peers per relevant sector with median-ish metrics.

    def _peer(ticker, sector, **kw):
        d = InstrumentInput(ticker=ticker, sector=sector, asset_class="Stock")
        for k, v in kw.items():
            object.__setattr__(d, k, v)
        return d

    tech_peers = [
        _peer("PEER_T1", "Technology", market_cap=50e9, ev_ebitda=18, pe=22, pb=4.0,
              free_cashflow=2e9, ebit=3e9, total_debt=2e9, book_equity=12e9, roe=0.18,
              return_1y=0.12, total_assets=20e9, revenue=15e9, net_income=2e9,
              operating_cashflow=2.5e9),
        _peer("PEER_T2", "Technology", market_cap=40e9, ev_ebitda=20, pe=25, pb=5.0,
              free_cashflow=1.5e9, ebit=2.5e9, total_debt=1e9, book_equity=10e9, roe=0.20,
              return_1y=0.08, total_assets=18e9, revenue=12e9, net_income=1.8e9,
              operating_cashflow=2e9),
        _peer("PEER_T3", "Technology", market_cap=60e9, ev_ebitda=22, pe=28, pb=6.0,
              free_cashflow=2.5e9, ebit=3.5e9, total_debt=3e9, book_equity=15e9, roe=0.22,
              return_1y=0.15, total_assets=25e9, revenue=18e9, net_income=2.5e9,
              operating_cashflow=3e9),
    ]

    bank_peers = [
        _peer("PEER_B1", "Banks", market_cap=20e9, pb=1.0, roe=0.10,
              div_yield=0.04, return_1y=0.05, total_assets=200e9,
              tier1_capital_ratio=0.12, npl_ratio=0.02, loan_loss_coverage=1.4),
        _peer("PEER_B2", "Banks", market_cap=25e9, pb=1.2, roe=0.12,
              div_yield=0.045, return_1y=0.08, total_assets=250e9,
              tier1_capital_ratio=0.13, npl_ratio=0.018, loan_loss_coverage=1.5),
        _peer("PEER_B3", "Banks", market_cap=18e9, pb=0.9, roe=0.08,
              div_yield=0.035, return_1y=0.03, total_assets=180e9,
              tier1_capital_ratio=0.11, npl_ratio=0.025, loan_loss_coverage=1.2),
    ]

    energy_peers = [
        _peer("PEER_E1", "Energy", market_cap=30e9, ev_ebitda=6, pe=10, pb=1.5,
              free_cashflow=2e9, ebit=3.5e9, total_debt=5e9, book_equity=20e9, roe=0.12,
              return_1y=0.05, total_assets=40e9, revenue=20e9, net_income=2e9,
              operating_cashflow=3e9, is_cyclical=True),
        _peer("PEER_E2", "Energy", market_cap=28e9, ev_ebitda=7, pe=11, pb=1.8,
              free_cashflow=1.8e9, ebit=3e9, total_debt=6e9, book_equity=18e9, roe=0.10,
              return_1y=-0.02, total_assets=38e9, revenue=18e9, net_income=1.5e9,
              operating_cashflow=2.5e9, is_cyclical=True),
        _peer("PEER_E3", "Energy", market_cap=35e9, ev_ebitda=8, pe=13, pb=2.0,
              free_cashflow=2.2e9, ebit=4e9, total_debt=4e9, book_equity=22e9, roe=0.14,
              return_1y=0.10, total_assets=42e9, revenue=22e9, net_income=2.3e9,
              operating_cashflow=3.2e9, is_cyclical=True),
    ]

    all_peers = tech_peers + bank_peers + energy_peers
    sm = build_sector_medians(all_peers)
    gpe = compute_global_pe_median(sm)

    print("=" * 70)
    print("VALUE SCREENER — SCORING ENGINE EXAMPLES")
    print("=" * 70)

    # ─────────────────────────────────────────────────────────────────────────
    # Case 1: High-quality compounder at a fair price
    # ROIC=28%, FCF/MCap=6%, below-median P/E & EV/EBITDA, excellent earnings quality
    # Expected: Strong Buy / Buy
    # ─────────────────────────────────────────────────────────────────────────
    compounder = InstrumentInput(
        ticker="COMP",  name="Quality Compounder Co",
        sector="Technology",  asset_class="Stock",
        market_cap=45e9, ev=46e9, ev_ebitda=16, ev_ebit=14, pe=18, pb=3.5,
        ebit=3.3e9, ebitda=3.8e9, revenue=14e9, net_income=2.2e9,
        free_cashflow=2.7e9, operating_cashflow=3.0e9,  # strong cash conversion
        total_debt=1.5e9, book_equity=13e9, cash=2e9, total_assets=18e9,
        current_assets=7e9, current_liabilities=3e9, retained_earnings=9e9,
        roe=0.25, effective_tax_rate=0.18,
        div_yield=0.015, payout_ratio=0.25,
        return_1y=0.18, return_1m=0.01,   # good 12M, exclude last month
        shares_outstanding=1e9, shares_3y_ago=1.05e9,  # mild buybacks
    )
    r1 = score_instrument(compounder, sm, gpe)
    print(f"\n[1] {r1['ticker']} — {r1['name']}")
    print(f"    Sector-Relative Score : {r1['sector_relative_score']}")
    print(f"    Cross-Market Score    : {r1['cross_market_adjusted_score']}")
    print(f"    Label                 : {r1['label']}")
    print(f"    Coverage              : {r1['score_coverage']:.0%}")
    print(f"    ROIC                  : {r1['derived'].get('roic', 0):.1%}")
    print(f"    EQ Score              : {r1['derived'].get('eq_score')}")
    print(f"    Flags                 : {[f['label'] for f in r1['flags']]}")

    # ─────────────────────────────────────────────────────────────────────────
    # Case 2: Classic value trap
    # Cheap P/E and EV/EBITDA, but: poor ROIC, high accruals, regulatory flag,
    # high leverage, falling revenues → distress risk
    # Expected: Avoid / Strong Avoid
    # ─────────────────────────────────────────────────────────────────────────
    value_trap = InstrumentInput(
        ticker="TRAP",  name="Value Trap Inc",
        sector="Technology",  asset_class="Stock",
        market_cap=8e9, ev=16e9, ev_ebitda=9, ev_ebit=12, pe=8, pb=1.2,
        ebit=1.3e9, ebitda=1.8e9, revenue=12e9, net_income=1.0e9,
        free_cashflow=0.1e9,   # very poor FCF vs net income → accruals!
        operating_cashflow=0.2e9,
        total_debt=14e9,       # very high debt
        book_equity=6.7e9, cash=0.5e9, total_assets=22e9,
        current_assets=3e9, current_liabilities=4.5e9,  # negative working capital
        retained_earnings=1e9,
        roe=0.05,              # poor ROE
        effective_tax_rate=0.20,
        div_yield=0.05,        # high yield but FCF doesn't support it
        payout_ratio=1.0,      # 100% payout → not covered by FCF
        return_1y=-0.25,       # falling knife
        shares_outstanding=1e9, shares_3y_ago=0.9e9,  # dilution!
        regulatory_flag=True,  flag_severity="high",
    )
    r2 = score_instrument(value_trap, sm, gpe)
    print(f"\n[2] {r2['ticker']} — {r2['name']}")
    print(f"    Sector-Relative Score : {r2['sector_relative_score']}")
    print(f"    Cross-Market Score    : {r2['cross_market_adjusted_score']}")
    print(f"    Label                 : {r2['label']}")
    print(f"    Altman Z              : {r2['derived'].get('altman_z')}")
    print(f"    Accrual Ratio         : {r2['derived'].get('accrual_ratio')}")
    print(f"    Penalties applied     : {r2['penalties']}")
    print(f"    Flags                 : {[f['label'] for f in r2['flags']]}")

    # ─────────────────────────────────────────────────────────────────────────
    # Case 3: Cyclical company — cheap on trailing earnings but fair on normalised
    # Energy co: trailing P/E looks very cheap but near-peak earnings.
    # Normalised earnings bring EV/EBIT up to mid-cycle level.
    # Good momentum (energy cycle upswing).
    # Expected: Watch / Buy (not as cheap as trailing metrics suggest)
    # ─────────────────────────────────────────────────────────────────────────
    cyclical = InstrumentInput(
        ticker="CYCL",  name="Mid-Cycle Energy Ltd",
        sector="Energy",  asset_class="Stock",
        is_cyclical=True,
        market_cap=30e9, ev=35e9, ev_ebitda=5, ev_ebit=7, pe=8, pb=1.6,
        ebit=5e9,       # peak cycle EBIT
        ebitda=6e9, revenue=25e9, net_income=3.5e9,
        free_cashflow=2.5e9, operating_cashflow=3e9,
        total_debt=5e9, book_equity=18.75e9, cash=2e9, total_assets=38e9,
        current_assets=8e9, current_liabilities=5e9, retained_earnings=10e9,
        roe=0.14, effective_tax_rate=0.22,
        div_yield=0.04,
        return_1y=0.22,  # momentum is strong (energy rally)
        return_1m=0.02,
        # Normalised (mid-cycle) data — average over 5–7 years
        revenue_avg_5y=20e9,
        ebit_margin_avg_5y=0.12,   # normalised EBIT margin 12% → normalised EBIT = 2.4bn
        net_income_avg_3y=2e9,     # trailing 3.5bn is 75% above average → flag
        shares_outstanding=1e9,
    )
    r3 = score_instrument(cyclical, sm, gpe)
    print(f"\n[3] {r3['ticker']} — {r3['name']}")
    print(f"    Sector-Relative Score : {r3['sector_relative_score']}")
    print(f"    Cross-Market Score    : {r3['cross_market_adjusted_score']}")
    print(f"    Label                 : {r3['label']}")
    print(f"    Is Cyclical           : {r3['derived'].get('is_cyclical')}")
    print(f"    Normalised Earnings   : {r3['derived'].get('normalised_earn', 0)/1e9:.1f}bn")
    print(f"    Flags                 : {[f['label'] for f in r3['flags']]}")

    # ─────────────────────────────────────────────────────────────────────────
    # Case 4: Distressed bank trading below book
    # P/B < 1, deteriorating NPLs, weak Tier 1, cutting dividends
    # Expected: Strong Avoid
    # ─────────────────────────────────────────────────────────────────────────
    distressed_bank = InstrumentInput(
        ticker="DBNK",  name="Distressed Regional Bank",
        sector="Banks",  asset_class="Stock",
        market_cap=6e9, pb=0.55, roe=0.04,  # very low ROE
        div_yield=0.02, payout_ratio=0.50,
        return_1y=-0.35,  # severe underperformance
        return_1m=-0.05,
        total_assets=120e9,
        tier1_capital_ratio=0.085,   # below 10% → concern
        npl_ratio=0.08,              # high NPL
        loan_loss_coverage=0.8,      # under-reserved (<1.0)
        npl_trend="deteriorating",   # rising NPLs
        regulatory_flag=True, flag_severity="medium",
        net_income=240e6, operating_cashflow=180e6,   # poor cash conversion
    )
    r4 = score_instrument(distressed_bank, sm, gpe)
    print(f"\n[4] {r4['ticker']} — {r4['name']}")
    print(f"    Sector-Relative Score : {r4['sector_relative_score']}")
    print(f"    Cross-Market Score    : {r4['cross_market_adjusted_score']}")
    print(f"    Label                 : {r4['label']}")
    print(f"    Asset Quality Score   : {r4['score_components'].get('asset_quality_score')}")
    print(f"    Penalties applied     : {r4['penalties']}")
    print(f"    Flags                 : {[f['label'] for f in r4['flags']]}")

    print("\n" + "=" * 70)
    print("All examples complete.")


if __name__ == "__main__":
    _run_examples()
