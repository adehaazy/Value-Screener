#!/bin/bash
# ── Value Screener — Mac Launcher ──────────────────────────────────────────
# Double-click this file to start the app. That's it.

cd "$(dirname "$0")"

echo ""
echo "  📊 Value Screener"
echo "  ─────────────────────────────────"

# Check Python
if ! command -v python3 &>/dev/null; then
    echo ""
    echo "  ⚠️  Python 3 not found."
    echo "  Please install it from: https://www.python.org/downloads/"
    echo "  Then double-click this file again."
    echo ""
    read -p "  Press Enter to close..."
    exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  ✓ Python $PY_VER found"

# Install/check packages (now includes vaderSentiment for news sentiment)
echo "  Checking required packages…"
python3 -m pip install --quiet --user streamlit yfinance pandas numpy vaderSentiment 2>&1 | \
    grep -v "already satisfied" | grep -v "^$" | grep -v "Requirement" | head -8

echo "  ✓ Packages ready"
echo ""
echo "  Opening in your browser…"
echo "  (Close this window to stop the app)"
echo ""
echo "  💡 Tip: Run surveillance from the Signals page inside the app"
echo "     or schedule it daily by adding this to cron (crontab -e):"
echo "     0 6 * * 1-5 cd $(pwd) && python3 surveillance/run_surveillance.py --quiet"
echo ""

# Launch
python3 -m streamlit run app.py \
    --server.headless true \
    --browser.gatherUsageStats false \
    --server.port 8501
