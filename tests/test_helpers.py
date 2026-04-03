"""
tests/test_helpers.py — Unit tests for utils/helpers.py
"""
import math
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.helpers import _f, _clamp, _pct, _x, _fmt_pct, _fmt_ratio, _fmt_price, _fmt_aum


class TestF:
    def test_none_returns_none(self):
        assert _f(None) is None

    def test_int(self):
        assert _f(5) == 5.0

    def test_float_string(self):
        assert _f("3.14") == pytest.approx(3.14)

    def test_nan_returns_none(self):
        assert _f(float("nan")) is None

    def test_inf_returns_none(self):
        assert _f(float("inf")) is None
        assert _f(float("-inf")) is None

    def test_non_numeric_string_returns_none(self):
        assert _f("hello") is None

    def test_zero(self):
        assert _f(0) == 0.0

    def test_negative(self):
        assert _f(-42.5) == -42.5


class TestClamp:
    def test_within_range(self):
        assert _clamp(50.0) == 50.0

    def test_below_min(self):
        assert _clamp(-10.0) == 0.0

    def test_above_max(self):
        assert _clamp(110.0) == 100.0

    def test_at_boundaries(self):
        assert _clamp(0.0) == 0.0
        assert _clamp(100.0) == 100.0

    def test_custom_bounds(self):
        assert _clamp(5.0, lo=10.0, hi=20.0) == 10.0
        assert _clamp(25.0, lo=10.0, hi=20.0) == 20.0
        assert _clamp(15.0, lo=10.0, hi=20.0) == 15.0


class TestPct:
    def test_none(self):
        assert _pct(None) == "N/A"

    def test_decimal_to_pct(self):
        assert _pct(0.15) == "15.0%"

    def test_custom_decimals(self):
        assert _pct(0.1234, decimals=2) == "12.34%"


class TestX:
    def test_none(self):
        assert _x(None) == "N/A"

    def test_multiple(self):
        assert _x(12.3) == "12.3x"

    def test_custom_decimals(self):
        assert _x(12.345, decimals=2) == "12.35x"


class TestFmtPct:
    def test_none(self):
        assert _fmt_pct(None) == "—"

    def test_positive(self):
        assert _fmt_pct(3.5) == "+3.5%"

    def test_negative(self):
        assert _fmt_pct(-2.1) == "-2.1%"

    def test_near_zero(self):
        assert _fmt_pct(0.0) == "0.0%"
        assert _fmt_pct(0.04) == "0.0%"


class TestFmtAum:
    def test_none(self):
        assert _fmt_aum(None) == "—"

    def test_billions(self):
        assert _fmt_aum(5_500_000_000) == "$5.5bn"

    def test_millions(self):
        assert _fmt_aum(250_000_000) == "$250m"

    def test_small(self):
        assert _fmt_aum(500_000) == "$500,000"
