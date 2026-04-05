@echo off
REM ── Value Screener — Windows Launcher ──────────────────────────────────────
REM Double-click this file to start the app.

cd /d "%~dp0"

echo.
echo   ^>^> Value Screener
echo   ─────────────────────────────────

REM ── Locate a compatible Python (3.13 preferred, 3.12 fallback) ─────────────
REM Streamlit requires Python 3.10-3.13. Python 3.14+ is not yet supported.

SET PYTHON=

REM Try versioned executables first (py launcher or named binaries)
FOR %%V IN (3.13 3.12 3.11 3.10) DO (
    IF NOT DEFINED PYTHON (
        py -%%V --version >nul 2>&1
        IF NOT ERRORLEVEL 1 SET PYTHON=py -%%V
    )
)

REM Fall back to plain 'python' if version is compatible (< 3.14)
IF NOT DEFINED PYTHON (
    python --version >nul 2>&1
    IF NOT ERRORLEVEL 1 (
        FOR /F "tokens=2 delims= " %%V IN ('python --version 2^>^&1') DO SET PYVER=%%V
        REM Extract minor version — reject 3.14+
        FOR /F "tokens=1,2 delims=." %%A IN ("%PYVER%") DO (
            IF %%A EQU 3 (
                IF %%B LEQ 13 SET PYTHON=python
            )
        )
    )
)

IF NOT DEFINED PYTHON (
    echo.
    echo   No compatible Python found ^(3.10-3.13 required^).
    echo.
    echo   Your system Python appears to be 3.14+, which is not yet
    echo   supported by Streamlit.
    echo.
    echo   Fix ^(choose one^):
    echo     - Python Launcher: py -3.13 is available after installing Python 3.13
    echo     - Download Python 3.13: https://www.python.org/downloads/release/python-3130/
    echo       IMPORTANT: tick "Add Python to PATH" during install.
    echo.
    pause
    exit /b
)

FOR /F "tokens=*" %%V IN ('%PYTHON% --version 2^>^&1') DO echo   Using %%V ^(%PYTHON%^)

echo   Checking packages ^(first run may take a minute^)...
%PYTHON% -m pip install --quiet --user streamlit yfinance pandas numpy vaderSentiment

echo   Packages ready.
echo.
echo   Opening in your browser...
echo   ^(Close this window to stop the app^)
echo.

%PYTHON% -m streamlit run app.py --server.headless true --browser.gatherUsageStats false --server.port 8501
pause
