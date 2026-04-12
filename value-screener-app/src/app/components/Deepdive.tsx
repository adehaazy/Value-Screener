import { useState, useMemo, useEffect, useCallback, useRef } from "react";
import { Link, useSearchParams, useNavigate } from "react-router";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ResponsiveContainer,
  BarChart,
  Bar,
} from "recharts";
import {
  ChevronLeft,
  Search,
  ArrowUpRight,
  ArrowDownRight,
  Bookmark,
  BookmarkCheck,
  Loader2,
  TrendingUp,
  TrendingDown,
  AlertCircle,
  Clock,
  FileText,
  Check,
  ExternalLink,
  RefreshCw,
  Info,
} from "lucide-react";
import { cn } from "../utils";
import { useAppData } from "../useAppData";
import { addToWatchlist } from "../../api/client";

// ─── API base (mirrors client.js) ────────────────────────────────────────────
const API_BASE = "https://value-screener.onrender.com";

// ─── Types ────────────────────────────────────────────────────────────────────
interface PricePoint { date: string; price: number }
interface DividendPoint { date: string; amount: number }
interface DeepDiveData {
  instrument: Record<string, any>;
  thesis: string | null;
  thesis_from_cache: boolean;
  thesis_cached_at: string | null;
  rate_limited: boolean;
  calls_remaining: number;
}
interface DividendData {
  div_yield: number | null;
  five_year_avg_yield: number | null;
  last_dividend: number | null;
  last_ex_date: string | null;
  payment_frequency: string;
  dividends_per_year: number | null;
  payout_ratio: number | null;
  dividend_growth_3y: number | null;
  history: DividendPoint[];
  roe: number | null;
  summary: string;
  generated_at: string;
  symbol: string;
}

// ─── Currency helpers (keep in sync with Screener/Watchlist) ─────────────────
function currencySymbol(inst: Record<string, any>): string {
  const c = (inst.currency || "").toUpperCase();
  if (c === "GBP" || c === "GBX") return "£";
  if (c === "USD") return "$";
  if (c === "EUR") return "€";
  return "";
}

function fmtPrice(inst: Record<string, any>): string {
  if (inst.price == null) return "—";
  const c = (inst.currency || "").toUpperCase();
  const sym = currencySymbol(inst);
  const px = Number(inst.price);
  if (c === "GBX") return `${px.toFixed(0)}p`;
  return `${sym}${px.toFixed(2)}`;
}

function fmtMCap(inst: Record<string, any>): string {
  const mc = inst.market_cap;
  if (mc == null) return "—";
  const sym = currencySymbol(inst);
  const n = Number(mc);
  if (n >= 1e12) return `${sym}${(n / 1e12).toFixed(2)}T`;
  if (n >= 1e9)  return `${sym}${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6)  return `${sym}${(n / 1e6).toFixed(0)}M`;
  return `${sym}${n.toFixed(0)}`;
}

function fmtLargeNum(value: number | null | undefined, sym: string): string {
  if (value == null) return "—";
  const n = Number(value);
  const neg = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  if (abs >= 1e12) return `${neg}${sym}${(abs / 1e12).toFixed(2)}T`;
  if (abs >= 1e9)  return `${neg}${sym}${(abs / 1e9).toFixed(1)}B`;
  if (abs >= 1e6)  return `${neg}${sym}${(abs / 1e6).toFixed(0)}M`;
  return `${neg}${sym}${abs.toFixed(0)}`;
}

function fmtPct(v: number | null | undefined, decimals = 1): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${Number(v).toFixed(decimals)}%`;
}

function fmtX(v: number | null | undefined, decimals = 1): string {
  if (v == null) return "—";
  return `${Number(v).toFixed(decimals)}x`;
}

// ─── Signal pill (same pastel palette as Screener) ────────────────────────────
function signalPill(label: string | null | undefined) {
  const l = (label || "").toLowerCase();
  if (l === "strong buy")   return { text: "Strong Buy",   cls: "bg-[#D6EDDF] text-[#1E5C38]" };
  if (l === "buy")          return { text: "Buy",          cls: "bg-[#E8F4EC] text-[#2E7D52]" };
  if (l === "watch")        return { text: "Watch",        cls: "bg-[#FFF8E1] text-[#A67C00]" };
  if (l === "avoid")        return { text: "Avoid",        cls: "bg-[#FDECEA] text-[#B71C1C]" };
  if (l === "strong avoid") return { text: "Strong Avoid", cls: "bg-[#F5C6C6] text-[#7F1010]" };
  return { text: label || "—", cls: "bg-vs-bg-raised text-vs-ink-mid" };
}

// ─── Period map ──────────────────────────────────────────────────────────────
const TIME_FILTERS = [
  { label: "1M",  api: "1mo" },
  { label: "3M",  api: "3mo" },
  { label: "6M",  api: "6mo" },
  { label: "YTD", api: "ytd" },
  { label: "1Y",  api: "1y"  },
  { label: "5Y",  api: "5y"  },
];

const TABS = ["Overview", "Financials", "Valuation", "Dividends", "News & Signals"];

// ─── Tab placeholder ─────────────────────────────────────────────────────────
function ComingSoon({ tab }: { tab: string }) {
  return (
    <div className="py-16 text-center border border-dashed border-vs-rule">
      <p className="text-[13px] text-vs-ink-soft font-semibold">{tab}</p>
      <p className="text-[12px] text-vs-ink-faint mt-1">Coming soon</p>
    </div>
  );
}

// ─── Custom chart tooltip ─────────────────────────────────────────────────────
function ChartTooltip({ active, payload, label, sym, isGbx }: any) {
  if (!active || !payload?.length) return null;
  const val = Number(payload[0].value);
  const display = isGbx ? `${val.toFixed(0)}p` : `${sym}${val.toFixed(2)}`;
  return (
    <div className="bg-white border border-vs-rule px-3 py-2 text-[11px]">
      <p className="text-vs-ink-soft mb-0.5">{label}</p>
      <p className="font-bold text-vs-ink">{display}</p>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────
export default function Deepdive() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const tickerParam = (searchParams.get("ticker") || "").toUpperCase();

  const [activeTimeFilter, setActiveTimeFilter] = useState(4); // 1Y
  const [activeTab, setActiveTab] = useState(0);

  // Deep dive data
  const [ddData, setDdData] = useState<DeepDiveData | null>(null);
  const [ddLoading, setDdLoading] = useState(false);
  const [ddError, setDdError] = useState<string | null>(null);

  // Price history
  const [priceData, setPriceData] = useState<PricePoint[]>([]);
  const [chartLoading, setChartLoading] = useState(false);

  // Dividend data
  const [divData, setDivData] = useState<DividendData | null>(null);
  const [divLoading, setDivLoading] = useState(false);
  const [divError, setDivError] = useState<string | null>(null);

  // Watchlist state
  const { watchlist, refetchWatchlist } = useAppData();
  const [wlState, setWlState] = useState<"idle" | "adding" | "added">("idle");
  const alreadyOnWatchlist = useMemo(
    () => watchlist.some((w: any) => (w.ticker || w.t || "").toUpperCase() === tickerParam),
    [watchlist, tickerParam]
  );

  // News state
  const [newsItems, setNewsItems] = useState<any[]>([]);
  const [newsLoading, setNewsLoading] = useState(false);

  // Ticker search
  const [searchVal, setSearchVal] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  // ── Fetch deepdive data ────────────────────────────────────────────────────
  useEffect(() => {
    if (!tickerParam) return;
    setDdLoading(true);
    setDdError(null);
    setDdData(null);

    fetch(`${API_BASE}/api/deepdive?ticker=${encodeURIComponent(tickerParam)}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((d) => {
        if (d.ok) {
          setDdData({
            instrument:        d.instrument,
            thesis:            d.thesis,
            thesis_from_cache: d.thesis_from_cache ?? false,
            thesis_cached_at:  d.thesis_cached_at ?? null,
            rate_limited:      d.rate_limited ?? false,
            calls_remaining:   d.calls_remaining ?? 5,
          });
        } else {
          setDdError("No data returned from server.");
        }
      })
      .catch((e) => setDdError(e.message))
      .finally(() => setDdLoading(false));
  }, [tickerParam]);

  // ── Fetch price history ────────────────────────────────────────────────────
  const fetchPriceHistory = useCallback((period: string) => {
    if (!tickerParam) return;
    setChartLoading(true);
    fetch(`${API_BASE}/api/price-history?ticker=${encodeURIComponent(tickerParam)}&period=${period}`)
      .then((r) => r.json())
      .then((d) => {
        if (d.ok && d.data?.length) setPriceData(d.data);
      })
      .catch(() => {})
      .finally(() => setChartLoading(false));
  }, [tickerParam]);

  useEffect(() => {
    fetchPriceHistory(TIME_FILTERS[activeTimeFilter].api);
  }, [tickerParam, activeTimeFilter, fetchPriceHistory]);

  // ── Fetch dividend data (lazy — only when Dividends tab is active) ────────
  const fetchDividends = useCallback((force = false) => {
    if (!tickerParam) return;
    setDivLoading(true);
    setDivError(null);
    if (force) setDivData(null);
    fetch(`${API_BASE}/api/dividends?ticker=${encodeURIComponent(tickerParam)}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((d) => {
        if (d.ok) setDivData(d as DividendData);
        else setDivError("No dividend data available.");
      })
      .catch((e) => setDivError(e.message))
      .finally(() => setDivLoading(false));
  }, [tickerParam]);

  useEffect(() => {
    if (activeTab !== 3 || !tickerParam || divData || divLoading) return;
    fetchDividends();
  }, [activeTab, tickerParam, divData, divLoading, fetchDividends]);

  // Reset dividend state when ticker changes
  useEffect(() => {
    setDivData(null);
    setDivError(null);
  }, [tickerParam]);

  // ── Fetch news (lazy — only when News & Signals tab is active) ────────
  useEffect(() => {
    if (activeTab !== 4 || !tickerParam || newsItems.length || newsLoading) return;
    setNewsLoading(true);
    fetch(`${API_BASE}/api/briefing/news?tickers=${encodeURIComponent(tickerParam)}`)
      .then(r => r.json())
      .then(d => setNewsItems(d.watchlist_news || []))
      .catch(() => {})
      .finally(() => setNewsLoading(false));
  }, [activeTab, tickerParam, newsItems, newsLoading]);

  // Reset news state when ticker changes
  useEffect(() => {
    setNewsItems([]);
    setNewsLoading(false);
  }, [tickerParam]);

  // ── Watchlist handler ──────────────────────────────────────────────────────
  const handleAddWatchlist = useCallback(async () => {
    if (alreadyOnWatchlist || wlState !== "idle" || !ddData) return;
    const name = ddData.instrument.name || ddData.instrument.ticker || tickerParam;
    setWlState("adding");
    try {
      await addToWatchlist(tickerParam, name);
      setWlState("added");
      refetchWatchlist();
      setTimeout(() => setWlState("idle"), 2500);
    } catch {
      setWlState("idle");
    }
  }, [alreadyOnWatchlist, wlState, ddData, tickerParam, refetchWatchlist]);

  // ── Ticker search handler ──────────────────────────────────────────────────
  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const val = searchVal.trim().toUpperCase();
    if (!val) return;
    if (val.length > 15 || !/^[A-Z0-9.\-^=]+$/.test(val)) {
      setSearchVal("");
      return;
    }
    navigate(`/deepdive?ticker=${encodeURIComponent(val)}`);
    setSearchVal("");
  };

  // ── No ticker state ────────────────────────────────────────────────────────
  if (!tickerParam) {
    return (
      <div className="py-20 text-center max-w-[1000px] mx-auto">
        <p className="text-[14px] text-vs-ink-soft">
          Select an instrument from the{" "}
          <Link to="/screener" className="text-vs-accent font-semibold">
            Screener
          </Link>{" "}
          to view its Deep Dive.
        </p>
      </div>
    );
  }

  // ── Loading state ──────────────────────────────────────────────────────────
  if (ddLoading) {
    return (
      <div className="py-20 flex flex-col items-center gap-3 max-w-[1000px] mx-auto">
        <Loader2 className="w-7 h-7 animate-spin text-vs-accent" />
        <p className="text-[13px] text-vs-ink-soft">Loading deep dive for {tickerParam}…</p>
        <p className="text-[11px] text-vs-ink-faint">AI thesis generation may take 10–15 seconds</p>
      </div>
    );
  }

  // ── Error state ────────────────────────────────────────────────────────────
  if (ddError) {
    return (
      <div className="py-20 max-w-[1000px] mx-auto">
        <Link
          to="/screener"
          className="flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wider text-vs-ink-soft hover:text-vs-accent mb-6"
        >
          <ChevronLeft className="w-4 h-4" />
          Back to Screener
        </Link>
        <div className="flex items-start gap-3 bg-[#FDECEA] border border-[#F5C6C6] p-4">
          <AlertCircle className="w-5 h-5 text-[#B71C1C] shrink-0 mt-0.5" />
          <div>
            <p className="text-[13px] font-bold text-[#B71C1C] mb-1">Could not load {tickerParam}</p>
            <p className="text-[12px] text-[#7F1010]">{ddError}</p>
          </div>
        </div>
      </div>
    );
  }

  if (!ddData) return null;

  const inst              = ddData.instrument;
  const thesis            = ddData.thesis;
  const rateLimited       = ddData.rate_limited;
  const thesisFromCache   = ddData.thesis_from_cache;
  const thesisCachedAt    = ddData.thesis_cached_at;

  const ticker   = inst.ticker || tickerParam;
  const name     = inst.name || inst.company || ticker;
  const score    = inst.score ?? null;
  const sector   = inst.sector || "—";
  const exchange = inst.exchange || "";
  const currency = (inst.currency || "").toUpperCase();
  const isGbx    = currency === "GBX";
  const pill     = signalPill(inst.score_label);
  const sym      = currencySymbol(inst);

  const dayChangePct = inst.day_change_pct != null ? inst.day_change_pct * 100 : null;
  const isUp = dayChangePct != null ? dayChangePct >= 0 : true;

  // Key metrics for sidebar
  const keyMetrics = [
    { label: "Market Cap",     value: fmtMCap(inst) },
    { label: "P/E Ratio",      value: fmtX(inst.pe ?? inst.pe_ratio) },
    { label: "P/B Ratio",      value: fmtX(inst.pb ?? inst.pb_ratio) },
    { label: "EV/EBITDA",      value: fmtX(inst.ev_ebitda) },
    { label: "Dividend Yield", value: inst.div_yield != null ? `${Number(inst.div_yield).toFixed(2)}%` : "—" },
    { label: "52W High",       value: inst.high_52w != null ? (isGbx ? `${Number(inst.high_52w).toFixed(0)}p` : `${sym}${Number(inst.high_52w).toFixed(2)}`) : "—" },
    { label: "52W Low",        value: inst.low_52w  != null ? (isGbx ? `${Number(inst.low_52w).toFixed(0)}p`  : `${sym}${Number(inst.low_52w).toFixed(2)}`)  : "—" },
    { label: "1Y Return",      value: fmtPct(inst.yr1_pct) },
    { label: "ROE",            value: inst.roe != null ? `${(Number(inst.roe) * 100).toFixed(1)}%` : "—" },
    { label: "Debt/Equity",    value: inst.debt_equity != null ? `${Number(inst.debt_equity).toFixed(2)}x` : "—" },
  ];

  // ── Financials tab data ────────────────────────────────────────────────────
  const financialsMetrics = [
    { label: "Revenue",          value: fmtLargeNum(inst.revenue, sym) },
    { label: "Revenue Growth",   value: inst.revenue_growth  != null ? fmtPct(inst.revenue_growth  * 100) : "—" },
    { label: "Earnings Growth",  value: inst.earnings_growth != null ? fmtPct(inst.earnings_growth * 100) : "—" },
    { label: "Operating CF",     value: fmtLargeNum(inst.operating_cashflow, sym) },
    { label: "Total Cash",       value: fmtLargeNum(inst.total_cash,         sym) },
    { label: "Total Debt",       value: fmtLargeNum(inst.total_debt,         sym) },
    { label: "ROE",              value: inst.roe          != null ? `${(Number(inst.roe) * 100).toFixed(1)}%` : "—" },
    { label: "Current Ratio",    value: inst.current_ratio != null ? `${Number(inst.current_ratio).toFixed(2)}x` : "—" },
  ];

  // ── Valuation tab data ─────────────────────────────────────────────────────
  const valuationMetrics = [
    { label: "P/E (Trailing)",   value: fmtX(inst.pe ?? inst.pe_ratio) },
    { label: "P/E (Forward)",    value: fmtX(inst.fwd_pe) },
    { label: "P/B",              value: fmtX(inst.pb ?? inst.pb_ratio) },
    { label: "EV/EBITDA",        value: fmtX(inst.ev_ebitda) },
    { label: "P/FCF",            value: fmtX(inst.p_fcf) },
    { label: "Div Yield",        value: inst.div_yield != null ? `${Number(inst.div_yield).toFixed(2)}%` : "—" },
    { label: "Composite Score",  value: score != null ? `${Math.round(score)}/100` : "—" },
    { label: "Signal",           value: inst.score_label || "—" },
  ];

  return (
    <div className="py-8 lg:py-10 max-w-[1000px] mx-auto">
      {/* ── Breadcrumb ── */}
      <Link
        to="/screener"
        className="flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wider text-vs-ink-soft hover:text-vs-accent mb-6"
      >
        <ChevronLeft className="w-4 h-4" />
        Back to Screener
      </Link>

      {/* ── Header Block ── */}
      <div className="flex flex-col md:flex-row md:items-start md:justify-between border-b border-vs-rule pb-6 mb-8">
        <div>
          <h1 className="font-mono text-2xl md:text-[36px] font-medium text-vs-ink tracking-tight leading-tight">
            {name}
          </h1>
          <div className="flex items-center gap-3 mt-2 flex-wrap">
            <span className="text-[10px] font-bold uppercase tracking-widest bg-vs-accent text-white px-2.5 py-1">
              {ticker}
            </span>
            <span className="text-[13px] text-vs-ink-mid">
              {sector}
              {exchange ? ` · ${exchange}` : ""}
            </span>
            {inst.score_label && (
              <span className={cn("text-[10px] font-bold px-2.5 py-1", pill.cls)}>
                {pill.text}
              </span>
            )}
          </div>
        </div>

        <div className="mt-4 md:mt-0 md:text-right">
          {/* Ticker search */}
          <form onSubmit={handleSearch} className="flex items-center gap-2 md:justify-end mb-3">
            <div className="relative">
              <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-vs-ink-soft" />
              <input
                ref={searchRef}
                type="text"
                value={searchVal}
                onChange={(e) => setSearchVal(e.target.value)}
                placeholder="Search ticker…"
                className="pl-8 pr-3 py-1.5 text-[12px] border border-vs-rule bg-vs-bg-card outline-none focus:border-vs-accent w-36"
              />
            </div>
            <button
              type="submit"
              className="text-[11px] font-semibold uppercase tracking-wider text-vs-ink-mid hover:text-vs-accent px-2 py-1.5 border border-vs-rule hover:border-vs-accent transition-colors"
            >
              Go
            </button>
          </form>

          {/* Price block */}
          <p className="font-mono text-3xl md:text-[42px] font-medium text-vs-ink leading-tight">
            {fmtPrice(inst)}
          </p>
          {dayChangePct != null && (
            <p className={cn(
              "text-[14px] font-semibold flex items-center gap-1 md:justify-end mt-1",
              isUp ? "text-vs-pos" : "text-vs-neg"
            )}>
              {isUp
                ? <ArrowUpRight className="w-4 h-4" />
                : <ArrowDownRight className="w-4 h-4" />
              }
              {fmtPct(dayChangePct)} today
            </p>
          )}

          {/* Action buttons row */}
          <div className="mt-3 flex items-center gap-2 md:justify-end flex-wrap">
            {/* Watchlist button */}
            <button
              onClick={handleAddWatchlist}
              disabled={alreadyOnWatchlist || wlState === "adding"}
              className={cn(
                "flex items-center gap-2 text-[11px] font-semibold uppercase tracking-widest px-4 py-2 border transition-colors",
                alreadyOnWatchlist
                  ? "border-vs-accent bg-vs-accent text-white cursor-default"
                  : wlState === "added"
                  ? "border-vs-accent bg-vs-accent text-white"
                  : "border-vs-ink hover:bg-vs-ink hover:text-white"
              )}
            >
              {alreadyOnWatchlist || wlState === "added"
                ? <><BookmarkCheck className="w-4 h-4" /> On Watchlist</>
                : wlState === "adding"
                ? <><Loader2 className="w-4 h-4 animate-spin" /> Adding…</>
                : <><Bookmark className="w-4 h-4" /> Add to Watchlist</>
              }
            </button>

            {/* View Analyses button — only shown when a thesis exists */}
            {thesis && (
              <button
                onClick={() => navigate("/analyses")}
                className={cn(
                  "flex items-center gap-2 text-[11px] font-semibold uppercase tracking-widest px-4 py-2 border transition-colors",
                  thesisFromCache
                    ? "border-vs-rule text-vs-ink-soft cursor-pointer hover:border-vs-accent hover:text-vs-accent"
                    : "border-vs-rule text-vs-ink-soft hover:border-vs-accent hover:text-vs-accent"
                )}
                title="View all saved analyses"
              >
                <><FileText className="w-4 h-4" /> View Analyses</>
              </button>
            )}
          </div>
        </div>
      </div>

      {/* ── Score Row ── */}
      <div className="flex flex-col md:flex-row gap-6 mb-8">
        {/* Score Widget */}
        <div className="md:w-[30%] shrink-0 border-l-4 border-vs-accent bg-vs-bg-card shadow-[0_2px_8px_rgba(0,0,0,0.04)] p-6">
          <p className="text-[10px] font-bold uppercase tracking-[0.1em] text-vs-ink-soft mb-2">
            Composite Score
          </p>
          {score != null ? (
            <>
              <div className="flex items-baseline gap-1">
                <span className="font-mono text-[48px] font-medium text-vs-ink leading-none">
                  {Math.round(score)}
                </span>
                <span className="text-[22px] text-vs-ink-faint font-mono">/100</span>
              </div>
              <div className="mt-4 h-1.5 bg-vs-bg-subtle overflow-hidden">
                <div
                  className="h-full bg-vs-accent"
                  style={{ width: `${Math.min(score, 100)}%` }}
                />
              </div>
              <p className={cn("text-[11px] font-bold mt-3 px-2 py-1 inline-block", pill.cls)}>
                {pill.text}
              </p>
            </>
          ) : (
            <p className="text-[13px] text-vs-ink-soft mt-2">Score unavailable</p>
          )}
        </div>

        {/* Quick stats grid */}
        <div className="flex-1 grid grid-cols-2 sm:grid-cols-4 gap-[1px] bg-vs-rule">
          {[
            { label: "P/E",          value: fmtX(inst.pe ?? inst.pe_ratio) },
            { label: "P/B",          value: fmtX(inst.pb ?? inst.pb_ratio) },
            { label: "Div Yield",    value: inst.div_yield != null ? `${Number(inst.div_yield).toFixed(2)}%` : "—" },
            { label: "EV/EBITDA",    value: fmtX(inst.ev_ebitda) },
            { label: "1Y Return",    value: fmtPct(inst.yr1_pct) },
            { label: "ROE",          value: inst.roe != null ? `${(Number(inst.roe) * 100).toFixed(1)}%` : "—" },
            { label: "Rev Growth",   value: inst.revenue_growth  != null ? fmtPct(inst.revenue_growth  * 100) : "—" },
            { label: "Debt/Equity",  value: inst.debt_equity != null ? `${Number(inst.debt_equity).toFixed(2)}x` : "—" },
          ].map((m) => {
            // Colour 1Y Return and Rev Growth
            const isPctMetric = m.label === "1Y Return" || m.label === "Rev Growth";
            const numVal = isPctMetric
              ? parseFloat(m.value)
              : null;
            const colourCls = isPctMetric && !isNaN(numVal!)
              ? numVal! >= 0 ? "text-vs-pos" : "text-vs-neg"
              : "text-vs-ink";
            return (
              <div key={m.label} className="bg-vs-bg-card p-4">
                <p className="text-[10px] font-bold uppercase tracking-[0.1em] text-vs-ink-soft mb-1">
                  {m.label}
                </p>
                <p className={cn("font-mono text-lg font-medium", colourCls)}>{m.value}</p>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Price Chart ── */}
      <div className="bg-vs-bg-card border border-vs-rule p-5 mb-8">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] border-b-2 border-vs-ink pb-2">
            Price History
          </h2>
          <div className="flex gap-1">
            {TIME_FILTERS.map((f, i) => (
              <button
                key={f.label}
                onClick={() => setActiveTimeFilter(i)}
                className={cn(
                  "text-[11px] font-semibold uppercase tracking-wider px-3 py-1",
                  i === activeTimeFilter
                    ? "bg-vs-ink text-white"
                    : "text-vs-ink-soft hover:bg-vs-bg-raised"
                )}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>

        {chartLoading ? (
          <div className="h-[300px] flex items-center justify-center">
            <Loader2 className="w-6 h-6 animate-spin text-vs-accent" />
          </div>
        ) : priceData.length > 0 ? (
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={priceData}>
              <defs>
                <linearGradient id="colorPrice" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="#6B7F5E" stopOpacity={0.15} />
                  <stop offset="95%" stopColor="#6B7F5E" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid vertical={false} stroke="var(--color-vs-rule)" strokeDasharray="3 3" />
              <XAxis
                dataKey="date"
                axisLine={false}
                tickLine={false}
                tick={{ fill: "#808080", fontSize: 10 }}
                tickFormatter={(d: string) => {
                  const dt = new Date(d);
                  const period = TIME_FILTERS[activeTimeFilter].api;
                  if (period === "1mo" || period === "3mo") return dt.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
                  if (period === "6mo" || period === "ytd") return dt.toLocaleDateString("en-GB", { month: "short" });
                  return dt.toLocaleDateString("en-GB", { month: "short", year: "2-digit" });
                }}
                interval="preserveStartEnd"
                minTickGap={40}
              />
              <YAxis
                axisLine={false}
                tickLine={false}
                tick={{ fill: "#808080", fontSize: 10 }}
                tickFormatter={(v: number) => isGbx ? `${v.toFixed(0)}p` : `${sym}${v}`}
                domain={([dataMin, dataMax]: [number, number]) => {
                  const padding = (dataMax - dataMin) * 0.1;
                  return [Math.floor(dataMin - padding), Math.ceil(dataMax + padding)];
                }}
                width={65}
              />
              <Tooltip content={<ChartTooltip sym={sym} isGbx={isGbx} />} />
              <Area
                type="monotone"
                dataKey="price"
                stroke="#6B7F5E"
                strokeWidth={2}
                fill="url(#colorPrice)"
                dot={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-[300px] flex items-center justify-center">
            <p className="text-[12px] text-vs-ink-faint">No price data available for this period.</p>
          </div>
        )}

        {/* 52W range bar */}
        {inst.low_52w != null && inst.high_52w != null && inst.price != null && (
          <div className="mt-4 border-t border-vs-rule pt-4">
            <p className="text-[10px] font-bold uppercase tracking-[0.08em] text-vs-ink-soft mb-2">
              52-Week Range
            </p>
            <div className="flex items-center gap-3">
              <span className="text-[11px] text-vs-ink-mid w-16 text-right shrink-0">
                {isGbx ? `${Number(inst.low_52w).toFixed(0)}p` : `${sym}${Number(inst.low_52w).toFixed(2)}`}
              </span>
              <div className="flex-1 h-1.5 bg-vs-bg-subtle relative overflow-hidden">
                {(() => {
                  const pct = inst.pos_52w != null
                    ? inst.pos_52w * 100
                    : ((inst.price - inst.low_52w) / (inst.high_52w - inst.low_52w)) * 100;
                  return (
                    <div
                      className="absolute top-0 left-0 h-full bg-vs-accent"
                      style={{ width: `${Math.max(2, Math.min(pct, 100))}%` }}
                    />
                  );
                })()}
              </div>
              <span className="text-[11px] text-vs-ink-mid w-16 shrink-0">
                {isGbx ? `${Number(inst.high_52w).toFixed(0)}p` : `${sym}${Number(inst.high_52w).toFixed(2)}`}
              </span>
            </div>
          </div>
        )}
      </div>

      {/* ── Tab Bar ── */}
      <div className="border-b border-vs-rule mb-8 overflow-x-auto [&::-webkit-scrollbar]:hidden">
        <div className="flex">
          {TABS.map((tab, i) => (
            <button
              key={tab}
              onClick={() => setActiveTab(i)}
              className={cn(
                "text-[11px] font-semibold uppercase tracking-[0.08em] px-5 py-3 border-b-2 transition-colors whitespace-nowrap",
                i === activeTab
                  ? "text-vs-accent border-vs-accent"
                  : "text-vs-ink-mid border-transparent hover:text-vs-ink"
              )}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      {/* ── Tab Content ── */}

      {/* OVERVIEW */}
      {activeTab === 0 && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          {/* LEFT: AI Investment Thesis */}
          <div className="md:col-span-2">
            <div className="flex items-center justify-between border-b-2 border-vs-ink pb-2 mb-4">
              <h3 className="text-[13px] font-bold uppercase tracking-[0.08em]">
                Investment Thesis
              </h3>
              {thesisFromCache && thesisCachedAt && (
                <button
                  onClick={() => navigate("/analyses")}
                  className="flex items-center gap-1 text-[10px] text-vs-ink-faint hover:text-vs-accent transition-colors"
                  title="View saved analyses"
                >
                  <Clock className="w-3 h-3" />
                  {(() => {
                    const age = Math.floor((Date.now() - new Date(thesisCachedAt).getTime()) / 86400000);
                    const daysLeft = Math.max(0, 7 - age);
                    return age === 0
                      ? `Generated today · refreshes in 7 days`
                      : `Analysis from ${age}d ago · refreshes in ${daysLeft}d`;
                  })()}
                </button>
              )}
            </div>

            {/* Rate limit banner */}
            {rateLimited ? (
              <div className="flex items-start gap-3 bg-[#FFF8E1] border border-[#FFD54F] p-4 mb-4">
                <AlertCircle className="w-5 h-5 text-[#A67C00] shrink-0 mt-0.5" />
                <div>
                  <p className="text-[13px] font-bold text-[#A67C00] mb-1">
                    Daily thesis limit reached
                  </p>
                  <p className="text-[12px] text-[#7A5800] leading-relaxed">
                    You've used all 5 thesis generations for today. Limit resets at midnight UTC.
                    Instrument data and metrics are still available below.
                  </p>
                </div>
              </div>
            ) : ddData.calls_remaining < 5 ? (
              <div className="flex items-center gap-2 bg-vs-bg-raised border border-vs-rule px-3 py-2 mb-4">
                <span className="text-[11px] text-vs-ink-soft">
                  Thesis generations today:
                  <span className="font-bold text-vs-ink ml-1">
                    {5 - ddData.calls_remaining}/{5} used
                  </span>
                  <span className="text-vs-ink-faint ml-2">· resets midnight UTC</span>
                </span>
              </div>
            ) : null}
            {!rateLimited && thesis ? (
              <>
                {/* AI disclaimer — persistent, above content */}
                <div className="flex items-start gap-2.5 border border-vs-rule bg-vs-bg-raised px-4 py-3 mb-5">
                  <Info className="w-3.5 h-3.5 text-vs-ink-soft shrink-0 mt-[1px]" />
                  <p className="text-[11px] text-vs-ink-soft leading-relaxed">
                    <span className="font-bold text-vs-ink uppercase tracking-[0.06em]">AI-Generated Analysis.</span>
                    {" "}This thesis is produced by a large language model and is provided for informational purposes only.
                    It does not constitute financial advice, a recommendation to buy or sell, or an invitation to invest.
                    Always conduct your own due diligence before making any investment decision.
                  </p>
                </div>

                <div className="space-y-4">
                  {thesis.split(/\n\n+/).map((para, i) => (
                    <p key={i} className="text-[14px] text-vs-ink-mid leading-relaxed">
                      {para}
                    </p>
                  ))}
                </div>

                {/* Footer disclaimer */}
                <p className="mt-6 text-[10px] text-vs-ink-faint border-t border-vs-rule pt-3 leading-relaxed">
                  Analysis generated by Claude (Anthropic). Not financial advice. Past performance is not indicative of future results.
                  This content has not been verified by a regulated financial adviser. Treat all figures as indicative only.
                </p>
              </>
            ) : !rateLimited ? (
              <p className="text-[13px] text-vs-ink-soft">No thesis available.</p>
            ) : null}

            {/* 1Y Return callout */}
            {inst.yr1_pct != null && (
              <div className="mt-6 bg-vs-bg-raised border-l-2 border-vs-accent p-4 flex items-start gap-3">
                {inst.yr1_pct >= 0
                  ? <TrendingUp className="w-5 h-5 text-vs-pos shrink-0 mt-0.5" />
                  : <TrendingDown className="w-5 h-5 text-vs-neg shrink-0 mt-0.5" />
                }
                <div>
                  <p className="text-[13px] font-bold text-vs-ink mb-1">
                    1-Year Total Return: {fmtPct(inst.yr1_pct)}
                  </p>
                  <p className="text-[12px] text-vs-ink-mid leading-relaxed">
                    Based on price performance over the past 12 months. 3-month return:{" "}
                    {inst.return_3m != null ? fmtPct(inst.return_3m * 100) : "N/A"}.
                  </p>
                </div>
              </div>
            )}
          </div>

          {/* RIGHT: Key Metrics */}
          <div>
            <div className="bg-vs-bg-card border border-vs-rule">
              <div className="p-4 border-b border-vs-rule">
                <h3 className="text-[13px] font-bold uppercase tracking-[0.08em]">
                  Key Metrics
                </h3>
              </div>
              {keyMetrics.map((m) => (
                <div
                  key={m.label}
                  className="flex items-center justify-between px-4 py-3 border-b border-vs-rule last:border-0"
                >
                  <span className="text-[13px] text-vs-ink-mid">{m.label}</span>
                  <span className="text-[13px] font-semibold text-vs-ink">{m.value}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* FINANCIALS */}
      {activeTab === 1 && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          <div className="md:col-span-2">
            <h3 className="text-[13px] font-bold uppercase tracking-[0.08em] border-b-2 border-vs-ink pb-2 mb-4">
              Financial Summary
            </h3>
            <p className="text-[13px] text-vs-ink-soft leading-relaxed mb-6">
              Key financial metrics derived from the most recent filings. Data sourced from Yahoo Finance.
            </p>
            <div className="bg-vs-bg-card border border-vs-rule">
              {financialsMetrics.map((m) => (
                <div
                  key={m.label}
                  className="flex items-center justify-between px-4 py-3 border-b border-vs-rule last:border-0"
                >
                  <span className="text-[13px] text-vs-ink-mid">{m.label}</span>
                  <span className="text-[13px] font-semibold text-vs-ink">{m.value}</span>
                </div>
              ))}
            </div>
          </div>
          <div>
            <div className="bg-vs-bg-card border border-vs-rule">
              <div className="p-4 border-b border-vs-rule">
                <h3 className="text-[13px] font-bold uppercase tracking-[0.08em]">Signal</h3>
              </div>
              <div className="p-4">
                <p className={cn("text-[12px] font-bold px-3 py-2 inline-block", pill.cls)}>{pill.text}</p>
                <p className="text-[12px] text-vs-ink-soft mt-3 leading-relaxed">
                  Composite score of {score != null ? Math.round(score) : "—"}/100 based on value, quality, and momentum factors.
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* VALUATION */}
      {activeTab === 2 && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          <div className="md:col-span-2">
            <h3 className="text-[13px] font-bold uppercase tracking-[0.08em] border-b-2 border-vs-ink pb-2 mb-4">
              Valuation Multiples
            </h3>
            <p className="text-[13px] text-vs-ink-soft leading-relaxed mb-6">
              Multiples compared against sector medians within the scoring model.
            </p>
            <div className="bg-vs-bg-card border border-vs-rule">
              {valuationMetrics.map((m) => (
                <div
                  key={m.label}
                  className="flex items-center justify-between px-4 py-3 border-b border-vs-rule last:border-0"
                >
                  <span className="text-[13px] text-vs-ink-mid">{m.label}</span>
                  <span className="text-[13px] font-semibold text-vs-ink">{m.value}</span>
                </div>
              ))}
            </div>
          </div>
          <div>
            <div className="bg-vs-bg-card border border-vs-rule p-4">
              <p className="text-[10px] font-bold uppercase tracking-[0.1em] text-vs-ink-soft mb-3">52W Position</p>
              {inst.low_52w != null && inst.high_52w != null ? (
                <>
                  <div className="flex justify-between text-[11px] text-vs-ink-mid mb-1">
                    <span>Low: {isGbx ? `${Number(inst.low_52w).toFixed(0)}p` : `${sym}${Number(inst.low_52w).toFixed(2)}`}</span>
                    <span>High: {isGbx ? `${Number(inst.high_52w).toFixed(0)}p` : `${sym}${Number(inst.high_52w).toFixed(2)}`}</span>
                  </div>
                  <div className="h-1.5 bg-vs-bg-subtle overflow-hidden">
                    <div
                      className="h-full bg-vs-accent"
                      style={{
                        width: `${Math.max(2, Math.min(
                          inst.pos_52w != null ? inst.pos_52w * 100
                          : ((inst.price - inst.low_52w) / (inst.high_52w - inst.low_52w)) * 100,
                          100
                        ))}%`
                      }}
                    />
                  </div>
                  {inst.pct_from_high != null && (
                    <p className="text-[11px] text-vs-ink-soft mt-2">
                      {Math.abs(inst.pct_from_high).toFixed(1)}% from 52W high
                    </p>
                  )}
                </>
              ) : (
                <p className="text-[12px] text-vs-ink-faint">N/A</p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* DIVIDENDS */}
      {activeTab === 3 && (
        <div>
          {divLoading && (
            <div className="py-16 flex flex-col items-center gap-3">
              <Loader2 className="w-6 h-6 animate-spin text-vs-accent" />
              <p className="text-[12px] text-vs-ink-soft">Loading dividend data…</p>
            </div>
          )}
          {divError && !divLoading && (
            <div className="flex items-start gap-3 bg-[#FDECEA] border border-[#F5C6C6] p-4">
              <AlertCircle className="w-5 h-5 text-[#B71C1C] shrink-0 mt-0.5" />
              <div>
                <p className="text-[13px] font-bold text-[#B71C1C] mb-1">Could not load dividend data</p>
                <p className="text-[12px] text-[#7F1010]">{divError}</p>
              </div>
            </div>
          )}
          {divData && !divLoading && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
              {/* LEFT: AI summary + history chart */}
              <div className="md:col-span-2 space-y-8">
                {/* AI income analysis */}
                <div>
                  <div className="flex items-center justify-between border-b-2 border-vs-ink pb-2 mb-4">
                    <h3 className="text-[13px] font-bold uppercase tracking-[0.08em]">
                      Income Analysis
                    </h3>
                    <div className="flex items-center gap-3">
                      {divData.generated_at && (
                        <span className="flex items-center gap-1 text-[10px] text-vs-ink-faint">
                          <Clock className="w-3 h-3" />
                          {(() => {
                            const age = Math.floor((Date.now() - new Date(divData.generated_at).getTime()) / 86400000);
                            return age === 0 ? "Generated today" : `From ${age}d ago`;
                          })()}
                        </span>
                      )}
                      <button
                        onClick={() => fetchDividends(true)}
                        disabled={divLoading}
                        className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-vs-ink-soft hover:text-vs-accent transition-colors disabled:opacity-40"
                        title="Refresh dividend data"
                      >
                        <RefreshCw className={cn("w-3 h-3", divLoading && "animate-spin")} />
                        Refresh
                      </button>
                    </div>
                  </div>
                  <div className="space-y-3">
                    {(divData.summary || "").split(/\n\n+/).map((para, i) => (
                      <p key={i} className="text-[14px] text-vs-ink-mid leading-relaxed">{para}</p>
                    ))}
                  </div>
                </div>

                {/* Dividend history bar chart */}
                {divData.history && divData.history.length > 0 && (
                  <div>
                    <h3 className="text-[13px] font-bold uppercase tracking-[0.08em] border-b-2 border-vs-ink pb-2 mb-4">
                      Dividend History
                    </h3>
                    <ResponsiveContainer width="100%" height={220}>
                      <BarChart data={divData.history} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                        <CartesianGrid vertical={false} stroke="var(--color-vs-rule)" strokeDasharray="3 3" />
                        <XAxis
                          dataKey="date"
                          axisLine={false}
                          tickLine={false}
                          tick={{ fill: "#808080", fontSize: 10 }}
                          tickFormatter={(d: string) => {
                            const dt = new Date(d);
                            return dt.toLocaleDateString("en-GB", { month: "short", year: "2-digit" });
                          }}
                          interval="preserveStartEnd"
                          minTickGap={40}
                        />
                        <YAxis
                          axisLine={false}
                          tickLine={false}
                          tick={{ fill: "#808080", fontSize: 10 }}
                          tickFormatter={(v: number) => `${divData.symbol}${v.toFixed(2)}`}
                          width={55}
                        />
                        <Tooltip
                          formatter={(v: number) => [`${divData.symbol}${Number(v).toFixed(4)}`, "Dividend"]}
                          labelFormatter={(l: string) => new Date(l).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" })}
                          contentStyle={{ fontSize: 11, border: "1px solid var(--color-vs-rule)", borderRadius: 0 }}
                        />
                        <Bar dataKey="amount" fill="#6B7F5E" radius={[2, 2, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </div>

              {/* RIGHT: Dividend stats */}
              <div className="space-y-4">
                <div className="bg-vs-bg-card border border-vs-rule">
                  <div className="p-4 border-b border-vs-rule">
                    <h3 className="text-[13px] font-bold uppercase tracking-[0.08em]">Dividend Stats</h3>
                  </div>
                  {[
                    { label: "Current Yield",     value: divData.div_yield != null ? `${Number(divData.div_yield).toFixed(2)}%` : "—" },
                    { label: "5Y Avg Yield",       value: divData.five_year_avg_yield != null ? `${Number(divData.five_year_avg_yield).toFixed(2)}%` : "—" },
                    { label: "Frequency",          value: divData.payment_frequency || "—" },
                    { label: "Last Dividend",      value: divData.last_dividend != null ? `${divData.symbol}${Number(divData.last_dividend).toFixed(4)}` : "—" },
                    { label: "Last Ex-Date",       value: divData.last_ex_date || "—" },
                    { label: "Payout Ratio",       value: divData.payout_ratio != null ? `${Number(divData.payout_ratio).toFixed(1)}%` : "—" },
                    { label: "3Y Div CAGR",        value: divData.dividend_growth_3y != null ? `${divData.dividend_growth_3y > 0 ? "+" : ""}${Number(divData.dividend_growth_3y).toFixed(1)}%` : "—" },
                    { label: "ROE",                value: divData.roe != null ? `${Number(divData.roe).toFixed(1)}%` : "—" },
                  ].map((m) => (
                    <div
                      key={m.label}
                      className="flex items-center justify-between px-4 py-3 border-b border-vs-rule last:border-0"
                    >
                      <span className="text-[13px] text-vs-ink-mid">{m.label}</span>
                      <span className="text-[13px] font-semibold text-vs-ink">{m.value}</span>
                    </div>
                  ))}
                </div>

                {/* Payout sustainability indicator */}
                {divData.payout_ratio != null && (
                  <div className="bg-vs-bg-card border border-vs-rule p-4">
                    <p className="text-[10px] font-bold uppercase tracking-[0.1em] text-vs-ink-soft mb-2">
                      Payout Sustainability
                    </p>
                    <div className="h-1.5 bg-vs-bg-subtle overflow-hidden mb-2">
                      <div
                        className={cn("h-full transition-all",
                          divData.payout_ratio < 60 ? "bg-vs-pos" :
                          divData.payout_ratio < 85 ? "bg-yellow-400" : "bg-vs-neg"
                        )}
                        style={{ width: `${Math.min(divData.payout_ratio, 100)}%` }}
                      />
                    </div>
                    <p className="text-[11px] text-vs-ink-soft">
                      {divData.payout_ratio < 60
                        ? "Well covered by earnings"
                        : divData.payout_ratio < 85
                        ? "Moderately stretched"
                        : "Highly stretched — monitor closely"}
                    </p>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* NEWS & SIGNALS */}
      {activeTab === 4 && (
        <div>
          <h3 className="text-[13px] font-bold uppercase tracking-[0.08em] border-b-2 border-vs-ink pb-2 mb-5">
            Latest News
          </h3>
          {newsLoading && (
            <div className="py-10 flex items-center justify-center gap-2">
              <Loader2 className="w-5 h-5 animate-spin text-vs-accent" />
              <p className="text-[12px] text-vs-ink-soft">Fetching news…</p>
            </div>
          )}
          {!newsLoading && newsItems.length === 0 && (
            <div className="py-10 text-center border border-dashed border-vs-rule">
              <p className="text-[13px] text-vs-ink-soft">No recent news found for {tickerParam}.</p>
            </div>
          )}
          {!newsLoading && newsItems.length > 0 && (
            <div className="bg-vs-bg-card border border-vs-rule divide-y divide-vs-rule">
              {newsItems.slice(0, 10).map((item: any, i: number) => (
                <a
                  key={i}
                  href={item.link || "#"}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-start justify-between gap-4 px-5 py-4 hover:bg-vs-bg-raised transition-colors group"
                >
                  <div className="flex-1 min-w-0">
                    <p className="text-[13px] text-vs-ink font-medium group-hover:text-vs-accent transition-colors leading-snug">
                      {item.title}
                    </p>
                    <p className="text-[11px] text-vs-ink-faint mt-1">
                      {item.publisher}{item.pub_time ? ` · ${new Date(item.pub_time * 1000).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}` : ""}
                    </p>
                  </div>
                  {item.link && <ExternalLink className="w-3.5 h-3.5 text-vs-ink-faint shrink-0 mt-0.5 opacity-0 group-hover:opacity-100 transition-opacity" />}
                </a>
              ))}
            </div>
          )}
          {/* Signals from verdict */}
          {ddData?.instrument?.verdict && (
            <div className="mt-8">
              <h3 className="text-[13px] font-bold uppercase tracking-[0.08em] border-b-2 border-vs-ink pb-2 mb-5">
                Signals
              </h3>
              <div className="bg-vs-bg-card border border-vs-rule p-5">
                <p className="text-[13px] text-vs-ink-mid leading-relaxed">{ddData.instrument.verdict}</p>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
