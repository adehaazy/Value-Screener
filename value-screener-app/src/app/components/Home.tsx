import { useState, useEffect } from "react";
import { Link } from "react-router";
import { motion, AnimatePresence } from "motion/react";
import {
  Maximize2,
  Minimize2,
  TrendingUp,
  Activity,
  FileText,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { cn } from "../utils";
import { useAppData } from "../useAppData";
import { useAuth } from "../AuthContext";

/* ================================================================
   StockLogo — Section 8B
   ================================================================ */
function StockLogo({
  ticker,
  domain,
  pos,
}: {
  ticker: string;
  domain?: string;
  pos?: boolean;
}) {
  const [imgError, setImgError] = useState(false);
  const letter = ticker?.charAt(0) ?? "?";

  if (domain && !imgError) {
    return (
      <img
        src={`https://logo.clearbit.com/${domain}`}
        alt={ticker}
        className="w-8 h-8 rounded-sm object-contain bg-white shrink-0 border border-vs-rule/50"
        onError={() => setImgError(true)}
      />
    );
  }

  const bg =
    pos === undefined
      ? "bg-vs-ink"
      : pos
        ? "bg-vs-accent"
        : "bg-vs-ink-mid";

  return (
    <div
      className={cn(
        "w-8 h-8 flex items-center justify-center font-mono text-[11px] font-bold text-white shrink-0 rounded-sm",
        bg
      )}
    >
      {letter}
    </div>
  );
}

/* ================================================================
   PaginatedList — Section 8D
   ================================================================ */
function PaginatedList<T>({
  items,
  renderItem,
  pageSize = 5,
}: {
  items: T[];
  renderItem: (item: T, index: number) => React.ReactNode;
  pageSize?: number;
}) {
  const [page, setPage] = useState(0);
  const totalPages = Math.ceil(items.length / pageSize);
  const pageItems = items.slice(page * pageSize, (page + 1) * pageSize);

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto pr-2 -mr-2 [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:bg-vs-rule [&::-webkit-scrollbar-thumb]:rounded-full">
        <AnimatePresence mode="popLayout">
          {pageItems.map((item, i) => (
            <motion.div
              key={page * pageSize + i}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95 }}
              transition={{ duration: 0.2, delay: i * 0.05 }}
            >
              {renderItem(item, page * pageSize + i)}
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between border-t border-vs-rule pt-3 mt-4 shrink-0">
          <button
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
            className="text-[11px] font-semibold uppercase tracking-wider text-vs-ink-soft hover:text-vs-accent disabled:opacity-30 disabled:pointer-events-none"
          >
            <ChevronLeft className="w-4 h-4 inline -mt-0.5" /> Prev
          </button>
          <span className="text-[10px] text-vs-ink-mid font-semibold tracking-widest">
            {page + 1} / {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            disabled={page >= totalPages - 1}
            className="text-[11px] font-semibold uppercase tracking-wider text-vs-ink-soft hover:text-vs-accent disabled:opacity-30 disabled:pointer-events-none"
          >
            Next <ChevronRight className="w-4 h-4 inline -mt-0.5" />
          </button>
        </div>
      )}
    </div>
  );
}

/* ================================================================
   Quadrant — Section 8C
   ================================================================ */
function Quadrant({
  id,
  title,
  action,
  expandedId,
  setExpandedId,
  children,
}: {
  id: string;
  title: string;
  action: React.ReactNode;
  expandedId: string | null;
  setExpandedId: (id: string | null) => void;
  children: React.ReactNode;
}) {
  const isExpanded = expandedId === id;
  const isHidden = expandedId !== null && expandedId !== id;

  return (
    <AnimatePresence>
      {!isHidden && (
        <motion.div
          layout
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.95 }}
          transition={{ duration: 0.4, type: "spring", bounce: 0.2 }}
          className={cn(
            "flex flex-col bg-vs-bg-card border border-vs-rule p-5 relative overflow-hidden",
            isExpanded ? "md:col-span-2 h-[800px]" : "h-[450px]"
          )}
        >
          {/* Header */}
          <motion.div
            layout="position"
            className="flex justify-between items-end border-b-2 border-vs-ink pb-2 mb-4 shrink-0"
          >
            <h2 className="text-[13px] font-bold uppercase tracking-[0.08em]">
              {title}
            </h2>
            <div className="flex items-center gap-2">
              {action}
              <button
                onClick={() => setExpandedId(isExpanded ? null : id)}
                className="bg-vs-bg-raised p-1.5 rounded-sm"
              >
                {isExpanded ? (
                  <Minimize2 className="w-3.5 h-3.5" />
                ) : (
                  <Maximize2 className="w-3.5 h-3.5" />
                )}
              </button>
            </div>
          </motion.div>

          {/* Content */}
          <motion.div
            layout="position"
            className="flex-1 overflow-y-auto pr-2 -mr-2 [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:bg-vs-rule [&::-webkit-scrollbar-thumb]:rounded-full"
          >
            {children}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/* ================================================================
   InstrumentRow — shared row for screener, portfolio, watchlist
   ================================================================ */
function InstrumentRow({
  item,
  label,
  showPos = false,
}: {
  item: any;
  label?: string;
  showPos?: boolean;
}) {
  const ticker = item.t || item.ticker || "";
  const name = item.name || item.company || ticker;
  const score = item.score ?? item.value_score;
  const price = item.price ?? item.current_price;
  const chg = item.chg_pct ?? item.change_pct ?? 0;
  const positive = chg >= 0;

  return (
    <Link
      to={`/deepdive?ticker=${ticker}`}
      className="flex items-center justify-between py-3 border-b border-vs-rule last:border-0 hover:bg-vs-bg-raised px-2 -mx-2 rounded-sm cursor-pointer group"
    >
      <div className="flex items-center gap-3 min-w-0">
        <StockLogo
          ticker={ticker}
          pos={showPos ? positive : undefined}
        />
        <div className="min-w-0">
          <span className="text-[13px] font-bold text-vs-ink block truncate">
            {ticker}
          </span>
          <span className="text-[10px] font-bold uppercase tracking-[0.1em] text-vs-ink-soft block truncate">
            {label || name}
          </span>
        </div>
      </div>

      <div className="flex items-center gap-3 shrink-0">
        {score != null && (
          <span className="text-[10px] bg-vs-bg-subtle px-1.5 py-0.5 font-semibold text-vs-ink-mid">
            {Math.round(score)}
          </span>
        )}
        <div className="text-right">
          <span className="text-[13px] font-semibold text-vs-ink block">
            {price != null ? `£${Number(price).toFixed(2)}` : "—"}
          </span>
          <span
            className={cn(
              "text-[11px] font-bold flex items-center gap-0.5 justify-end",
              positive ? "text-vs-pos" : "text-vs-neg"
            )}
          >
            {positive ? (
              <TrendingUp className="w-3 h-3" />
            ) : (
              <Activity className="w-3 h-3" />
            )}
            {positive ? "+" : ""}
            {chg.toFixed(2)}%
          </span>
        </div>
      </div>
    </Link>
  );
}

/* ================================================================
   MarketTicker — Section 8G
   ================================================================ */

const _TICKER_API = "https://value-screener.onrender.com";

// Fallback static data shown while live data loads
const _TICKER_FALLBACK = [
  { label: "S&P 500",    value: "—",    change: null, pos: true  },
  { label: "Nasdaq",     value: "—",    change: null, pos: true  },
  { label: "Dow Jones",  value: "—",    change: null, pos: true  },
  { label: "FTSE 100",   value: "—",    change: null, pos: true  },
  { label: "DAX",        value: "—",    change: null, pos: true  },
  { label: "Nikkei",     value: "—",    change: null, pos: true  },
  { label: "Gold",       value: "—",    change: null, pos: true  },
  { label: "Crude Oil",  value: "—",    change: null, pos: true  },
  { label: "US 10Y",     value: "—",    change: null, pos: false },
  { label: "EUR/USD",    value: "—",    change: null, pos: true  },
];

function fmtIndexPrice(price: number | null, label: string): string {
  if (price == null) return "—";
  if (label === "EUR/USD") return price.toFixed(4);
  if (label === "US 10Y") return `${price.toFixed(2)}%`;
  if (price > 1000) return price.toLocaleString("en-US", { maximumFractionDigits: 0 });
  return price.toFixed(2);
}

function MarketTicker() {
  const [items, setItems] = useState(_TICKER_FALLBACK);
  const [live, setLive] = useState(false);

  useEffect(() => {
    fetch(`${_TICKER_API}/api/market/indices`)
      .then((r) => r.json())
      .then((d) => {
        if (d.ok && d.indices?.length) {
          setItems(
            d.indices.map((idx: any) => ({
              label:  idx.label,
              value:  fmtIndexPrice(idx.price, idx.label),
              change: idx.change_pct != null
                ? `${idx.change_pct >= 0 ? "+" : ""}${idx.change_pct.toFixed(2)}%`
                : null,
              pos:    (idx.change_pct ?? 0) >= 0,
            }))
          );
          setLive(true);
        }
      })
      .catch(() => {/* keep fallback */});
  }, []);

  const allItems = [...items, ...items];

  return (
    <div className="mt-4 mb-10 border-t border-vs-ink pt-6 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <span className="text-[10px] font-bold uppercase tracking-[0.1em] text-vs-ink-soft">
          Global Markets &bull; Daily Snapshot
        </span>
        <div className="flex items-center gap-1.5">
          <span className={cn("w-2 h-2 rounded-full", live ? "bg-vs-pos animate-pulse" : "bg-vs-ink-faint")} />
          <span className="text-[10px] font-semibold uppercase tracking-wider text-vs-ink-soft">
            {live ? "Live" : "Loading…"}
          </span>
        </div>
      </div>

      {/* Scrolling container */}
      <div className="relative w-full bg-vs-bg-card border-y border-vs-rule flex items-center overflow-hidden h-[70px]">
        {/* Fade masks */}
        <div className="absolute left-0 top-0 bottom-0 w-8 bg-gradient-to-r from-vs-bg-card to-transparent z-10" />
        <div className="absolute right-0 top-0 bottom-0 w-8 bg-gradient-to-l from-vs-bg-card to-transparent z-10" />

        <motion.div
          className="flex"
          animate={{ x: ["0%", "-50%"] }}
          transition={{ repeat: Infinity, ease: "linear", duration: 30 }}
        >
          {allItems.map((item, i) => (
            <div
              key={i}
              className="inline-flex flex-col justify-center px-8 border-r border-vs-rule/50 h-full shrink-0"
            >
              <span className="text-[10px] font-semibold uppercase tracking-[0.1em] text-vs-ink-soft">
                {item.label}
              </span>
              {item.change != null ? (
                <span
                  className={cn(
                    "text-[11px] font-bold flex items-center gap-0.5",
                    item.pos ? "text-vs-pos" : "text-vs-neg"
                  )}
                >
                  {item.pos ? (
                    <TrendingUp className="w-3 h-3" />
                  ) : (
                    <Activity className="w-3 h-3" />
                  )}
                  {item.change}
                </span>
              ) : (
                <span className="text-[11px] text-vs-ink-faint">—</span>
              )}
              <span className="font-mono text-[16px] font-medium text-vs-ink leading-tight mt-1">
                {item.value}
              </span>
            </div>
          ))}
        </motion.div>
      </div>
    </div>
  );
}

/* ================================================================
   BriefingQuadrant — Section 8F.3
   ================================================================ */
const API_BASE = "https://value-screener.onrender.com";

function BriefingQuadrantContent({ watchlistTickers = "" }: { watchlistTickers?: string }) {
  const [briefing, setBriefing] = useState<any>(null);
  const [newsItems, setNewsItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Fetch briefing for macro tone + headline
    fetch(`${API_BASE}/api/briefing`)
      .then((r) => r.json())
      .then((d) => {
        if (d.ok && d.briefing) setBriefing(d.briefing);
      })
      .catch(() => {})
      .finally(() => setLoading(false));

    // Fetch news headlines with watchlist tickers
    const newsUrl = watchlistTickers
      ? `${API_BASE}/api/briefing/news?tickers=${encodeURIComponent(watchlistTickers)}`
      : `${API_BASE}/api/briefing/news`;
    fetch(newsUrl)
      .then((r) => r.json())
      .then((d) => {
        if (d.ok) {
          // Combine watchlist news + market news, take top 4
          const wl = (d.watchlist_news || []).slice(0, 2).map((n: any) => ({
            category: n.ticker || "Watchlist",
            headline: n.title,
            publisher: n.publisher,
            link: n.link,
            isWatchlist: true,
          }));
          const mkt = (d.market_news || []).slice(0, 3).map((n: any) => ({
            category: n.publisher || "Markets",
            headline: n.title,
            publisher: n.publisher,
            link: n.link,
            isWatchlist: false,
            sentiment: n.sentiment,
          }));
          setNewsItems([...wl, ...mkt].slice(0, 4));
        }
      })
      .catch(() => {});
  }, [watchlistTickers]);

  const macroTone = briefing?.macro?.tone;
  const toneColour = macroTone === "constructive"
    ? "text-[#1E5C38]"
    : macroTone === "cautious"
    ? "text-vs-neg"
    : "text-[#A67C00]";

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 mb-3">
        <FileText className="w-5 h-5 text-vs-accent" />
        <span className="text-[14px] font-bold text-vs-ink">Today's Digest</span>
      </div>

      {/* Macro tone summary */}
      {briefing?.macro && (
        <div className="mb-4 pb-3 border-b border-vs-rule">
          <p className="text-[10px] font-bold uppercase tracking-[0.1em] text-vs-ink-soft mb-1">
            Macro Tone
          </p>
          <p className={cn("text-[13px] font-bold capitalize", toneColour)}>
            {macroTone}
          </p>
          <p className="text-[11px] text-vs-ink-soft leading-relaxed mt-0.5">
            {briefing.macro.tone_detail}
          </p>
        </div>
      )}

      <p className="text-[10px] font-bold uppercase tracking-[0.1em] text-vs-ink-soft mb-3">
        Key Headlines
      </p>

      {loading ? (
        <div className="space-y-3 flex-1">
          {[1, 2, 3].map((i) => (
            <div key={i} className="pl-3 py-2 border-l-2 border-vs-rule">
              <div className="w-20 h-2 bg-vs-bg-subtle animate-pulse mb-1.5" />
              <div className="w-full h-3 bg-vs-bg-subtle animate-pulse" />
            </div>
          ))}
        </div>
      ) : (
        <div className="space-y-3 flex-1 overflow-hidden">
          {newsItems.length > 0 ? newsItems.map((item: any, i: number) => (
            <a
              key={i}
              href={item.link || "#"}
              target="_blank"
              rel="noopener noreferrer"
              className={cn(
                "block pl-3 py-2 hover:opacity-80 transition-opacity",
                i === 0 ? "border-l-2 border-vs-accent" : "border-l-2 border-vs-rule"
              )}
            >
              <div className="flex items-center gap-2 mb-0.5">
                <span className="text-[10px] font-bold uppercase tracking-[0.08em] text-vs-ink-soft">
                  {item.category}
                </span>
                {item.isWatchlist && (
                  <span className="text-[9px] font-bold uppercase tracking-wider text-vs-accent bg-vs-bg-raised px-1.5 py-0.5">
                    Watchlist
                  </span>
                )}
              </div>
              <p className="text-[12px] font-semibold text-vs-ink leading-snug line-clamp-2">
                {item.headline}
              </p>
            </a>
          )) : (
            <p className="text-[12px] text-vs-ink-faint">
              No headlines yet. Check the Briefing page.
            </p>
          )}
        </div>
      )}

      <Link
        to="/briefing"
        className="mt-4 shrink-0 w-full text-center py-2.5 text-[11px] font-semibold uppercase tracking-widest border border-vs-ink hover:bg-vs-ink hover:text-white transition-colors"
      >
        Go to Briefing
      </Link>
    </div>
  );
}

/* ================================================================
   Loading Skeleton
   ================================================================ */
function LoadingSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center justify-between py-3 border-b border-vs-rule last:border-0">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-vs-bg-subtle animate-pulse rounded-sm" />
            <div>
              <div className="w-16 h-3 bg-vs-bg-subtle animate-pulse mb-1" />
              <div className="w-24 h-2.5 bg-vs-bg-subtle animate-pulse" />
            </div>
          </div>
          <div className="text-right">
            <div className="w-14 h-3 bg-vs-bg-subtle animate-pulse mb-1 ml-auto" />
            <div className="w-10 h-2.5 bg-vs-bg-subtle animate-pulse ml-auto" />
          </div>
        </div>
      ))}
    </div>
  );
}

function ErrorMessage({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center py-8">
      <Activity className="w-6 h-6 text-vs-ink-soft mb-2" />
      <p className="text-[12px] text-vs-ink-soft">{message}</p>
    </div>
  );
}

/* ================================================================
   Fallback mock data — shown when APIs are down
   ================================================================ */
const MOCK_SCREENER = [
  { t: "SHEL.L", name: "Shell plc", score: 87, price: 27.12, chg_pct: 1.24, sector: "Energy" },
  { t: "BP.L", name: "BP plc", score: 84, price: 4.85, chg_pct: -0.62, sector: "Energy" },
  { t: "HSBA.L", name: "HSBC Holdings", score: 82, price: 6.48, chg_pct: 0.93, sector: "Financials" },
  { t: "ULVR.L", name: "Unilever plc", score: 79, price: 43.21, chg_pct: 0.31, sector: "Consumer Staples" },
  { t: "AZN.L", name: "AstraZeneca", score: 77, price: 112.50, chg_pct: -1.15, sector: "Healthcare" },
  { t: "GSK.L", name: "GSK plc", score: 76, price: 15.34, chg_pct: 0.45, sector: "Healthcare" },
  { t: "RIO.L", name: "Rio Tinto", score: 75, price: 52.80, chg_pct: 2.10, sector: "Materials" },
  { t: "BARC.L", name: "Barclays plc", score: 74, price: 1.98, chg_pct: -0.38, sector: "Financials" },
  { t: "LLOY.L", name: "Lloyds Banking", score: 73, price: 0.54, chg_pct: 0.72, sector: "Financials" },
  { t: "DGE.L", name: "Diageo plc", score: 71, price: 28.45, chg_pct: -0.89, sector: "Consumer Staples" },
];

const MOCK_PORTFOLIO = [
  { ticker: "AAPL", name: "Apple Inc.", score: 78, price: 178.72, chg_pct: 1.85 },
  { ticker: "MSFT", name: "Microsoft Corp.", score: 81, price: 378.91, chg_pct: 0.42 },
  { ticker: "SHEL.L", name: "Shell plc", score: 87, price: 27.12, chg_pct: 1.24 },
  { ticker: "BP.L", name: "BP plc", score: 84, price: 4.85, chg_pct: -0.62 },
  { ticker: "HSBA.L", name: "HSBC Holdings", score: 82, price: 6.48, chg_pct: 0.93 },
];

const MOCK_WATCHLIST = [
  { t: "TSLA", name: "Tesla Inc.", score: 65, price: 248.50, chg_pct: -2.31 },
  { t: "NVDA", name: "NVIDIA Corp.", score: 72, price: 875.40, chg_pct: 3.12 },
  { t: "VOD.L", name: "Vodafone Group", score: 68, price: 0.72, chg_pct: -1.05 },
  { t: "BA.L", name: "BAE Systems", score: 76, price: 13.25, chg_pct: 0.88 },
  { t: "RR.L", name: "Rolls-Royce", score: 74, price: 4.10, chg_pct: 1.55 },
];

/* ================================================================
   Home — Section 8
   ================================================================ */
function getTimeGreeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Morning";
  if (h < 18) return "Afternoon";
  return "Evening";
}

export default function Home() {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const { user } = useAuth();

  const {
    instruments: liveInstruments,
    holdings: liveHoldings,
    watchlist: liveWatchlist,
    screenerLoading,
    portfolioLoading,
    watchlistLoading,
  } = useAppData();

  const instruments = liveInstruments.length ? liveInstruments : (!screenerLoading ? MOCK_SCREENER : []);
  const holdings    = liveHoldings.length    ? liveHoldings    : (!portfolioLoading ? MOCK_PORTFOLIO : []);
  const watchlist   = liveWatchlist.length   ? liveWatchlist   : (!watchlistLoading ? MOCK_WATCHLIST : []);

  const greeting = getTimeGreeting();
  const firstName = user?.first_name || "Investor";

  return (
    <div className="py-8 lg:py-10">
      {/* ── Hero Band ── */}
      <div className="bg-vs-accent -mx-4 md:-mx-10 px-4 md:px-10 py-10 md:py-12">
        <h1 className="font-mono text-2xl md:text-[36px] font-medium text-white tracking-tight leading-tight">
          {greeting}, {firstName}.
        </h1>
        <p className="text-[13px] text-white/70 mt-2 font-mono">
          Signed in as {user?.username || "—"}.
        </p>
      </div>

      {/* ── 2x2 Grid ── */}
      <div
        className={cn(
          "py-8 grid gap-6",
          expandedId ? "grid-cols-1" : "grid-cols-1 md:grid-cols-2"
        )}
      >
        {/* Q1: Top Screener Matches */}
        <Quadrant
          id="screener"
          title="Top Screener Matches"
          action={
            <Link
              to="/screener"
              className="text-[11px] font-semibold uppercase tracking-wider text-vs-accent hover:text-vs-accent-dark"
            >
              View all
            </Link>
          }
          expandedId={expandedId}
          setExpandedId={setExpandedId}
        >
          {screenerLoading ? (
            <LoadingSkeleton />
          ) : (
            <PaginatedList
              items={instruments.slice(0, 50)}
              pageSize={expandedId === "screener" ? 10 : 5}
              renderItem={(item: any) => (
                <InstrumentRow item={item} showPos />
              )}
            />
          )}
        </Quadrant>

        {/* Q2: My Portfolio */}
        <Quadrant
          id="portfolio"
          title="My Portfolio"
          action={
            <Link
              to="/portfolio"
              className="text-[11px] font-semibold uppercase tracking-wider text-vs-accent hover:text-vs-accent-dark"
            >
              View Detail
            </Link>
          }
          expandedId={expandedId}
          setExpandedId={setExpandedId}
        >
          {portfolioLoading ? (
            <LoadingSkeleton />
          ) : (
            <PaginatedList
              items={holdings}
              pageSize={expandedId === "portfolio" ? 10 : 5}
              renderItem={(item: any) => (
                <InstrumentRow item={item} label="Holding" />
              )}
            />
          )}
        </Quadrant>

        {/* Q3: Market Briefing */}
        <Quadrant
          id="briefing"
          title="Market Briefing"
          action={
            <Link
              to="/briefing"
              className="text-[11px] font-semibold uppercase tracking-wider text-vs-accent hover:text-vs-accent-dark"
            >
              Read All
            </Link>
          }
          expandedId={expandedId}
          setExpandedId={setExpandedId}
        >
          <BriefingQuadrantContent watchlistTickers={watchlist.map((w: any) => w.ticker || w.t).join(",")} />
        </Quadrant>

        {/* Q4: Watchlist */}
        <Quadrant
          id="watchlist"
          title="Watchlist"
          action={
            <Link
              to="/watchlist"
              className="text-[11px] font-semibold uppercase tracking-wider text-vs-accent hover:text-vs-accent-dark"
            >
              View all
            </Link>
          }
          expandedId={expandedId}
          setExpandedId={setExpandedId}
        >
          {watchlistLoading ? (
            <LoadingSkeleton />
          ) : (
            <PaginatedList
              items={watchlist}
              pageSize={expandedId === "watchlist" ? 10 : 5}
              renderItem={(item: any) => (
                <InstrumentRow item={item} label="Equity" showPos />
              )}
            />
          )}
        </Quadrant>
      </div>

      {/* ── Market Ticker ── */}
      <MarketTicker />

      {/* ── Footer disclaimer ── */}
      <div className="text-center mt-4 mb-8 space-y-1">
        <p className="text-[11px] font-mono text-vs-ink-faint tracking-wide">
          Not financial advice. Not even close.
        </p>
        <p className="text-[10px] font-mono text-vs-ink-faint tracking-wide">
          Market data via Yahoo Finance. Scores via guesswork.
        </p>
      </div>
    </div>
  );
}
