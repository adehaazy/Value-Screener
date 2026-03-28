"""
Two-stage scoring engine.

Stage 1 — Quality Gate (stocks only):
  Cheap bad businesses are filtered out entirely.
  Must pass ALL of: ROE, debt, profit margin, free cash flow.

Stage 2 — Sector-Relative Valuation:
  Only instruments that pass the quality gate get scored.
  Stocks are scored vs their sector median, not arbitrary absolutes.
  ETFs and money market funds have their own scoring logic.
"""

import numpy as np


# ── Safe float helper ─────────────────────────────────────────────────────────

def _f(v):
    if v is None:
        return None
    try:
        f = float(v)
        return None if (f != f) else f
    except (TypeError, ValueError):
        return None


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 1: QUALITY GATE (stocks only)
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_QUALITY_THRESHOLDS = {
    "min_roe":          0.10,   # 10% return on equity
    "max_debt_equity":  2.0,    # Debt/equity below 2x
    "min_profit_margin": 0.02,  # 2% profit margin
    "require_positive_fcf": True,
}

def quality_gate_result(row: dict, thresholds: dict = None) -> dict:
    """
    Run the quality gate on a stock.
    Returns {"passes": bool, "reasons": list[str], "flags": list[str]}
    reasons = why it failed
    flags   = concerns even if it passed (amber signals)
    """
    t = thresholds or DEFAULT_QUALITY_THRESHOLDS
    reasons = []   # Hard fails
    flags   = []   # Soft concerns

    roe          = _f(row.get("roe"))
    de           = _f(row.get("debt_equity"))
    pm           = _f(row.get("profit_margin"))
    fcf          = _f(row.get("free_cashflow"))

    # Hard gates
    if roe is None or roe < t["min_roe"]:
        reasons.append(f"ROE {_pct(roe)} — below {_pct(t['min_roe'])} threshold")
    if de is not None and de > t["max_debt_equity"]:
        reasons.append(f"Debt/Equity {de:.1f}x — above {t['max_debt_equity']}x threshold")
    if pm is None or pm < t["min_profit_margin"]:
        reasons.append(f"Profit margin {_pct(pm)} — below {_pct(t['min_profit_margin'])} threshold")
    if t["require_positive_fcf"] and fcf is not None and fcf < 0:
        reasons.append("Negative free cash flow")

    # Soft flags (won't fail, but worth noting)
    if roe is not None and roe < 0.15 and not reasons:
        flags.append(f"ROE {_pct(roe)} — adequate but not exceptional")
    if de is not None and de > 1.0 and not reasons:
        flags.append(f"Leverage elevated ({de:.1f}x D/E)")

    return {
        "passes": len(reasons) == 0,
        "reasons": reasons,
        "flags": flags,
    }

def _pct(v):
    if v is None: return "N/A"
    return f"{v*100:.1f}%"


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 2A: STOCK VALUATION SCORING (sector-relative)
# ══════════════════════════════════════════════════════════════════════════════

def _relative_score(stock_val, sector_median, target_multiple, ceiling_multiple):
    """
    Score a metric relative to its sector median.
    stock_val / sector_median gives us a 'multiple'.
    At target_multiple (e.g. 0.8) → 100 pts.
    At ceiling_multiple (e.g. 1.2) → 0 pts.
    Linear between.
    """
    if stock_val is None or sector_median is None or sector_median <= 0:
        return None
    multiple = stock_val / sector_median
    if multiple <= target_multiple:
        return 100.0
    if multiple >= ceiling_multiple:
        return 0.0
    return 100.0 * (1 - (multiple - target_multiple) / (ceiling_multiple - target_multiple))


def _absolute_score(val, best, worst):
    """Score where best = 100, worst = 0. Direction: best < worst means lower=better."""
    if val is None:
        return None
    if best < worst:  # lower is better
        if val <= best: return 100.0
        if val >= worst: return 0.0
        return 100.0 * (1 - (val - best) / (worst - best))
    else:             # higher is better
        if val >= best: return 100.0
        if val <= worst: return 0.0
        return 100.0 * (val - worst) / (best - worst)


def score_stock(row: dict, sector_medians: dict, weights: dict = None) -> dict:
    """
    Score a stock on valuation, sector-relative.
    weights: optional dict with keys pe, pb, evebitda, divyield, w52
             (relative importance values; normalised by engine, don't need to sum to 100)
    Returns {"score": float|None, "components": dict, "data_quality": str}
    """
    w = weights or {}
    sector = row.get("sector", "Unknown")
    sm = sector_medians.get(sector, {})
    has_sector = bool(sm)

    components = {}
    pts, wts = [], []

    def add(label, score, weight):
        if score is not None:
            pts.append(score * weight)
            wts.append(weight)
            components[label] = {"score": round(score, 1), "weight": weight}
        else:
            components[label] = {"score": None, "weight": weight}

    # P/E vs sector
    pe_score = _relative_score(_f(row.get("pe")), sm.get("pe"), 0.80, 1.20) if has_sector \
               else _absolute_score(_f(row.get("pe")), 12, 35)
    add("P/E vs sector" if has_sector else "P/E", pe_score, w.get("pe", 30))

    # P/B vs sector
    pb_score = _relative_score(_f(row.get("pb")), sm.get("pb"), 0.75, 1.25) if has_sector \
               else _absolute_score(_f(row.get("pb")), 1.0, 5.0)
    add("P/B vs sector" if has_sector else "P/B", pb_score, w.get("pb", 20))

    # EV/EBITDA vs sector
    ev_score = _relative_score(_f(row.get("ev_ebitda")), sm.get("ev_ebitda"), 0.80, 1.20) if has_sector \
               else _absolute_score(_f(row.get("ev_ebitda")), 6, 22)
    add("EV/EBITDA vs sector" if has_sector else "EV/EBITDA", ev_score, w.get("evebitda", 20))

    # Dividend yield — absolute, higher is better
    div_score = _absolute_score(_f(row.get("div_yield")), 5.0, 0.0)
    add("Dividend yield", div_score, w.get("divyield", 15))

    # Price vs 52w high — contrarian signal
    pct = _f(row.get("pct_from_high"))
    pct_score = None
    if pct is not None:
        pct_score = min(max((-pct) / 30, 0), 1) * 100
    add("Discount to 52w high", pct_score, w.get("w52", 15))

    total = sum(pts) / sum(wts) if wts else None
    data_quality = "good" if len(wts) >= 3 else "limited"

    return {
        "score": round(total, 1) if total is not None else None,
        "components": components,
        "data_quality": data_quality,
        "sector_relative": has_sector,
    }


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 2B: ETF SCORING
# ══════════════════════════════════════════════════════════════════════════════

def score_etf(row: dict, weights: dict = None) -> dict:
    """
    Score an ETF.
    weights: optional dict with keys aum, ter, ret, mom
    """
    w = weights or {}
    components = {}
    pts, wts = [], []

    def add(label, score, weight):
        if score is not None:
            pts.append(score * weight)
            wts.append(weight)
            components[label] = {"score": round(score, 1), "weight": weight}
        else:
            components[label] = {"score": None, "weight": weight}

    # AUM — fund size/liquidity
    aum = _f(row.get("aum"))
    aum_score = None
    if aum is not None:
        aum_score = min(max((aum - 500_000_000) / (10_000_000_000 - 500_000_000), 0), 1) * 100
    add("Fund size (AUM)", aum_score, w.get("aum", 35))

    # TER — expense ratio
    ter = _f(row.get("ter"))
    ter_score = None
    if ter is not None:
        ter_score = max(1 - (ter / 0.005), 0) * 100
    add("Annual cost (TER)", ter_score, w.get("ter", 35))

    # 1yr return
    ret = _f(row.get("yr1_pct"))
    ret_score = None
    if ret is not None:
        ret_score = min(max((ret + 15) / 35, 0), 1) * 100
    add("1yr return", ret_score, w.get("ret", 20))

    # Price vs 52w high — momentum
    pct = _f(row.get("pct_from_high"))
    pct_score = None
    if pct is not None:
        pct_score = min(max((pct + 20) / 20, 0), 1) * 100
    add("Price momentum", pct_score, w.get("mom", 10))

    total = sum(pts) / sum(wts) if wts else None

    return {
        "score": round(total, 1) if total is not None else None,
        "components": components,
        "data_quality": "good" if len(wts) >= 2 else "limited",
        "sector_relative": False,
    }


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 2C: MONEY MARKET SCORING
# ══════════════════════════════════════════════════════════════════════════════

def score_money_market(row: dict, weights: dict = None) -> dict:
    """
    Score a money market / short duration fund.
    weights: optional dict with keys yield, aum, ter
    """
    w = weights or {}
    components = {}
    pts, wts = [], []

    def add(label, score, weight):
        if score is not None:
            pts.append(score * weight)
            wts.append(weight)
            components[label] = {"score": round(score, 1), "weight": weight}
        else:
            components[label] = {"score": None, "weight": weight}

    # Yield
    yld = _f(row.get("div_yield"))
    yld_score = None
    if yld is not None:
        yld_score = min(yld / 5.0, 1) * 100
    add("Distribution yield", yld_score, w.get("yield", 60))

    # Fund size
    aum = _f(row.get("aum"))
    aum_score = None
    if aum is not None:
        aum_score = min(max((aum - 100_000_000) / (5_000_000_000 - 100_000_000), 0), 1) * 100
    add("Fund size", aum_score, w.get("aum", 25))

    # TER
    ter = _f(row.get("ter"))
    ter_score = None
    if ter is not None:
        ter_score = max(1 - (ter / 0.003), 0) * 100
    add("Annual cost (TER)", ter_score, w.get("ter", 15))

    total = sum(pts) / sum(wts) if wts else None

    return {
        "score": round(total, 1) if total is not None else None,
        "components": components,
        "data_quality": "good" if len(wts) >= 2 else "limited",
        "sector_relative": False,
    }


# ══════════════════════════════════════════════════════════════════════════════
# DISPATCHER
# ══════════════════════════════════════════════════════════════════════════════

def score_instrument(row: dict, sector_medians: dict,
                     quality_thresholds: dict = None,
                     scoring_weights: dict = None) -> dict:
    """
    Full scoring pipeline for one instrument.
    scoring_weights: optional dict with keys "stock", "etf", "mm"
                     each containing per-metric weight overrides.
    Returns enriched dict with score, quality gate, components, and verdict inputs.
    """
    ac = row.get("asset_class", "")
    result = dict(row)  # copy
    sw = scoring_weights or {}

    if ac == "Stock":
        gate = quality_gate_result(row, quality_thresholds)
        result["quality_passes"] = gate["passes"]
        result["quality_reasons"] = gate["reasons"]
        result["quality_flags"]   = gate["flags"]

        if gate["passes"]:
            scoring = score_stock(row, sector_medians, sw.get("stock"))
        else:
            scoring = {"score": None, "components": {}, "data_quality": "n/a", "sector_relative": False}
    else:
        result["quality_passes"] = True
        result["quality_reasons"] = []
        result["quality_flags"]   = []
        if ac == "ETF":
            scoring = score_etf(row, sw.get("etf"))
        elif ac == "Money Market":
            scoring = score_money_market(row, sw.get("mm"))
        else:
            scoring = {"score": None, "components": {}, "data_quality": "unknown", "sector_relative": False}

    result["score"]            = scoring["score"]
    result["score_components"] = scoring["components"]
    result["data_quality"]     = scoring["data_quality"]
    result["sector_relative"]  = scoring["sector_relative"]

    return result


def score_all(instruments: list[dict], sector_medians: dict,
              quality_thresholds: dict = None,
              scoring_weights: dict = None) -> list[dict]:
    return [score_instrument(r, sector_medians, quality_thresholds, scoring_weights)
            for r in instruments if r.get("ok", False)]


# ── Rating label helpers ──────────────────────────────────────────────────────

def score_label(s):
    if s is None: return "Insufficient data"
    if s >= 75:   return "Strong Value"
    if s >= 55:   return "Fair Value"
    if s >= 35:   return "Fully Valued"
    return "Expensive"

def score_colour(s):
    if s is None: return "#888888"
    if s >= 75:   return "#00c853"
    if s >= 55:   return "#ffd600"
    if s >= 35:   return "#ff9100"
    return "#ff1744"

def score_bg(s):
    if s is None: return "#1e2130"
    if s >= 75:   return "#0a2e1a"
    if s >= 55:   return "#2a2400"
    if s >= 35:   return "#2a1500"
    return "#2a0a0a"
