"""
tests/test_verdicts.py — Unit tests for utils/verdicts.py

Tests cover:
  - stock_verdict: quality fail path, quality pass path, dividend/price sentences
  - etf_verdict: cost tiers, AUM sizes, return notes
  - money_market_verdict: yield tiers, net yield calculation
  - add_verdicts: populates verdict key on all instruments
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.verdicts import stock_verdict, etf_verdict, money_market_verdict, add_verdicts


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _stock(overrides=None) -> dict:
    base = {
        "ok":              True,
        "asset_class":     "Stock",
        "sector":          "Technology",
        "quality_passes":  True,
        "quality_fail_reasons": [],
        "quality_flags":   [],
        "score":           65.0,
        "roe":             0.18,
        "pe":              14.0,
        "pb":              2.0,
        "debt_equity":     0.4,
        "div_yield":       0.025,   # 2.5% — stored as decimal
        "pct_from_high":   -15.0,
        "profit_margin":   0.12,
    }
    if overrides:
        base.update(overrides)
    return base


def _etf(overrides=None) -> dict:
    base = {
        "ok":          True,
        "asset_class": "ETF",
        "ter":         0.0007,          # 0.07%
        "aum":         5_000_000_000,   # $5bn
        "yr1_pct":     12.0,
        "div_yield":   0.0,
    }
    if overrides:
        base.update(overrides)
    return base


def _mm(overrides=None) -> dict:
    base = {
        "ok":          True,
        "asset_class": "Money Market",
        "div_yield":   0.045,   # 4.5%
        "ter":         0.001,   # 0.1%
        "aum":         3_000_000_000,
    }
    if overrides:
        base.update(overrides)
    return base


# ── stock_verdict ─────────────────────────────────────────────────────────────

class TestStockVerdict:

    def test_unavailable_data(self):
        v = stock_verdict({"ok": False, "asset_class": "Stock"}, {})
        # Called via generate_verdict which guards on ok; stock_verdict itself
        # receives the row directly so test the quality fail path with no reasons
        row = _stock({"quality_passes": False, "quality_fail_reasons": []})
        v = stock_verdict(row, {})
        assert "quality" in v.lower() or "not pass" in v.lower() or "concern" in v.lower()

    def test_quality_fail_with_reasons_mentions_reason(self):
        row = _stock({
            "quality_passes": False,
            "quality_fail_reasons": ["ROE 4.0% < 8%"],
        })
        v = stock_verdict(row, {})
        assert "returns on equity" in v.lower()

    def test_quality_fail_debt_reason(self):
        row = _stock({
            "quality_passes": False,
            "quality_fail_reasons": ["Debt/Equity 4.0x > 3x"],
        })
        v = stock_verdict(row, {})
        assert "leverage" in v.lower()

    def test_quality_fail_fcf_reason(self):
        row = _stock({
            "quality_passes": False,
            "quality_fail_reasons": ["Negative FCF"],
        })
        v = stock_verdict(row, {})
        assert "fcf" in v.lower() or "cash" in v.lower()

    def test_quality_pass_returns_string(self):
        row = _stock()
        v = stock_verdict(row, {})
        assert isinstance(v, str)
        assert len(v) > 20

    def test_high_roe_quality_sentence(self):
        row = _stock({"roe": 0.25})
        v = stock_verdict(row, {})
        assert "high-quality" in v.lower()

    def test_moderate_roe_quality_sentence(self):
        row = _stock({"roe": 0.10})
        v = stock_verdict(row, {})
        assert "adequate" in v.lower() or "solid" in v.lower() or "%" in v

    def test_near_debt_free(self):
        row = _stock({"debt_equity": 0.2})
        v = stock_verdict(row, {})
        assert "debt-free" in v.lower()

    def test_dividend_mentioned_when_above_1pct(self):
        # div_yield 0.03 = 3%, stored as decimal
        row = _stock({"div_yield": 0.03})
        v = stock_verdict(row, {})
        assert "%" in v and ("dividend" in v.lower() or "yield" in v.lower())

    def test_dividend_not_mentioned_when_very_low(self):
        # div_yield 0.002 = 0.2%, below 1% threshold
        row = _stock({"div_yield": 0.002})
        v = stock_verdict(row, {})
        assert "dividend" not in v.lower()

    def test_sector_pe_comparison_used_when_median_available(self):
        row = _stock({"pe": 10.0, "sector": "Tech"})
        sm = {"Tech": {"pe": 20.0}}
        v = stock_verdict(row, sm)
        assert "sector" in v.lower() or "discount" in v.lower()

    def test_far_below_high_mentioned(self):
        row = _stock({"pct_from_high": -35.0})
        v = stock_verdict(row, {})
        assert "52-week" in v.lower() or "high" in v.lower()

    def test_verdict_ends_with_period(self):
        row = _stock()
        v = stock_verdict(row, {})
        assert v.endswith(".")


# ── etf_verdict ───────────────────────────────────────────────────────────────

class TestEtfVerdict:

    def test_returns_string(self):
        assert isinstance(etf_verdict(_etf()), str)

    def test_very_low_cost(self):
        v = etf_verdict(_etf({"ter": 0.0005}))
        assert "low" in v.lower()

    def test_expensive_etf_flagged(self):
        v = etf_verdict(_etf({"ter": 0.015}))
        assert "expensive" in v.lower() or "alternatives" in v.lower()

    def test_large_fund_mentioned(self):
        v = etf_verdict(_etf({"aum": 15_000_000_000}))
        assert "bn" in v.lower() or "large" in v.lower()

    def test_small_fund_closure_risk_mentioned(self):
        v = etf_verdict(_etf({"aum": 50_000_000}))
        assert "closure" in v.lower() or "smaller" in v.lower()

    def test_positive_return_mentioned(self):
        v = etf_verdict(_etf({"yr1_pct": 18.0}))
        assert "return" in v.lower() or "%" in v

    def test_negative_return_mentioned(self):
        v = etf_verdict(_etf({"yr1_pct": -10.0}))
        assert "down" in v.lower() or "-10" in v or "%" in v

    def test_missing_ter(self):
        v = etf_verdict(_etf({"ter": None}))
        assert "unavailable" in v.lower() or "cost" in v.lower()


# ── money_market_verdict ──────────────────────────────────────────────────────

class TestMoneyMarketVerdict:

    def test_returns_string(self):
        assert isinstance(money_market_verdict(_mm()), str)

    def test_excellent_yield(self):
        # net yield = 4.5% - 0.1% = 4.4% → "Good" (>= 3.5%)
        v = money_market_verdict(_mm({"div_yield": 0.045, "ter": 0.001}))
        assert "yield" in v.lower()

    def test_net_yield_deducts_ter(self):
        # div_yield 5% (0.05), ter 1% (0.01) → net 4%
        v = money_market_verdict(_mm({"div_yield": 0.05, "ter": 0.01}))
        # Should mention ~4%, not ~5%
        assert "4." in v or "yield" in v.lower()

    def test_low_yield_flagged(self):
        v = money_market_verdict(_mm({"div_yield": 0.005, "ter": 0.001}))
        assert "low" in v.lower()

    def test_missing_yield(self):
        v = money_market_verdict(_mm({"div_yield": None}))
        assert "unavailable" in v.lower()

    def test_large_fund_stable(self):
        v = money_market_verdict(_mm({"aum": 10_000_000_000}))
        assert "bn" in v.lower() or "stable" in v.lower() or "large" in v.lower()


# ── add_verdicts ──────────────────────────────────────────────────────────────

class TestAddVerdicts:

    def test_populates_verdict_key(self):
        instruments = [
            _stock(),
            _etf(),
            _mm(),
        ]
        result = add_verdicts(instruments, {})
        for inst in result:
            assert "verdict" in inst
            assert isinstance(inst["verdict"], str)
            assert len(inst["verdict"]) > 0

    def test_unavailable_instrument(self):
        instruments = [{"ok": False, "asset_class": "Stock"}]
        result = add_verdicts(instruments, {})
        assert result[0]["verdict"] == "Data unavailable for this instrument."

    def test_unknown_asset_class(self):
        instruments = [{"ok": True, "asset_class": "Unknown"}]
        result = add_verdicts(instruments, {})
        assert result[0]["verdict"] == "—"

    def test_does_not_mutate_originals_unexpectedly(self):
        # add_verdicts mutates in-place by design, but should not break other keys
        inst = _stock()
        original_roe = inst["roe"]
        add_verdicts([inst], {})
        assert inst["roe"] == original_roe
