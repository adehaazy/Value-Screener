import React, { useState, useMemo, useRef, useEffect, useCallback } from "react";
import { useNavigate } from "react-router";
import {
  Search,
  ArrowUpDown,
  ChevronDown,
  ExternalLink,
  Bookmark,
  BookmarkX,
  TrendingUp,
  TrendingDown,
  X,
} from "lucide-react";
import { cn } from "../utils";
import { useAppData } from "../useAppData";
import { deleteFromWatchlist } from "../../api/client";

/* ── helpers (mirrors Screener.tsx) ─────────────────────────────── */

function currencySymbol(inst: any): string {
  const c = (inst.currency || "").toUpperCase();
  if (c === "GBP" || c === "GBX") return "£";
  if (c === "USD") return "$";
  if (c === "EUR") return "€";
  if (c === "JPY") return "¥";
  if (c === "CHF") return "CHF ";
  const t = (inst.t || inst.ticker || "").toUpperCase();
  if (t.endsWith(".L")) return "£";
  if (!t.includes(".")) return "$";
  return "€";
}

function fmtPrice(inst: any): string {
  if (inst.price == null) return "—";
  const c   = (inst.currency || "").toUpperCase();
  const sym = currencySymbol(inst);
  const px  = Number(inst.price);
  if (c === "GBX") return `${px.toFixed(0)}p`;
  return `${sym}${px.toFixed(2)}`;
}

function fmtMCap(inst: any): string {
  if (!inst.market_cap) return "—";
  return `${currencySymbol(inst)}${(inst.market_cap / 1e9).toFixed(1)}B`;
}

function fmtRangePx(inst: any, val: number | null | undefined): string {
  if (val == null) return "—";
  const sym = currencySymbol(inst);
  const c   = (inst.currency || "").toUpperCase();
  if (c === "GBX") return `${Number(val).toFixed(0)}p`;
  return `${sym}${Number(val).toFixed(2)}`;
}

function signalPill(label: string | null | undefined): { text: string; cls: string } {
  const l = (label || "").toLowerCase();
  if (l === "strong buy")   return { text: "Strong Buy",   cls: "bg-[#D6EDDF] text-[#1E5C38]" };
  if (l === "buy")          return { text: "Buy",          cls: "bg-[#EAF3EE] text-[#2A6B44]" };
  if (l === "watch")        return { text: "Watch",        cls: "bg-[#FBF3E4] text-[#9B6B1A]" };
  if (l === "avoid")        return { text: "Avoid",        cls: "bg-[#FAEEE6] text-[#B85C20]" };
  if (l === "strong avoid") return { text: "Strong Avoid", cls: "bg-[#FAECEE] text-[#8B2635]" };
  return { text: label || "—", cls: "bg-vs-bg-subtle text-vs-ink-soft" };
}

/* ── Column definitions ──────────────────────────────────────────── */

const COLUMNS = [
  { key: "company",    label: "Company" },
  { key: "sector",     label: "Sector" },
  { key: "score",      label: "Score" },
  { key: "div_yield",  label: "Div. Yield" },
  { key: "yr1_pct",    label: "1Y Return" },
  { key: "price",      label: "Price" },
  { key: "market_cap", label: "M.Cap" },
  { key: "pe",         label: "P/E" },
];

/* ── Mock fallback data ──────────────────────────────────────────── */

const MOCK_WATCHLIST = [
  { t: "SHEL.L", name: "Shell plc",    group: "UK Stocks", asset_class: "Stock", currency: "GBP", sector: "Energy",            score: 87, score_label: "Strong Buy", div_yield: 4.1, yr1_pct:  12.3, price: 27.12, market_cap: 147e9, pe: 8.2,  pb: 1.2, ev_ebitda: 4.1, high_52w: 31.40, low_52w: 22.80 },
  { t: "HSBA.L", name: "HSBC Holdings",group: "UK Stocks", asset_class: "Stock", currency: "GBP", sector: "Financial Services", score: 82, score_label: "Buy",        div_yield: 6.1, yr1_pct:  18.4, price: 6.48,  market_cap: 118e9, pe: 6.8,  pb: 0.9, ev_ebitda: null, high_52w: 7.10,  low_52w: 5.20  },
  { t: "RIO.L",  name: "Rio Tinto",    group: "UK Stocks", asset_class: "Stock", currency: "GBP", sector: "Basic Materials",    score: 75, score_label: "Buy",        div_yield: 7.2, yr1_pct: -11.2, price: 52.80, market_cap: 85e9,  pe: 9.5,  pb: 2.1, ev_ebitda: 5.8, high_52w: 61.00, low_52w: 45.20 },
];

/* ── Main component ──────────────────────────────────────────────── */

export default function Watchlist() {
  const navigate = useNavigate();
  const { watchlist: liveWatchlist, watchlistLoading: loading, watchlistError, refetchWatchlist } = useAppData();

  const instruments: any[] = liveWatchlist.length
    ? liveWatchlist
    : !loading ? MOCK_WATCHLIST : [];

  const [searchQuery,    setSearchQuery]    = useState("");
  const [sortKey,        setSortKey]        = useState("score");
  const [sortDir,        setSortDir]        = useState<"asc" | "desc">("desc");
  const [expandedTicker, setExpandedTicker] = useState<string | null>(null);
  // ticker → "idle" | "removing" | "removed"
  const [removeState, setRemoveState] = useState<Record<string, "idle" | "removing" | "removed">>({});
  // local removal — optimistic UI, filter out removed tickers immediately
  const [removedTickers, setRemovedTickers] = useState<Set<string>>(new Set());

  const handleRemove = useCallback(async (ticker: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (removeState[ticker] === "removing") return;
    setRemoveState((s) => ({ ...s, [ticker]: "removing" }));
    // Optimistic: hide the row immediately
    setRemovedTickers((prev) => new Set([...prev, ticker]));
    if (expandedTicker === ticker) setExpandedTicker(null);
    try {
      await deleteFromWatchlist(ticker);
      // Sync context so the home quadrant and any other consumers update
      refetchWatchlist();
    } catch (_) {
      // Best-effort — row is already hidden; backend may be offline
    }
    setRemoveState((s) => ({ ...s, [ticker]: "removed" }));
  }, [removeState, expandedTicker, refetchWatchlist]);

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const filtered = useMemo(() => {
    let list = instruments.filter((i: any) => {
      const ticker = (i.t || i.ticker || "").toUpperCase();
      return !removedTickers.has(ticker);
    });

    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      list = list.filter((i: any) =>
        (i.t || i.ticker || "").toLowerCase().includes(q) ||
        (i.name || "").toLowerCase().includes(q)
      );
    }

    const sk = sortKey;
    list.sort((a: any, b: any) => {
      const av = a[sk] ?? (sortDir === "desc" ? -Infinity : Infinity);
      const bv = b[sk] ?? (sortDir === "desc" ? -Infinity : Infinity);
      return sortDir === "desc" ? bv - av : av - bv;
    });

    return list;
  }, [instruments, searchQuery, sortKey, sortDir, removedTickers]);

  const isEmpty = !loading && filtered.length === 0 && removedTickers.size === 0 && !searchQuery;

  return (
    <div className="py-8 lg:py-10">
      {/* ── Header ── */}
      <div className="flex flex-col md:flex-row md:items-end md:justify-between mb-6">
        <div>
          <h1 className="font-mono text-2xl md:text-[36px] font-medium text-vs-ink tracking-tight leading-tight">
            Watchlist
          </h1>
          <p className="text-[14px] text-vs-ink-mid mt-1">
            {loading ? "Loading…" : `${filtered.length} instrument${filtered.length !== 1 ? "s" : ""} tracked`}
          </p>
        </div>
        {!isEmpty && (
          <div className="relative mt-4 md:mt-0">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-vs-ink-soft" />
            <input
              type="text"
              placeholder="Search ticker or company…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9 pr-4 py-2 text-[13px] border border-vs-rule bg-vs-bg-card outline-none focus:border-vs-accent w-64"
            />
          </div>
        )}
      </div>

      {/* ── Empty state ── */}
      {isEmpty && (
        <div className="border border-vs-rule bg-vs-bg-card px-8 py-16 text-center">
          <Bookmark className="w-10 h-10 text-vs-ink-soft mx-auto mb-4" strokeWidth={1.5} />
          <p className="text-[15px] font-semibold text-vs-ink mb-1">Watchlist is empty.</p>
          <p className="text-[13px] text-vs-ink-soft mb-6">
            Find something interesting.
          </p>
          <button
            onClick={() => navigate("/screener")}
            className="px-5 py-2.5 text-[11px] font-semibold uppercase tracking-wider border border-vs-accent text-vs-accent hover:bg-vs-accent hover:text-white transition-colors"
          >
            Go to Screener
          </button>
        </div>
      )}

      {/* ── Table ── */}
      {!isEmpty && (
        <div className="bg-vs-bg-card border border-vs-rule">
          {/* Table header bar */}
          <div className="flex items-center justify-between px-4 py-3 bg-vs-bg-raised border-b border-vs-rule">
            <span className="text-[11px] text-vs-ink-soft font-semibold flex items-center gap-2">
              {loading ? (
                <>
                  <span className="w-2 h-2 rounded-full bg-vs-accent animate-pulse inline-block" />
                  Loading watchlist…
                </>
              ) : watchlistError ? (
                <>
                  <span className="w-2 h-2 rounded-full bg-vs-neg inline-block" />
                  Sample data — {filtered.length} results
                </>
              ) : (
                `${filtered.length} instrument${filtered.length !== 1 ? "s" : ""}`
              )}
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[800px]">
              <thead>
                <tr className="bg-vs-bg-subtle">
                  {COLUMNS.map((col) => (
                    <th
                      key={col.key}
                      onClick={() => handleSort(col.key)}
                      className="text-left text-[10px] font-bold uppercase tracking-widest text-vs-ink-soft px-4 py-3 cursor-pointer hover:text-vs-accent group"
                    >
                      <span className="flex items-center gap-1">
                        {col.label}
                        <ArrowUpDown
                          className={cn(
                            "w-3 h-3 transition-opacity",
                            sortKey === col.key ? "opacity-100 text-vs-accent" : "opacity-0 group-hover:opacity-60"
                          )}
                        />
                      </span>
                    </th>
                  ))}
                  {/* Actions column header — no sort */}
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody>
                {/* Loading skeleton */}
                {loading && Array.from({ length: 5 }).map((_, i) => (
                  <tr key={`skel-${i}`} className="border-b border-vs-rule last:border-0">
                    {[...COLUMNS, { key: "_action" }].map((col) => (
                      <td key={col.key} className="px-4 py-3">
                        <div className={cn(
                          "h-3 bg-vs-bg-subtle animate-pulse rounded-sm",
                          col.key === "company" ? "w-36" :
                          col.key === "sector"  ? "w-24" :
                          col.key === "score"   ? "w-8"  : "w-12"
                        )} />
                      </td>
                    ))}
                  </tr>
                ))}

                {/* No search results */}
                {!loading && filtered.length === 0 && searchQuery && (
                  <tr>
                    <td colSpan={COLUMNS.length + 1} className="px-4 py-12 text-center">
                      <p className="text-[13px] text-vs-ink-soft">No instruments match your search.</p>
                      <button
                        onClick={() => setSearchQuery("")}
                        className="mt-2 text-[11px] font-semibold text-vs-accent uppercase tracking-wider"
                      >
                        Clear search
                      </button>
                    </td>
                  </tr>
                )}

                {filtered.map((inst: any) => {
                  const ticker  = inst.t || inst.ticker || "";
                  const name    = inst.name || inst.company || ticker;
                  const score   = inst.score ?? 0;
                  const isOpen  = expandedTicker === ticker;
                  const rmState = removeState[ticker] ?? "idle";

                  const scoreBg =
                    score >= 80 ? "bg-vs-accent"
                    : score >= 65 ? "bg-vs-ink-mid"
                    : "bg-vs-ink-soft";

                  return (
                    <React.Fragment key={ticker}>
                      {/* ── Main row ── */}
                      <tr
                        onClick={() => setExpandedTicker(isOpen ? null : ticker)}
                        className={cn(
                          "border-b border-vs-rule cursor-pointer transition-colors group",
                          isOpen ? "bg-vs-bg-raised" : "hover:bg-vs-bg-raised"
                        )}
                      >
                        {/* Company */}
                        <td className="px-4 py-3">
                          <div>
                            <span className="text-[14px] font-semibold text-vs-ink flex items-center gap-1.5">
                              {name}
                              <ChevronDown className={cn(
                                "w-3.5 h-3.5 text-vs-ink-soft transition-transform shrink-0",
                                isOpen ? "rotate-180 text-vs-accent" : "opacity-0 group-hover:opacity-60"
                              )} />
                            </span>
                            <span className="text-[10px] text-vs-ink-soft uppercase tracking-wider">{ticker}</span>
                          </div>
                        </td>

                        {/* Sector */}
                        <td className="px-4 py-3 text-[13px] text-vs-ink-mid">
                          {inst.sector || "—"}
                        </td>

                        {/* Score */}
                        <td className="px-4 py-3">
                          <span className={cn(
                            "inline-flex items-center justify-center w-10 h-8 font-mono text-[14px] font-medium text-white",
                            scoreBg
                          )}>
                            {score > 0 ? Math.round(score) : "—"}
                          </span>
                        </td>

                        {/* Div Yield */}
                        <td className="px-4 py-3 text-[13px] font-semibold text-vs-ink">
                          {inst.div_yield != null ? `${Number(inst.div_yield).toFixed(1)}%` : "—"}
                        </td>

                        {/* 1Y Return */}
                        <td className="px-4 py-3">
                          {inst.yr1_pct != null ? (
                            <span className={cn(
                              "text-[13px] font-semibold flex items-center gap-1",
                              inst.yr1_pct >= 0 ? "text-vs-pos" : "text-vs-neg"
                            )}>
                              {inst.yr1_pct >= 0
                                ? <TrendingUp className="w-3.5 h-3.5 shrink-0" />
                                : <TrendingDown className="w-3.5 h-3.5 shrink-0" />}
                              {inst.yr1_pct >= 0 ? "+" : ""}{Number(inst.yr1_pct).toFixed(1)}%
                            </span>
                          ) : (
                            <span className="text-[13px] text-vs-ink-soft">—</span>
                          )}
                        </td>

                        {/* Price */}
                        <td className="px-4 py-3 text-[13px] font-semibold text-vs-ink">
                          {fmtPrice(inst)}
                        </td>

                        {/* Market Cap */}
                        <td className="px-4 py-3 text-[13px] text-vs-ink-mid">
                          {fmtMCap(inst)}
                        </td>

                        {/* P/E */}
                        <td className="px-4 py-3 text-[13px] text-vs-ink-mid">
                          {(inst.pe ?? inst.pe_ratio) != null ? Number(inst.pe ?? inst.pe_ratio).toFixed(1) : "—"}
                        </td>

                        {/* Remove button */}
                        <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                          <button
                            onClick={(e) => handleRemove(ticker, e)}
                            disabled={rmState === "removing"}
                            title="Remove from watchlist"
                            className="flex items-center gap-1 text-[11px] font-semibold text-vs-ink-soft hover:text-vs-neg disabled:opacity-30 transition-colors"
                          >
                            <X className="w-3.5 h-3.5" />
                          </button>
                        </td>
                      </tr>

                      {/* ── Expander row ── */}
                      {isOpen && (
                        <tr key={`${ticker}-expanded`} className="border-b border-vs-rule bg-vs-bg-raised">
                          <td colSpan={COLUMNS.length + 1} className="px-6 py-4">
                            <div className="flex flex-col md:flex-row md:items-start gap-5">

                              {/* Quick stats */}
                              <div className="grid grid-cols-3 md:grid-cols-6 gap-3 flex-1">
                                {/* Div Yield */}
                                <div className="flex flex-col gap-0.5">
                                  <span className="text-[10px] font-semibold uppercase tracking-widest text-vs-ink-soft">Div. Yield</span>
                                  <span className="text-[13px] font-semibold text-vs-ink">
                                    {inst.div_yield != null ? `${Number(inst.div_yield).toFixed(1)}%` : "—"}
                                  </span>
                                </div>

                                {/* P/B */}
                                <div className="flex flex-col gap-0.5">
                                  <span className="text-[10px] font-semibold uppercase tracking-widest text-vs-ink-soft">P/B Ratio</span>
                                  <span className="text-[13px] font-semibold text-vs-ink">
                                    {(inst.pb ?? inst.pb_ratio ?? inst.price_to_book) != null
                                      ? Number(inst.pb ?? inst.pb_ratio ?? inst.price_to_book).toFixed(2)
                                      : "—"}
                                  </span>
                                </div>

                                {/* EV/EBITDA */}
                                <div className="flex flex-col gap-0.5">
                                  <span className="text-[10px] font-semibold uppercase tracking-widest text-vs-ink-soft">EV/EBITDA</span>
                                  <span className="text-[13px] font-semibold text-vs-ink">
                                    {inst.ev_ebitda != null ? Number(inst.ev_ebitda).toFixed(1) : "—"}
                                  </span>
                                </div>

                                {/* 52W High */}
                                <div className="flex flex-col gap-0.5">
                                  <span className="text-[10px] font-semibold uppercase tracking-widest text-vs-ink-soft">52W High</span>
                                  <span className="text-[13px] font-semibold text-vs-ink">
                                    {fmtRangePx(inst, inst.high_52w ?? inst.week52_high)}
                                  </span>
                                </div>

                                {/* 52W Low */}
                                <div className="flex flex-col gap-0.5">
                                  <span className="text-[10px] font-semibold uppercase tracking-widest text-vs-ink-soft">52W Low</span>
                                  <span className="text-[13px] font-semibold text-vs-ink">
                                    {fmtRangePx(inst, inst.low_52w ?? inst.week52_low)}
                                  </span>
                                </div>

                                {/* Signal pill */}
                                <div className="flex flex-col gap-0.5">
                                  <span className="text-[10px] font-semibold uppercase tracking-widest text-vs-ink-soft">Signal</span>
                                  {(() => {
                                    const pill = signalPill(inst.score_label);
                                    return (
                                      <span className={cn(
                                        "self-start px-2 py-0.5 text-[11px] font-bold rounded-sm whitespace-nowrap",
                                        pill.cls
                                      )}>
                                        {pill.text}
                                      </span>
                                    );
                                  })()}
                                </div>
                              </div>

                              {/* Action buttons */}
                              <div className="flex items-center gap-2 shrink-0 md:self-center">
                                <button
                                  onClick={(e) => handleRemove(ticker, e)}
                                  disabled={rmState === "removing"}
                                  className="flex items-center gap-1.5 px-3.5 py-2 text-[11px] font-semibold uppercase tracking-wider border border-vs-rule text-vs-ink-mid hover:border-vs-neg hover:text-vs-neg transition-colors disabled:opacity-40"
                                >
                                  <BookmarkX className="w-3.5 h-3.5" />
                                  {rmState === "removing" ? "Removing…" : "Remove"}
                                </button>

                                <button
                                  onClick={(e) => { e.stopPropagation(); navigate(`/deepdive?ticker=${ticker}`); }}
                                  className="flex items-center gap-1.5 px-3.5 py-2 text-[11px] font-semibold uppercase tracking-wider border border-vs-accent text-vs-accent hover:bg-vs-accent hover:text-white transition-colors"
                                >
                                  <ExternalLink className="w-3.5 h-3.5" />
                                  Deep Dive
                                </button>
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
