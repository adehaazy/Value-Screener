# Value Screener — Local Development

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Node.js | 18 + | https://nodejs.org |
| Python | 3.10 – 3.13 | https://python.org |
| npm | ships with Node | — |
| pip | ships with Python | — |

---

## 1. Start the backend

```bash
cd "Value Screener v3"

# First time only
pip install -r requirements.txt

# Start the FastAPI server
uvicorn main:app --reload --port 8000
```

API is live at **http://localhost:8000**
Swagger docs at **http://localhost:8000/docs**

Quick health check:
```bash
curl http://localhost:8000/health
# → {"status":"ok","cache_populated":true}
```

---

## 2. Start the frontend

Open a **second terminal**:

```bash
cd "value screener/value-screener-app"

# First time only
npm install

# Start Vite dev server
npm run dev
```

App is live at **http://localhost:5173**

The frontend is pre-configured to talk to `https://value-screener.onrender.com`
(the deployed backend). To point it at your local backend instead, edit
`src/api/client.js`:

```js
// Change this line:
export const API_BASE = 'https://value-screener.onrender.com'

// To:
export const API_BASE = 'http://localhost:8000'
```

---

## 3. Key API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Health check |
| GET | `/api/screener` | All scored instruments |
| GET | `/api/watchlist` | Saved watchlist with live data |
| GET | `/api/briefing` | Latest market briefing |
| GET | `/api/signals` | Alerts & score drift signals |
| GET | `/api/macro` | US + UK macro indicators |
| GET | `/api/portfolio` | Holdings + P&L + scored instrument data |
| POST | `/api/portfolio` | Add / update a holding (upsert by ticker) |
| DELETE | `/api/portfolio/{ticker}` | Remove a holding |

### Add a test holding

```bash
curl -s -X POST http://localhost:8000/api/portfolio \
  -H "Content-Type: application/json" \
  -d '{
    "ticker": "AAPL",
    "shares": 10,
    "avg_cost": 165.00,
    "currency": "USD",
    "account": "ISA",
    "notes": "Core tech holding",
    "target_weight": 15.0
  }'
```

### Remove it

```bash
curl -X DELETE http://localhost:8000/api/portfolio/AAPL
```

---

## 4. Frontend page structure

```
/              Home        — hero + 4 expandable quadrants + ticker strip
/deepdive      Deep Dive   — per-ticker deep analysis
/screen        Screener    — full universe table
/portfolio     Portfolio   — holdings, charts, table
/briefing      Briefing    — AI market briefing
/settings      Settings    — preferences
```

---

## 5. Build for production

```bash
# In value-screener-app/
npm run build
# Output goes to dist/
```

---

## 6. Repository structure

```
value screener/
└── value-screener-app/     ← React + Vite frontend
    ├── src/
    │   ├── App.jsx          Router entry
    │   ├── Root.tsx         Shell: nav + ticker + page transitions
    │   ├── theme.css        All design tokens + component CSS
    │   ├── api/
    │   │   ├── client.js    API fetch functions
    │   │   └── useApi.js    Generic data-fetching hook
    │   ├── components/
    │   │   ├── StockLogo.tsx   Logo with 3-tier fallback
    │   │   └── PaginatedList.tsx  Animated paginated list
    │   └── pages/
    │       ├── Home.tsx     Dashboard (motion/react layout animations)
    │       ├── Portfolio.tsx  Holdings + Recharts
    │       └── ...          Other pages (stub JSX)

Value Screener v3/          ← Python FastAPI + Streamlit backend
    ├── main.py              FastAPI JSON API (7 endpoints)
    ├── app.py               Streamlit UI
    ├── user_data.py         Holdings / watchlist / prefs persistence
    ├── data/                Universe, fetcher, cache
    ├── utils/               Scoring, verdicts, signals
    └── cache/               SQLite + JSON data cache
```
