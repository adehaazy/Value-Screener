"""
Surveillance runner — Layer 1 + 2 orchestration.

Can be run in two ways:
  1. Via the Streamlit app (on-demand, with progress UI)
  2. As a standalone script for scheduled/background use:
       python3 run_surveillance.py
       python3 run_surveillance.py --force   # bypass all caches

Design for compute efficiency:
  - Only fetches yfinance data for tickers with stale cache (>6h)
  - External API calls (FRED, RSS, EDGAR, OpenInsider) each have their own TTL
  - A complete run on a cold cache typically takes 3–8 minutes
  - Subsequent runs (warm cache) complete in under 30 seconds
  - Run this once daily (e.g. 6am via cron/launchd) for zero-latency app experience
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.universe    import UNIVERSE
from data.fetcher     import fetch_one, compute_sector_medians, _cache_is_fresh
from data.sources     import run_all_sources
from utils.scoring    import score_all, DEFAULT_QUALITY_THRESHOLDS
from utils.verdicts   import add_verdicts
from utils.signals    import run_signals
from surveillance.briefing import generate_briefing


def _all_tickers() -> list[str]:
    tickers = []
    for group_data in UNIVERSE.values():
        tickers.extend(group_data["tickers"].keys())
    return tickers


def _load_watchlist() -> list[str]:
    """Load watchlist ticker strings from disk.
    watchlist.json stores a list of dicts; extract just the ticker strings.
    """
    cache_dir = Path(__file__).parent.parent / "cache"
    wl_file = cache_dir / "watchlist.json"
    if wl_file.exists():
        try:
            import json
            data = json.loads(wl_file.read_text())
            # Handle both [{"ticker": "AAPL", ...}] and ["AAPL", ...]
            if data and isinstance(data[0], dict):
                return [entry["ticker"] for entry in data if "ticker" in entry]
            return [str(t) for t in data]
        except Exception:
            pass
    return []


def run(force: bool = False, verbose: bool = True) -> dict:
    """
    Full surveillance run.

    Args:
        force:   bypass all caches (re-fetch everything)
        verbose: print progress to stdout

    Returns: briefing dict
    """
    start_time = datetime.now()

    def log(msg: str):
        if verbose:
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[{ts}] {msg}")

    log("═" * 60)
    log("  Value Screener — Surveillance Run")
    log(f"  {datetime.now().strftime('%A %d %B %Y %H:%M')}")
    log("═" * 60)

    # ── Step 1: Fetch instrument data ──────────────────────────────────────────
    log("\n[1/5] Fetching instrument data...")
    all_instruments = []
    all_tickers = _all_tickers()
    stale = [t for t in all_tickers if not _cache_is_fresh(t)]
    fresh = len(all_tickers) - len(stale)

    log(f"      Universe: {len(all_tickers)} instruments | {fresh} cached | {len(stale)} to fetch")

    for group_name, group_data in UNIVERSE.items():
        asset_class = group_data["asset_class"]
        for ticker, name in group_data["tickers"].items():
            inst = fetch_one(ticker, name, asset_class, group_name)
            all_instruments.append(inst)

    ok_count = sum(1 for i in all_instruments if i.get("ok"))
    log(f"      Done. {ok_count}/{len(all_instruments)} instruments loaded successfully.")

    # ── Step 2: Score all instruments ─────────────────────────────────────────
    log("\n[2/5] Scoring instruments...")
    sector_medians = compute_sector_medians(all_instruments)
    scored = score_all(all_instruments, sector_medians, DEFAULT_QUALITY_THRESHOLDS)
    scored = add_verdicts(scored, sector_medians)
    log(f"      Done. {len(scored)} instruments scored.")

    # ── Step 3: Fetch surveillance data (macro + news + filings) ──────────────
    log("\n[3/5] Fetching surveillance data (macro, news, filings)...")
    log("      FRED macro indicators...")
    surveillance_data = run_all_sources(tickers=all_tickers, force=force)
    macro_us = surveillance_data.get("macro_us", {})
    macro_uk = surveillance_data.get("macro_uk", {})
    news     = surveillance_data.get("news", {})
    insider  = surveillance_data.get("insider", {})
    edgar    = surveillance_data.get("edgar", {})
    log(f"      Macro: {len(macro_us.get('signals', []))} US signals, "
        f"{len(macro_uk.get('signals', []))} UK signals")
    log(f"      News: {news.get('total', 0)} headlines fetched")
    log(f"      Insider: {len(insider.get('cluster_signals', []))} cluster buy signals")
    log(f"      EDGAR: {len(edgar.get('events', {}))} tickers with recent 8-K filings")

    # ── Step 4: Run signals engine ─────────────────────────────────────────────
    log("\n[4/5] Running signals engine...")
    watchlist = _load_watchlist()
    signals = run_signals(
        instruments       = scored,
        surveillance_data = surveillance_data,
        watchlist         = watchlist,
    )
    high_count   = sum(1 for s in signals if s.get("severity") == "high")
    medium_count = sum(1 for s in signals if s.get("severity") == "medium")
    log(f"      {len(signals)} signals generated: {high_count} high, {medium_count} medium")

    # ── Step 5: Generate briefing ──────────────────────────────────────────────
    log("\n[5/5] Generating morning briefing...")
    briefing = generate_briefing(
        instruments       = scored,
        signals           = signals,
        surveillance_data = surveillance_data,
        watchlist         = watchlist,
    )
    log(f"      Headline: {briefing['headline']}")

    elapsed = (datetime.now() - start_time).total_seconds()
    log(f"\n✓ Surveillance complete in {elapsed:.1f}s")
    log("  Briefing saved. Open the app to view results.\n")

    return briefing


# ── CLI entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Value Screener Surveillance Runner")
    parser.add_argument("--force", action="store_true",
                        help="Bypass all caches and re-fetch everything")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress output (for cron/launchd use)")
    args = parser.parse_args()

    run(force=args.force, verbose=not args.quiet)
