#!/usr/bin/env python3
"""
scripts/refresh_prices.py — Morning price cache refresh.

Refreshes all price data (15-min TTL layer) without touching fundamentals
(7-day TTL). Runs in ~2-3 minutes for 655 instruments vs. 20+ for a full
re-fetch. Designed to be called by the scheduled task at market open so
the app loads instantly with live prices.

Usage:
    cd "Value Screener v3"
    python3 scripts/refresh_prices.py
"""

import sys, time, json
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from data.universe import UNIVERSE
from data.fetcher  import refresh_all_prices, save_scan_summary, fetch_one
from utils.scoring_engine import score_all, compute_sector_medians as _csm
from utils.verdicts import add_verdicts

def main():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Value Screener — Morning Cache Refresh")
    print("-" * 55)

    # Collect all tickers from universe
    all_tickers = []
    for group, meta in UNIVERSE.items():
        for ticker, name in meta["tickers"].items():
            all_tickers.append((ticker, name, meta["asset_class"], group))

    total = len(all_tickers)
    print(f"Refreshing prices for {total} instruments...")

    t0 = time.time()
    ok_count = 0
    failed = []

    def _progress(pct, msg):
        bar_len = 30
        filled = int(bar_len * pct)
        bar = "#" * filled + "-" * (bar_len - filled)
        print(f"\r  [{bar}] {int(pct*100):3d}%  {msg[:40]:<40}", end="", flush=True)

    results = refresh_all_prices(all_tickers, progress_cb=_progress)
    print()  # newline after progress bar

    for r in results:
        if r.get("ok"):
            ok_count += 1
        else:
            failed.append(r.get("ticker", "?"))

    elapsed = time.time() - t0
    print(f"\n  Done: {ok_count}/{total} refreshed in {elapsed:.0f}s")

    if failed:
        print(f"  Failed ({len(failed)}): {', '.join(failed[:10])}"
              + (" ..." if len(failed) > 10 else ""))

    # Rebuild scan summary so the dashboard tiles are current
    print("\nUpdating scan summary...")
    from utils.scoring_engine import score_all
    scored = score_all(results, _csm(results))
    scored = add_verdicts(scored, _csm(results))
    ok_scored = [x for x in scored if x.get("ok")]

    save_scan_summary({
        "total": len(ok_scored),
        "stocks_passing_quality": sum(
            1 for x in ok_scored
            if x.get("asset_class") == "Stock" and x.get("quality_passes")
        ),
        "strong_value": sum(
            1 for x in ok_scored if (x.get("score") or 0) >= 75
        ),
        "top_picks": [
            {"ticker": x["ticker"], "name": x["name"],
             "score": x.get("score"), "verdict": x.get("verdict", "")}
            for x in sorted(ok_scored,
                            key=lambda r: r.get("score") or 0, reverse=True)[:5]
        ],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    })

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Refresh complete.")


if __name__ == "__main__":
    main()
