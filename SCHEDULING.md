# Scheduling Surveillance — Zero Cost, Runs While You Sleep

## Mac: cron (built-in, no install needed)

Run surveillance every weekday at 6:00am:

```bash
# Open your cron editor
crontab -e

# Add this line (replace /path/to with your actual folder path)
0 6 * * 1-5 cd /path/to/screener-v3 && python3 surveillance/run_surveillance.py --quiet
```

To find your folder path: right-click the screener folder → Get Info → copy the path shown.

## Mac: launchd (more reliable than cron, survives sleep)

Create `/Library/LaunchAgents/com.valuescreener.surveillance.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.valuescreener.surveillance</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/path/to/screener-v3/surveillance/run_surveillance.py</string>
        <string>--quiet</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>6</integer>
        <key>Minute</key>
        <integer>0</integer>
        <key>Weekday</key>
        <integer>1</integer>
    </dict>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
```

Then load it:
```bash
launchctl load ~/Library/LaunchAgents/com.valuescreener.surveillance.plist
```

## Windows: Task Scheduler

1. Open Task Scheduler → Create Basic Task
2. Trigger: Daily, 6:00am, weekdays
3. Action: Start a program
   - Program: `python`
   - Arguments: `surveillance/run_surveillance.py --quiet`
   - Start in: `C:\path\to\screener-v3`

## Manual run (on demand)

```bash
cd screener-v3
python3 surveillance/run_surveillance.py          # normal run (uses caches)
python3 surveillance/run_surveillance.py --force  # bypass all caches, re-fetch everything
```

## What the scheduler does

1. Refreshes any stale instrument caches (yfinance, 6h TTL)
2. Fetches FRED macro data (4h TTL)
3. Fetches UK macro from BoE (6h TTL)
4. Pulls RSS headlines from Reuters, BBC, FT and scores sentiment (1h TTL)
5. Checks SEC EDGAR for 8-K filings from US tickers (4h TTL)
6. Checks OpenInsider for cluster buying signals (6h TTL)
7. Runs signals engine — compares against last snapshot, detects drift
8. Generates morning briefing

**First run**: 3–8 minutes (cold caches)
**Subsequent runs**: under 30 seconds (warm caches)
**Cost**: £0
