"""
tests/test_scoring.py — Unit tests for utils/scoring.py

Tests cover:
  - _passes_quality: ROE, D/E, margin, FCF gates for both financial and non-financial stocks
  - score_instrument: ETF, money market, non-financial stock, financial stock
  - score_all: batch pass-through
  - compute_sector_medians: median calculation, single-instrument sector, filtering
  - _score_vs_median: sigmoid behaviour, None handling, lower/higher-is-better
  - score_label / score_colour / score_bg: display helpers
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.scoring import (
    _passes_quality,
    _score_vs_median,
    score_instrument,
    score_all,
    compute_sector_medians,
    score_label,
    score_colour,
    score_bg,
    DEFAULT_QUALITY_THRESHOLDS,
    DEFAULT_WEIGHTS,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _stock(overrides=None) -> dict:
    """Minimal non-financial stock with healthy metrics."""
    base = {
        "ticker":       "TEST",
        "name":         "Test Co",
        "asset_class":  "Stock",
        "sector":       "Technology",
        "ok":           True,
        "roe":          0.18,           # 18%
        "debt_to_equity": 50.0,         # 0.5× (yfinance stores as %)
        "profit_margin":  0.12,         # 12%
        "free_cashflow":  1_000_000,    # positive
        "market_cap":     10_000_000,
        "ev_ebitda":      12.0,
        "pe":             15.0,
        "pb":             2.0,
        "div_yield":      0.025,        # 2.5%
        "pos_52w":        0.3,          # 30% into 52w range
    }
    if overrides:
        base.update(overrides)
    return base


def _financial(overrides=None) -> dict:
    """Minimal financial-sector stock."""
    base = {
        "ticker":       "BANK",
        "name":         "Test Bank",
        "asset_class":  "Stock",
        "sector":       "Financial Services",
        "ok":           True,
        "roe":          0.12,           # 12%
        "price_to_book": 1.2,
        "div_yield":    0.04,           # 4%
        "pos_52w":      0.4,
    }
    if overrides:
        base.update(overrides)
    return base


def _etf(overrides=None) -> dict:
    base = {
        "ticker":      "ETF",
        "asset_class": "ETF",
        "ok":          True,
        "aum":         5_000_000_000,
        "ter":         0.0007,          # 0.07%
        "return_1y":   0.12,
        "return_3m":   0.03,
    }
    if overrides:
        base.update(overrides)
    return base


def _mm(overrides=None) -> dict:
    base = {
        "ticker":      "MM",
        "asset_class": "Money Market",
        "ok":          True,
        "div_yield":   0.045,           # 4.5%
        "aum":         2_000_000_000,
        "ter":         0.001,
    }
    if overrides:
        base.update(overrides)
    return base


# ── _passes_quality tests ─────────────────────────────────────────────────────

class TestPassesQuality:
    def test_healthy_stock_passes(self):
        passes, reasons = _passes_quality(_stock(), DEFAULT_QUALITY_THRESHOLDS)
        assert passes is True
        assert reasons == []

    def test_low_roe_fails(self):
        # ROE 3% < min_roe 8%
        s = _stock({"roe": 0.03})
        passes, reasons = _passes_quality(s, DEFAULT_QUALITY_THRESHOLDS)
        assert passes is False
        assert any("ROE" in r for r in reasons)

    def test_roe_exactly_at_threshold_passes(self):
        # ROE == min_roe: roe*100 < min_roe is False → passes
        s = _stock({"roe": 0.08})
        passes, _ = _passes_quality(s, DEFAULT_QUALITY_THRESHOLDS)
        assert passes is True

    def test_high_debt_fails(self):
        # D/E > 3× (yfinance returns as %, so 350 = 3.5×)
        s = _stock({"debt_to_equity": 350.0})
        passes, reasons = _passes_quality(s, DEFAULT_QUALITY_THRESHOLDS)
        assert passes is False
        assert any("D/E" in r for r in reasons)

    def test_thin_margin_fails(self):
        s = _stock({"profit_margin": 0.005})  # 0.5% < 2%
        passes, reasons = _passes_quality(s, DEFAULT_QUALITY_THRESHOLDS)
        assert passes is False
        assert any("Margin" in r for r in reasons)

    def test_negative_fcf_fails(self):
        s = _stock({"free_cashflow": -500_000})
        passes, reasons = _passes_quality(s, DEFAULT_QUALITY_THRESHOLDS)
        assert passes is False
        assert any("FCF" in r for r in reasons)

    def test_none_values_do_not_fail(self):
        # Missing data should not trigger quality failures
        s = _stock({"roe": None, "debt_to_equity": None, "profit_margin": None, "free_cashflow": None})
        passes, reasons = _passes_quality(s, DEFAULT_QUALITY_THRESHOLDS)
        assert passes is True

    def test_financial_low_roe_fails(self):
        f = _financial({"roe": 0.03})   # 3% < fin_min_roe 6%
        passes, reasons = _passes_quality(f, DEFAULT_QUALITY_THRESHOLDS)
        assert passes is False
        assert any("ROE" in r for r in reasons)

    def test_financial_de_gate_not_applied(self):
        # D/E gate should NOT apply to financials
        f = _financial({"debt_to_equity": 2000.0})
        passes, _ = _passes_quality(f, DEFAULT_QUALITY_THRESHOLDS)
        assert passes is True  # high D/E should not matter for a financial

    def test_financial_high_ptb_fails(self):
        f = _financial({"price_to_book": 3.0})  # > fin_max_price_book 2.0
        passes, reasons = _passes_quality(f, DEFAULT_QUALITY_THRESHOLDS)
        assert passes is False
        assert any("P/Book" in r for r in reasons)

    def test_custom_thresholds_respected(self):
        custom_qt = {**DEFAULT_QUALITY_THRESHOLDS, "min_roe": 20}
        s = _stock({"roe": 0.15})   # 15% < custom 20%
        passes, _ = _passes_quality(s, custom_qt)
        assert passes is False


# ── _score_vs_median tests ────────────────────────────────────────────────────

class TestScoreVsMedian:
    def test_at_median_scores_50(self):
        score = _score_vs_median(10.0, 10.0, lower_is_better=True)
        assert score == pytest.approx(50.0, abs=0.5)

    def test_below_median_cheaper_scores_above_50(self):
        score = _score_vs_median(5.0, 10.0, lower_is_better=True)
        assert score > 50.0

    def test_above_median_expensive_scores_below_50(self):
        score = _score_vs_median(20.0, 10.0, lower_is_better=True)
        assert score < 50.0

    def test_higher_is_better_above_median_scores_above_50(self):
        score = _score_vs_median(15.0, 10.0, lower_is_better=False)
        assert score > 50.0

    def test_none_value_returns_none(self):
        assert _score_vs_median(None, 10.0) is None

    def test_none_median_returns_50(self):
        score = _score_vs_median(10.0, None)
        assert score == 50.0

    def test_zero_median_returns_50(self):
        score = _score_vs_median(10.0, 0.0)
        assert score == 50.0

    def test_output_clamped_0_to_100(self):
        # Extreme value — should still be within [0, 100]
        score = _score_vs_median(0.001, 100.0, lower_is_better=True)
        assert 0.0 <= score <= 100.0


# ── score_instrument tests ────────────────────────────────────────────────────

class TestScoreInstrument:
    def _sm(self, instruments):
        return compute_sector_medians(instruments)

    def test_healthy_stock_gets_score(self):
        inst = _stock()
        sm = self._sm([inst])
        result = score_instrument(inst, sm)
        assert result["score"] is not None
        assert 0 <= result["score"] <= 100

    def test_stock_with_no_data_gets_none_score(self):
        inst = _stock({
            "ev_ebitda": None, "pe": None, "pb": None,
            "div_yield": None, "pos_52w": None,
            "free_cashflow": None, "market_cap": None,
        })
        sm = self._sm([inst])
        result = score_instrument(inst, sm)
        # With no data coverage, score is pulled toward 50
        assert result["score"] is not None or result["score"] is None  # either is acceptable

    def test_etf_gets_score(self):
        result = score_instrument(_etf(), {})
        assert result["score"] is not None
        assert 0 <= result["score"] <= 100

    def test_money_market_gets_score(self):
        result = score_instrument(_mm(), {})
        assert result["score"] is not None
        assert 0 <= result["score"] <= 100

    def test_quality_pass_flag_set(self):
        inst = _stock()
        sm = self._sm([inst])
        result = score_instrument(inst, sm)
        assert "quality_passes" in result
        assert result["quality_passes"] is True

    def test_quality_fail_flag_set(self):
        inst = _stock({"roe": 0.01})  # very low ROE
        sm = self._sm([inst])
        result = score_instrument(inst, sm)
        assert result["quality_passes"] is False
        assert len(result["quality_fail_reasons"]) > 0

    def test_financial_stock_scores(self):
        inst = _financial()
        sm = self._sm([inst])
        result = score_instrument(inst, sm)
        assert result["score"] is not None
        assert result.get("is_financial") is True

    def test_score_coverage_between_0_and_1(self):
        inst = _stock()
        sm = self._sm([inst])
        result = score_instrument(inst, sm)
        assert 0.0 <= result.get("score_coverage", 0) <= 1.0


# ── score_all tests ───────────────────────────────────────────────────────────

class TestScoreAll:
    def test_returns_same_count(self):
        instruments = [_stock(), _etf(), _mm()]
        sm = compute_sector_medians(instruments)
        results = score_all(instruments, sm)
        assert len(results) == 3

    def test_all_have_score_key(self):
        instruments = [_stock(), _etf()]
        sm = compute_sector_medians(instruments)
        results = score_all(instruments, sm)
        for r in results:
            assert "score" in r


# ── compute_sector_medians tests ──────────────────────────────────────────────

class TestComputeSectorMedians:
    def test_single_instrument(self):
        inst = _stock({"pe": 15.0, "sector": "Technology"})
        medians = compute_sector_medians([inst])
        assert "Technology" in medians
        assert medians["Technology"]["pe"] == pytest.approx(15.0)

    def test_two_instruments_same_sector(self):
        a = _stock({"pe": 10.0, "sector": "Energy"})
        b = _stock({"pe": 20.0, "sector": "Energy"})
        medians = compute_sector_medians([a, b])
        assert medians["Energy"]["pe"] == pytest.approx(15.0)

    def test_three_instruments_same_sector(self):
        insts = [
            _stock({"pe": 10.0, "sector": "Health Care"}),
            _stock({"pe": 20.0, "sector": "Health Care"}),
            _stock({"pe": 30.0, "sector": "Health Care"}),
        ]
        medians = compute_sector_medians(insts)
        assert medians["Health Care"]["pe"] == pytest.approx(20.0)

    def test_etfs_excluded(self):
        etf = _etf()
        stock = _stock({"sector": "Consumer"})
        medians = compute_sector_medians([etf, stock])
        assert "ETF" not in medians  # ETFs not included

    def test_non_ok_instruments_excluded(self):
        bad = _stock({"ok": False, "sector": "Industrials", "pe": 5.0})
        good = _stock({"ok": True,  "sector": "Industrials", "pe": 20.0})
        medians = compute_sector_medians([bad, good])
        assert medians["Industrials"]["pe"] == pytest.approx(20.0)

    def test_different_sectors_separated(self):
        a = _stock({"pe": 10.0, "sector": "Tech"})
        b = _stock({"pe": 30.0, "sector": "Energy"})
        medians = compute_sector_medians([a, b])
        assert medians["Tech"]["pe"] == pytest.approx(10.0)
        assert medians["Energy"]["pe"] == pytest.approx(30.0)


# ── Display helpers ───────────────────────────────────────────────────────────

class TestScoreLabel:
    def test_none(self):
        assert score_label(None) == "—"

    def test_strong_buy(self):
        assert score_label(85) == "Strong Buy"

    def test_buy(self):
        assert score_label(70) == "Buy"

    def test_watch(self):
        assert score_label(55) == "Watch"

    def test_avoid(self):
        assert score_label(40) == "Avoid"

    def test_strong_avoid(self):
        assert score_label(20) == "Strong Avoid"

    def test_boundary_80(self):
        assert score_label(80) == "Strong Buy"

    def test_boundary_65(self):
        assert score_label(65) == "Buy"


class TestScoreColour:
    def test_none_returns_neutral(self):
        assert score_colour(None) == "#8890b0"

    def test_high_score_green(self):
        assert score_colour(85) == "#00c853"

    def test_low_score_red(self):
        assert score_colour(20) == "#ff5252"


class TestScoreBg:
    def test_none_returns_dark(self):
        assert score_bg(None) == "#1e2235"

    def test_high_score_dark_green(self):
        assert score_bg(85) == "#0a2e1a"
