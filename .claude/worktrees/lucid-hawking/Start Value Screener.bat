@echo off
REM ── Value Screener — Windows Launcher ──────────────────────────────────────
REM Double-click this file to start the app.

cd /d "%~dp0"

echo.
echo   ^>^> Value Screener
echo   ─────────────────────────────────

python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo   Python not found.
    echo   Please install it from: https://www.python.org/downloads/
    echo   IMPORTANT: tick "Add Python to PATH" during install.
    echo   Then double-click this file again.
    echo.
    pause
    exit /b
)

echo   Checking packages ^(first run may take a minute^)...
python -m pip install --quiet --user streamlit yfinance pandas numpy vaderSentiment

echo   Packages ready.
echo.
echo   Opening in your browser...
echo   ^(Close this window to stop the app^)
echo.

python -m streamlit run app.py --server.headless true --browser.gatherUsageStats false --server.port 8501
pause
