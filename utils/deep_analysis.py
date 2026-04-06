"""
Deep Analysis — qualitative value investing evaluation via Claude API.

For a single watchlist instrument:
  1. Assembles a rich data context from the cached instrument dict
     plus optional extra text (transcripts, filings, user notes)
  2. Calls claude-haiku-4-5-20251001 for the initial analysis (fast, cheap)
     OR claude-sonnet-4-6 if force_sonnet=True (explicit user refresh)
  3. Parses and caches the structured JSON response
  4. Returns the analysis dict

Model strategy:
  - Default (auto): claude-haiku-4-5-20251001 (~10x cheaper, ~3x faster)
  - Force refresh:  claude-sonnet-4-6 (full depth, on explicit user request)
  - The model used is stored in the cache as "_model" for display in the UI

Cache TTL: 7 days (qualitative analysis doesn't change hourly)
Requires: ANTHROPIC_API_KEY environment variable
"""

import json
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone

CACHE_DIR = Path(__file__).parent.parent / "cache" / "deep_analysis"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_TTL_DAYS = 7

# Model routing
MODEL_HAIKU  = "claude-haiku-4-5-20251001"   # default — fast and cheap
MODEL_SONNET = "claude-sonnet-4-6"            # full depth — explicit refresh only


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _cache_file(ticker: str) -> Path:
    safe = ticker.replace(".", "_").replace("-", "_")
    return CACHE_DIR / f"{safe}.json"


def load_cached_analysis(ticker: str) -> dict | None:
    """Return cached analysis if it exists and is fresh, else None."""
    f = _cache_file(ticker)
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text())
        ran_at = datetime.fromisoformat(data.get("_ran_at", "2000-01-01"))
        if ran_at.tzinfo is None:
            ran_at = ran_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - ran_at < timedelta(days=CACHE_TTL_DAYS):
            return data
    except Exception:
        pass
    return None


def _save_analysis(ticker: str, data: dict):
    data["_ran_at"] = datetime.now(timezone.utc).isoformat()
    _cache_file(ticker).write_text(json.dumps(data, indent=2, default=str))


def cache_age_days(ticker: str) -> float | None:
    """Returns how many days old the cached analysis is, or None if absent."""
    f = _cache_file(ticker)
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text())
        ran_at = datetime.fromisoformat(data.get("_ran_at", "2000-01-01"))
        if ran_at.tzinfo is None:
            ran_at = ran_at.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ran_at).total_seconds() / 86400
    except Exception:
        return None


# ── Data context assembly ─────────────────────────────────────────────────────

def _fmt(v, suffix="", decimals=2, multiplier=1.0):
    """Format a numeric value cleanly, return '—' if None."""
    if v is None:
        return "—"
    try:
        return f"{float(v) * multiplier:.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return str(v)


def _fmt_large(v):
    """Format large numbers (market cap, AUM) as £/$/€bn or m."""
    if v is None:
        return "—"
    try:
        v = float(v)
        if v >= 1e9:
            return f"{v/1e9:.1f}bn"
        if v >= 1e6:
            return f"{v/1e6:.0f}m"
        return f"{v:,.0f}"
    except (TypeError, ValueError):
        return str(v)


def build_data_context(inst: dict) -> str:
    """
    Assemble a structured plain-text summary of all available financial data
    for one instrument. This becomes the 'INPUT' section of the prompt.
    """
    name    = inst.get("name", inst.get("ticker", "Unknown"))
    ticker  = inst.get("ticker", "")
    sector  = inst.get("sector", "—")
    industry = inst.get("industry", "—")
    group   = inst.get("group", "—")
    cur     = inst.get("currency", "")
    ac      = inst.get("asset_class", "Stock")

    fetched = inst.get("fetched_at", "")
    if fetched:
        try:
            fetched = datetime.fromisoformat(fetched).strftime("%d %b %Y")
        except Exception:
            pass

    lines = [
        f"COMPANY: {name} ({ticker})",
        f"SECTOR: {sector}  |  INDUSTRY: {industry}",
        f"ASSET CLASS: {ac}  |  MARKET: {group}",
        f"CURRENCY: {cur}  |  DATA AS OF: {fetched}",
        "",
        "── PRICE & MARKET DATA ──────────────────────────────",
        f"Current price:       {cur} {_fmt(inst.get('price'), decimals=2)}",
        f"Market cap:          {_fmt_large(inst.get('market_cap'))}",
        f"52-week high:        {cur} {_fmt(inst.get('high_52w'), decimals=2)}",
        f"52-week low:         {cur} {_fmt(inst.get('low_52w'), decimals=2)}",
        f"% below 52w high:    {_fmt(inst.get('pct_from_high'), suffix='%', decimals=1)}",
        f"YTD return:          {_fmt(inst.get('ytd_pct'), suffix='%', decimals=1)}",
        f"1-year return:       {_fmt(inst.get('yr1_pct'), suffix='%', decimals=1)}",
        "",
    ]

    if ac == "Stock":
        lines += [
            "── VALUATION MULTIPLES ──────────────────────────────",
            f"Trailing P/E:        {_fmt(inst.get('pe'), suffix='x', decimals=1)}",
            f"Forward P/E:         {_fmt(inst.get('fwd_pe'), suffix='x', decimals=1)}",
            f"Price / Book:        {_fmt(inst.get('pb'), suffix='x', decimals=1)}",
            f"EV / EBITDA:         {_fmt(inst.get('ev_ebitda'), suffix='x', decimals=1)}",
            f"Dividend yield:      {_fmt(inst.get('div_yield'), suffix='%', decimals=2)}",
            "",
            "── QUALITY & BALANCE SHEET ──────────────────────────",
            f"Return on Equity:    {_fmt(inst.get('roe'), suffix='%', decimals=1, multiplier=100)}",
            f"Return on Assets:    {_fmt(inst.get('roa'), suffix='%', decimals=1, multiplier=100)}",
            f"Profit margin:       {_fmt(inst.get('profit_margin'), suffix='%', decimals=1, multiplier=100)}",
            f"Debt / Equity:       {_fmt(inst.get('debt_equity'), suffix='x', decimals=2)}",
            f"Free cash flow:      {_fmt_large(inst.get('free_cashflow'))}",
            "",
            "── GROWTH ───────────────────────────────────────────",
            f"Revenue growth:      {_fmt(inst.get('revenue_growth'), suffix='%', decimals=1, multiplier=100)}",
            f"Earnings growth:     {_fmt(inst.get('earnings_growth'), suffix='%', decimals=1, multiplier=100)}",
            "",
            "── SCREENER SCORES ──────────────────────────────────",
            f"Quantitative score:  {_fmt(inst.get('score'), decimals=1)} / 100",
            f"Quality gate:        {'PASS' if inst.get('quality_passes') else 'FAIL'}",
        ]
        reasons = inst.get("quality_fail_reasons", [])  # written by scoring.py as quality_fail_reasons
        if reasons:
            lines.append(f"Quality fail reasons: {'; '.join(reasons)}")
        flags = inst.get("quality_flags", [])
        if flags:
            lines.append(f"Quality flags:       {'; '.join(flags)}")
        verdict = inst.get("verdict", "")
        if verdict:
            lines += ["", f"Screener verdict: {verdict}"]

    elif ac == "ETF":
        lines += [
            "── ETF METRICS ──────────────────────────────────────",
            f"Total Expense Ratio: {_fmt(inst.get('ter'), suffix='%', decimals=3, multiplier=100)}",
            f"AUM:                 {_fmt_large(inst.get('aum'))}",
            f"Fund family:         {inst.get('fund_family', '—')}",
            f"1-year return:       {_fmt(inst.get('yr1_pct'), suffix='%', decimals=1)}",
            f"Quantitative score:  {_fmt(inst.get('score'), decimals=1)} / 100",
        ]

    elif ac == "Money Market":
        lines += [
            "── MONEY MARKET METRICS ─────────────────────────────",
            f"Distribution yield:  {_fmt(inst.get('div_yield'), suffix='%', decimals=2)}",
            f"Total Expense Ratio: {_fmt(inst.get('ter'), suffix='%', decimals=3, multiplier=100)}",
            f"AUM:                 {_fmt_large(inst.get('aum'))}",
            f"Fund family:         {inst.get('fund_family', '—')}",
            f"Quantitative score:  {_fmt(inst.get('score'), decimals=1)} / 100",
        ]

    return "\n".join(lines)


# ── Master prompt ─────────────────────────────────────────────────────────────

MASTER_PROMPT = """ROLE

You are a disciplined equity research analyst operating within a structured value investing framework.
Your task is to evaluate a single financial instrument as if acquiring the entire business.
You must: prioritise evidence over narrative, be conservative in assumptions, avoid speculation,
and explicitly justify all scores.

INPUT

You will be provided with: company description, financial data, any available earnings/filing context,
and industry context. If information is missing, state this explicitly and reduce confidence.

OUTPUT FORMAT (MANDATORY — respond with valid JSON only, no markdown fences, no preamble)

{
  "company_name": "",
  "overall_score": 0,
  "confidence": "High | Medium | Low",
  "moat": {
    "type_strength": 0,
    "durability": 0,
    "evidence": 0,
    "total": 0,
    "justification": ""
  },
  "business_quality": {
    "revenue_quality": 0,
    "growth_quality": 0,
    "total": 0,
    "justification": ""
  },
  "management": {
    "capital_allocation": 0,
    "communication": 0,
    "alignment": 0,
    "total": 0,
    "justification": ""
  },
  "financial_strength": {
    "balance_sheet": 0,
    "cash_flow": 0,
    "returns_on_capital": 0,
    "total": 0,
    "justification": ""
  },
  "valuation": {
    "discount_to_value": 0,
    "downside_protection": 0,
    "total": 0,
    "justification": ""
  },
  "risk_factors": {
    "score": 0,
    "key_risks": []
  },
  "final_assessment": {
    "rating": "Exceptional | Strong | Moderate | Reject",
    "summary": "",
    "key_drivers": [],
    "failure_modes": []
  }
}

SCORING FRAMEWORK

1. COMPETITIVE MOAT (0–25)
   A. Type Strength (0–10): 0–3 none/weak, 4–7 moderate, 8–10 strong/multiple
   B. Durability (0–10): 0–3 likely erosion, 4–7 medium-term, 8–10 durable 10+ years
      Must include: threat analysis, disruption risk
   C. Evidence (0–5): objective signals only — margins, ROIC, market share stability
   Constraint: narrative alone insufficient. Weak evidence caps moat total at 12.

2. BUSINESS QUALITY (0–15)
   A. Revenue Quality (0–10): recurring vs transactional, customer concentration, predictability
   B. Growth Quality (0–5): organic vs acquisition-driven, sustainable vs cyclical

3. MANAGEMENT (0–15)
   A. Capital Allocation (0–7): rational reinvestment, avoidance of dilution/poor acquisitions
   B. Communication (0–4): transparency, consistency
   C. Alignment (0–4): insider ownership, incentive structure

4. FINANCIAL STRENGTH (0–15)
   Balance sheet resilience (0–5), Cash flow consistency (0–5), Returns on capital (0–5)

5. VALUATION (0–20)
   A. Discount to Intrinsic Value (0–15): estimate conservatively, no high-growth assumption without evidence
   B. Downside Protection (0–5): asset backing, cash generation

6. RISK FACTORS (0–10): start at 10, subtract for industry disruption, regulatory exposure,
   financial leverage, key person dependency

RATING BANDS: 85–100 Exceptional | 70–84 Strong | 55–69 Moderate | <55 Reject

CONSERVATISM RULES
- When uncertain, assign a lower score
- Do not infer advantages without evidence
- Penalise inconsistent financial performance
- Do not optimise for optimism — optimise for accuracy, discipline, repeatability

For every section: explain reasoning in clear simple language, cite specific evidence,
avoid vague statements. Address explicitly: what could weaken the moat, what assumptions
are most fragile, what would cause this investment to fail."""


# ── API call ──────────────────────────────────────────────────────────────────

def run_deep_analysis(inst: dict, extra_context: str = "",
                      force_sonnet: bool = False) -> dict:
    """
    Run the full qualitative analysis for one instrument.

    Parameters
    ----------
    inst          : instrument dict from the screener cache
    extra_context : optional user-supplied text (transcripts, notes, filings)
    force_sonnet  : if True, uses claude-sonnet-4-6 regardless of cache state.
                    Use this for explicit "deep refresh" button clicks.
                    Default (False) uses claude-haiku-4-5-20251001 — ~10x cheaper.

    Returns the parsed analysis dict (also caches it).
    Raises RuntimeError if API key is missing or the API call fails.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY environment variable not set. "
            "Add it to your shell profile or .env file and restart the app."
        )

    try:
        import anthropic
    except ImportError:
        raise RuntimeError(
            "anthropic package not installed. Run: pip install anthropic"
        )

    model = MODEL_SONNET if force_sonnet else MODEL_HAIKU

    data_context = build_data_context(inst)
    user_content = data_context
    if extra_context.strip():
        user_content += f"\n\n── ADDITIONAL CONTEXT (provided by user) ────────────\n{extra_context.strip()}"

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=4096,
        system=MASTER_PROMPT,
        messages=[
            {"role": "user", "content": user_content}
        ],
    )

    raw_text = message.content[0].text.strip()

    # Strip markdown code fences if model wrapped them anyway
    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.strip()

    try:
        result = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Model returned invalid JSON: {e}\n\nRaw output:\n{raw_text[:500]}")

    # Store which model was used — shown in UI as "Haiku" or "Sonnet"
    result["_model"] = model
    _save_analysis(inst["ticker"], result)
    return result
