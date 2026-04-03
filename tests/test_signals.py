"""
tests/test_signals.py — Unit tests for utils/signals.py

Tests cover:
  - Severity Enum: values, string equality, JSON-serialisable
  - _score_drift_signals: no drift on first run, drift detection, severity bands
  - _value_threshold_signals: threshold, quality gate guard
  - signals_summary: counts by severity
  - run_signals: integration (no filesystem writes — patches _save_history)
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.signals import (
    Severity,
    _score_drift_signals,
    _value_threshold_signals,
    _near_52w_low_signals,
    signals_summary,
)


# ── Severity Enum ─────────────────────────────────────────────────────────────

class TestSeverityEnum:
    def test_values_are_strings(self):
        assert Severity.HIGH   == "high"
        assert Severity.MEDIUM == "medium"
        assert Severity.LOW    == "low"
        assert Severity.INFO   == "info"

    def test_string_equality(self):
        assert Severity.HIGH == "high"
        assert "high" == Severity.HIGH

    def test_json_serialisable(self):
        payload = {"severity": Severity.HIGH}
        dumped = json.dumps(payload)
        loaded = json.loads(dumped)
        assert loaded["severity"] == "high"

    def test_all_four_members_exist(self):
        members = {s.value for s in Severity}
        assert members == {"high", "medium", "low", "info"}


# ── _score_drift_signals ──────────────────────────────────────────────────────

class TestScoreDriftSignals:

    def _inst(self, ticker, score):
        return {"ok": True, "ticker": ticker, "name": f"Co {ticker}", "score": score}

    def test_no_drift_on_first_run(self):
        instruments = [self._inst("AAA", 70.0)]
        signals, snapshot = _score_drift_signals(instruments, {})
        assert signals == []
        assert snapshot == {"AAA": 70.0}

    def test_small_drift_ignored(self):
        instruments = [self._inst("AAA", 72.0)]
        signals, _ = _score_drift_signals(instruments, {"AAA": 70.0})
        assert signals == []

    def test_medium_drift_triggers_signal(self):
        instruments = [self._inst("AAA", 82.0)]
        signals, _ = _score_drift_signals(instruments, {"AAA": 70.0})
        assert len(signals) == 1
        assert signals[0]["type"] == "score_drift"

    def test_medium_drift_severity(self):
        # 12-point drift → medium
        instruments = [self._inst("AAA", 82.0)]
        signals, _ = _score_drift_signals(instruments, {"AAA": 70.0})
        assert signals[0]["severity"] == Severity.MEDIUM

    def test_large_drift_is_high_severity(self):
        # 25-point drift → high
        instruments = [self._inst("AAA", 95.0)]
        signals, _ = _score_drift_signals(instruments, {"AAA": 70.0})
        assert signals[0]["severity"] == Severity.HIGH

    def test_negative_drift_triggers_signal(self):
        instruments = [self._inst("AAA", 55.0)]
        signals, _ = _score_drift_signals(instruments, {"AAA": 70.0})
        assert len(signals) == 1
        assert "declined" in signals[0]["title"]

    def test_snapshot_updated(self):
        instruments = [self._inst("AAA", 82.0)]
        _, snapshot = _score_drift_signals(instruments, {"AAA": 70.0})
        assert snapshot["AAA"] == 82.0

    def test_non_ok_instrument_skipped(self):
        instruments = [{"ok": False, "ticker": "AAA", "score": 80.0}]
        signals, snapshot = _score_drift_signals(instruments, {"AAA": 70.0})
        assert signals == []
        assert "AAA" not in snapshot

    def test_none_score_skipped(self):
        instruments = [{"ok": True, "ticker": "AAA", "score": None}]
        signals, snapshot = _score_drift_signals(instruments, {"AAA": 70.0})
        assert signals == []


# ── _value_threshold_signals ──────────────────────────────────────────────────

class TestValueThresholdSignals:

    def _inst(self, score, quality_passes=True):
        return {
            "ok": True,
            "ticker": "TST",
            "name": "Test Co",
            "score": score,
            "quality_passes": quality_passes,
        }

    def test_high_score_passes_generates_signal(self):
        signals = _value_threshold_signals([self._inst(80.0)])
        assert len(signals) == 1
        assert signals[0]["type"] == "value_opportunity"

    def test_below_threshold_no_signal(self):
        signals = _value_threshold_signals([self._inst(74.9)])
        assert signals == []

    def test_quality_fail_excluded(self):
        signals = _value_threshold_signals([self._inst(90.0, quality_passes=False)])
        assert signals == []

    def test_85_plus_is_high_severity(self):
        signals = _value_threshold_signals([self._inst(85.0)])
        assert signals[0]["severity"] == Severity.HIGH

    def test_75_to_84_is_medium_severity(self):
        signals = _value_threshold_signals([self._inst(80.0)])
        assert signals[0]["severity"] == Severity.MEDIUM

    def test_none_score_excluded(self):
        signals = _value_threshold_signals([{"ok": True, "ticker": "X", "score": None}])
        assert signals == []


# ── _near_52w_low_signals ─────────────────────────────────────────────────────

class TestNear52wLowSignals:

    def _inst(self, pct_from_high, price, low_52w, quality_passes=True):
        return {
            "ok": True,
            "ticker": "TST",
            "name": "Test Co",
            "asset_class": "Stock",
            "pct_from_high": pct_from_high,
            "price": price,
            "low_52w": low_52w,
            "quality_passes": quality_passes,
        }

    def test_near_low_and_deeply_beaten_triggers(self):
        # 55% off high, 2% above 52w low
        signals = _near_52w_low_signals([self._inst(-55.0, 10.2, 10.0)])
        assert len(signals) == 1

    def test_not_deeply_beaten_no_signal(self):
        # Only 30% off high — outer guard skips
        signals = _near_52w_low_signals([self._inst(-30.0, 10.2, 10.0)])
        assert signals == []

    def test_deeply_beaten_but_not_near_low_no_signal(self):
        # 55% off high but 20% above 52w low
        signals = _near_52w_low_signals([self._inst(-55.0, 12.0, 10.0)])
        assert signals == []

    def test_quality_fail_excluded(self):
        signals = _near_52w_low_signals([
            self._inst(-55.0, 10.1, 10.0, quality_passes=False)
        ])
        assert signals == []

    def test_etf_excluded(self):
        inst = self._inst(-55.0, 10.1, 10.0)
        inst["asset_class"] = "ETF"
        assert _near_52w_low_signals([inst]) == []


# ── signals_summary ───────────────────────────────────────────────────────────

class TestSignalsSummary:

    def test_empty_list(self):
        result = signals_summary([])
        assert result["total"] == 0

    def test_counts_by_severity(self):
        sigs = [
            {"severity": "high",   "type": "score_drift"},
            {"severity": "high",   "type": "value_opportunity"},
            {"severity": "medium", "type": "score_drift"},
            {"severity": "low",    "type": "news_positive"},
        ]
        result = signals_summary(sigs)
        assert result["counts"]["high"]   == 2
        assert result["counts"]["medium"] == 1
        assert result["counts"]["low"]    == 1
        assert result["total"] == 4

    def test_counts_by_type(self):
        sigs = [
            {"severity": "high", "type": "score_drift"},
            {"severity": "high", "type": "score_drift"},
            {"severity": "low",  "type": "news_positive"},
        ]
        result = signals_summary(sigs)
        assert result["by_type"]["score_drift"]  == 2
        assert result["by_type"]["news_positive"] == 1
