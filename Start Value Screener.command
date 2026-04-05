#!/bin/bash
# ── Value Screener — Mac Launcher ──────────────────────────────────────────
# Double-click this file to start the app. That's it.

cd "$(dirname "$0")"

echo ""
echo "  📊 Value Screener"
echo "  ─────────────────────────────────"

# ── Locate a compatible Python (3.13 preferred, 3.12 fallback) ─────────────
# Streamlit requires Python 3.10–3.13. Python 3.14+ is not yet supported.
PYTHON=""

for candidate in python3.13 python3.12 python3.11 python3.10; do
    if command -v "$candidate" &>/dev/null; then
        PYTHON="$candidate"
        break
    fi
done

# Also check pyenv shim or Homebrew-managed python3 but only if it's < 3.14
if [ -z "$PYTHON" ] && command -v python3 &>/dev/null; then
    RAW=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    MAJOR=$(echo "$RAW" | cut -d. -f1)
    MINOR=$(echo "$RAW" | cut -d. -f2)
    if [ "$MAJOR" -eq 3 ] && [ "$MINOR" -le 13 ]; then
        PYTHON="python3"
    fi
fi

if [ -z "$PYTHON" ]; then
    echo ""
    echo "  ⚠️  No compatible Python found (3.10–3.13 required)."
    echo ""
    echo "  Your system Python appears to be 3.14+, which is not yet"
    echo "  supported by Streamlit."
    echo ""
    echo "  Fix (choose one):"
    echo "    • Homebrew:  brew install python@3.13"
    echo "    • pyenv:     pyenv install 3.13 && pyenv local 3.13"
    echo "    • Official:  https://www.python.org/downloads/release/python-3130/"
    echo ""
    read -p "  Press Enter to close..."
    exit 1
fi

PY_VER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
echo "  ✓ Using Python $PY_VER ($PYTHON)"

# Install/check packages
echo "  Checking required packages…"
"$PYTHON" -m pip install --quiet --user streamlit yfinance pandas numpy vaderSentiment 2>&1 | \
    grep -v "already satisfied" | grep -v "^$" | grep -v "Requirement" | head -8

echo "  ✓ Packages ready"
echo ""
echo "  Opening in your browser…"
echo "  (Close this window to stop the app)"
echo ""
echo "  💡 Tip: Run surveillance from the Signals page inside the app"
echo "     or schedule it daily by adding this to cron (crontab -e):"
echo "     0 6 * * 1-5 cd $(pwd) && $PYTHON surveillance/run_surveillance.py --quiet"
echo ""

# Launch
"$PYTHON" -m streamlit run app.py \
    --server.headless true \
    --browser.gatherUsageStats false \
    --server.port 8501
