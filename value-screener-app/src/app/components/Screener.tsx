import { useState, useMemo, useRef, useEffect, useCallback } from "react";
import { Link, useNavigate } from "react-router";
import {
  Search,
  ArrowUpDown,
  ChevronDown,
  Download,
  X,
  Bookmark,
  BookmarkCheck,
  ExternalLink,
  TrendingUp,
  TrendingDown,
} from "lucide-react";
import { cn } from "../utils";
import { useAppData } from "../useAppData";
import { addToWatchlist } from "../../api/client";

/* ── Constants ───────────────────────────────────────────────── */

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

// Preset tab → filter combination
const PRESETS: Record<string, { sortKey?: string; minScore?: number; minDivYield?: number; minQuality?: number }> = {
  "All":           {},
  "Value Leaders": { sortKey: "value_score",  minScore: 60 },
  "High Yield":    { sortKey: "div_yield",    minDivYield: 2 },
  "Dividend":      { sortKey: "div_yield",    minDivYield: 3, minQuality: 50 },
};

const PRESET_LABELS = Object.keys(PRESETS);

// Cap band thresholds (using GBP market cap)
const CAP_BANDS = [
  { label: "Mega",  min: 100e9, max: Infinity },
  { label: "Large", min: 10e9,  max: 100e9 },
  { label: "Mid",   min: 1e9,   max: 10e9 },
  { label: "Small", min: 0,     max: 1e9 },
];

// Currency symbol helper
function currencySymbol(inst: any): string {
  const c = (inst.currency || "").toUpperCase();
  if (c === "GBP" || c === "GBX") return "£";
  if (c === "USD") return "$";
  if (c === "EUR") return "€";
  if (c === "JPY") return "¥";
  if (c === "CHF") return "CHF ";
  // Fallback: infer from ticker suffix
  const t = (inst.t || inst.ticker || "").toUpperCase();
  if (t.endsWith(".L"))  return "£";
  if (!t.includes("."))  return "$";
  return "€";
}

// Format price with correct currency and scale (GBX → pence, show as £)
function fmtPrice(inst: any): string {
  if (inst.price == null) return "—";
  const c    = (inst.currency || "").toUpperCase();
  const sym  = currencySymbol(inst);
  const px   = Number(inst.price);
  // GBX (pence) — keep as pence with p suffix
  if (c === "GBX") return `${px.toFixed(0)}p`;
  return `${sym}${px.toFixed(2)}`;
}

// Format market cap with currency
function fmtMCap(inst: any): string {
  if (!inst.market_cap) return "—";
  const sym = currencySymbol(inst);
  return `${sym}${(inst.market_cap / 1e9).toFixed(1)}B`;
}

// Format 52-week price with currency
function fmtRangePx(inst: any, val: number | null | undefined): string {
  if (val == null) return "—";
  const sym = currencySymbol(inst);
  const c   = (inst.currency || "").toUpperCase();
  if (c === "GBX") return `${Number(val).toFixed(0)}p`;
  return `${sym}${Number(val).toFixed(2)}`;
}

// Signal label → pastel pill colours (matches theme.css pos/neg/amber)
function signalPill(label: string | null | undefined): { text: string; cls: string } {
  const l = (label || "").toLowerCase();
  if (l === "strong buy")   return { text: "Strong Buy",   cls: "bg-[#D6EDDF] text-[#1E5C38]" };
  if (l === "buy")          return { text: "Buy",          cls: "bg-[#EAF3EE] text-[#2A6B44]" };
  if (l === "watch")        return { text: "Watch",        cls: "bg-[#FBF3E4] text-[#9B6B1A]" };
  if (l === "avoid")        return { text: "Avoid",        cls: "bg-[#FAEEE6] text-[#B85C20]" };
  if (l === "strong avoid") return { text: "Strong Avoid", cls: "bg-[#FAECEE] text-[#8B2635]" };
  return { text: label || "—", cls: "bg-vs-bg-subtle text-vs-ink-soft" };
}

// EU exchange suffixes (non-UK European exchanges)
const EU_SUFFIXES = new Set([
  ".MC", ".PA", ".AS", ".DE", ".MI", ".BR", ".LS", ".ST", ".CO",
  ".OL", ".HE", ".VI", ".SW", ".IR", ".WA", ".PR",
]);

// Group name → jurisdiction
function jurisdictionOf(inst: any): string {
  // 1. Use the group field if present — most reliable
  const g = (inst.group || "").toLowerCase();
  if (g.includes("uk"))  return "UK";
  if (g.includes("us"))  return "US";
  if (g.includes("eu"))  return "EU";

  // 2. Infer from ticker suffix
  const t = (inst.t || inst.ticker || "").toUpperCase();
  if (t.endsWith(".L"))  return "UK";
  const dot = t.lastIndexOf(".");
  if (dot !== -1 && EU_SUFFIXES.has(t.slice(dot))) return "EU";
  if (t.includes("."))   return "EU";   // any other exchange suffix → EU

  // 3. No suffix = US (NYSE / NASDAQ)
  return "US";
}

function capBandOf(inst: any): string {
  const mc = inst.market_cap ?? 0;
  for (const b of CAP_BANDS) {
    if (mc >= b.min && mc < b.max) return b.label;
  }
  return "Small";
}

/* ── FilterDropdown component ───────────────────────────────── */
interface FilterDropdownProps {
  label: string;
  options: string[];
  selected: string[];
  onChange: (next: string[]) => void;
}

function FilterDropdown({ label, options, selected, onChange }: FilterDropdownProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const active = selected.length > 0;

  // Close on outside click
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  function toggle(opt: string) {
    onChange(
      selected.includes(opt)
        ? selected.filter((s) => s !== opt)
        : [...selected, opt]
    );
  }

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "flex items-center gap-1.5 px-3.5 py-2 text-[11px] font-semibold uppercase tracking-[0.08em] border transition-colors",
          active
            ? "border-vs-accent text-vs-accent bg-vs-accent/5"
            : "border-vs-rule text-vs-ink-mid hover:border-vs-ink hover:text-vs-ink"
        )}
      >
        {label}
        {active && (
          <span className="w-4 h-4 rounded-full bg-vs-accent text-white text-[9px] font-bold flex items-center justify-center leading-none">
            {selected.length}
          </span>
        )}
        <ChevronDown className={cn("w-3 h-3 transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <div className="absolute left-0 top-full mt-1 z-50 bg-vs-bg-card border border-vs-rule shadow-lg min-w-[160px] py-1">
          {options.map((opt) => {
            const checked = selected.includes(opt);
            return (
              <button
                key={opt}
                onClick={() => toggle(opt)}
                className={cn(
                  "w-full flex items-center gap-2.5 px-3.5 py-2 text-[12px] font-medium text-left transition-colors",
                  checked
                    ? "text-vs-accent bg-vs-accent/5"
                    : "text-vs-ink hover:bg-vs-bg-raised"
                )}
              >
                {/* Checkbox */}
                <span className={cn(
                  "w-3.5 h-3.5 border flex items-center justify-center shrink-0",
                  checked ? "bg-vs-accent border-vs-accent" : "border-vs-rule"
                )}>
                  {checked && <X className="w-2.5 h-2.5 text-white" strokeWidth={3} />}
                </span>
                {opt}
              </button>
            );
          })}
          {selected.length > 0 && (
            <>
              <div className="border-t border-vs-rule my-1" />
              <button
                onClick={() => { onChange([]); setOpen(false); }}
                className="w-full px-3.5 py-1.5 text-[11px] font-semibold text-vs-ink-soft hover:text-vs-neg uppercase tracking-wider text-left"
              >
                Clear
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Main component ─────────────────────────────────────────── */

export default function Screener() {
  const navigate = useNavigate();
  const [activePreset,   setActivePreset]   = useState("All");
  const [searchQuery,    setSearchQuery]    = useState("");
  const [sortKey,        setSortKey]        = useState("score");
  const [sortDir,        setSortDir]        = useState<"asc" | "desc">("desc");
  const [expandedTicker, setExpandedTicker] = useState<string | null>(null);
  // ticker → "idle" | "adding" | "added"
  const [watchlistState, setWatchlistState] = useState<Record<string, "idle" | "adding" | "added">>({});

  // Filter state
  const [filterType,     setFilterType]     = useState<string[]>([]);
  const [filterJuris,    setFilterJuris]    = useState<string[]>([]);
  const [filterCap,      setFilterCap]      = useState<string[]>([]);
  const [filterSector,   setFilterSector]   = useState<string[]>([]);
  const [filterMomentum, setFilterMomentum] = useState<string[]>([]);

  const { instruments: liveInstruments, screenerLoading: loading, screenerError, refetchWatchlist } = useAppData();

  const MOCK_INSTRUMENTS = [
    { t: "SHEL.L", name: "Shell plc",              group: "UK Stocks",        asset_class: "Stock", currency: "GBP", sector: "Energy",            score: 87, div_yield: 4.1, yr1_pct:  12.3, price: 27.12, market_cap: 147e9, pe: 8.2  },
    { t: "BP.L",   name: "BP plc",                group: "UK Stocks",        asset_class: "Stock", currency: "GBP", sector: "Energy",            score: 84, div_yield: 5.2, yr1_pct:  -8.1, price: 4.85,  market_cap: 73e9,  pe: 7.1  },
    { t: "HSBA.L", name: "HSBC Holdings",          group: "UK Stocks",        asset_class: "Stock", currency: "GBP", sector: "Financial Services", score: 82, div_yield: 6.1, yr1_pct:  18.4, price: 6.48,  market_cap: 118e9, pe: 6.8  },
    { t: "ULVR.L", name: "Unilever plc",           group: "UK Stocks",        asset_class: "Stock", currency: "GBP", sector: "Consumer Defensive", score: 79, div_yield: 3.8, yr1_pct:   4.2, price: 43.21, market_cap: 102e9, pe: 16.4 },
    { t: "AAPL",   name: "Apple Inc.",             group: "US Stocks",        asset_class: "Stock", currency: "USD", sector: "Technology",         score: 75, div_yield: 0.5, yr1_pct:  -5.6, price: 178.72,market_cap: 2800e9,pe: 28.5 },
    { t: "MSFT",   name: "Microsoft Corp.",        group: "US Stocks",        asset_class: "Stock", currency: "USD", sector: "Technology",         score: 78, div_yield: 0.7, yr1_pct:  22.1, price: 378.91,market_cap: 2600e9,pe: 32.1 },
    { t: "SAP.DE", name: "SAP SE",                 group: "EU Stocks",        asset_class: "Stock", currency: "EUR", sector: "Technology",         score: 71, div_yield: 1.2, yr1_pct:  31.0, price: 184.32,market_cap: 220e9, pe: 38.2 },
    { t: "VWRL.L", name: "Vanguard FTSE All-World",group: "ETFs & Index Funds",asset_class: "ETF",  currency: "GBP", sector: "ETF",               score: 80, div_yield: 1.8, yr1_pct:  14.7, price: 98.20, market_cap: 45e9,  pe: null },
    { t: "BARC.L", name: "Barclays plc",           group: "UK Stocks",        asset_class: "Stock", currency: "GBP", sector: "Financial Services", score: 74, div_yield: 3.5, yr1_pct:  28.9, price: 1.98,  market_cap: 33e9,  pe: 5.9  },
    { t: "RIO.L",  name: "Rio Tinto",              group: "UK Stocks",        asset_class: "Stock", currency: "GBP", sector: "Basic Materials",    score: 75, div_yield: 7.2, yr1_pct: -11.2, price: 52.80, market_cap: 85e9,  pe: 9.5  },
  ];

  const instruments = liveInstruments.length ? liveInstruments : (!loading ? MOCK_INSTRUMENTS : []);

  // Derive dynamic sector list from live data
  const allSectors = useMemo(() => {
    const s = new Set<string>();
    instruments.forEach((i: any) => { if (i.sector) s.add(i.sector); });
    return Array.from(s).sort();
  }, [instruments]);

  // Silent add-to-watchlist with tick confirmation + context refresh
  const handleAddWatchlist = useCallback(async (ticker: string, name: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (watchlistState[ticker] === "added" || watchlistState[ticker] === "adding") return;
    setWatchlistState((s) => ({ ...s, [ticker]: "adding" }));
    let succeeded = false;
    try {
      await addToWatchlist(ticker, name);
      succeeded = true;
    } catch (_) {
      // Best-effort — still show confirmation even if backend is offline
    }
    setWatchlistState((s) => ({ ...s, [ticker]: "added" }));
    // Refresh the watchlist context so the Watchlist page shows the new item
    if (succeeded) refetchWatchlist();
    // Reset badge back to idle after 2.5s
    setTimeout(() => setWatchlistState((s) => ({ ...s, [ticker]: "idle" })), 2500);
  }, [watchlistState, refetchWatchlist]);

  // Preset → apply sort overrides (filters are set separately by the dropdowns)
  function applyPreset(name: string) {
    setActivePreset(name);
    setExpandedTicker(null);
    const p = PRESETS[name];
    if (!p) return;
    // Reset all filters on preset switch
    setFilterType([]);
    setFilterJuris([]);
    setFilterCap([]);
    setFilterSector([]);
    setFilterMomentum([]);
    setSortKey(p.sortKey ?? "score");
    setSortDir("desc");
  }

  const anyFilterActive =
    filterType.length > 0 || filterJuris.length > 0 ||
    filterCap.length > 0  || filterSector.length > 0 || filterMomentum.length > 0;

  function clearAllFilters() {
    setFilterType([]); setFilterJuris([]);
    setFilterCap([]);  setFilterSector([]);
    setFilterMomentum([]);
    setActivePreset("All");
  }

  const filtered = useMemo(() => {
    const preset = PRESETS[activePreset] ?? {};
    let list = [...instruments];

    // Search
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      list = list.filter((i: any) =>
        (i.t || i.ticker || "").toLowerCase().includes(q) ||
        (i.name || i.company || "").toLowerCase().includes(q)
      );
    }

    // Type filter
    if (filterType.length) {
      list = list.filter((i: any) => {
        const ac = (i.asset_class || "Stock");
        return filterType.includes(ac);
      });
    }

    // Jurisdiction filter
    if (filterJuris.length) {
      list = list.filter((i: any) => filterJuris.includes(jurisdictionOf(i)));
    }

    // Cap filter
    if (filterCap.length) {
      list = list.filter((i: any) => filterCap.includes(capBandOf(i)));
    }

    // Sector filter
    if (filterSector.length) {
      list = list.filter((i: any) => filterSector.includes(i.sector));
    }

    // Momentum filter: Recent Drops (mom ≤ 35), Recent Risers (mom ≥ 70)
    if (filterMomentum.length) {
      list = list.filter((i: any) => {
        const m = i.momentum_score ?? 50;
        return filterMomentum.some((f) =>
          f === "Recent Drops"  ? m <= 35 :
          f === "Recent Risers" ? m >= 70 :
          false
        );
      });
    }

    // Preset-specific score/yield/quality gates — exclude pending (un-scored) instruments
    const hasPresetFilter = preset.minScore != null || preset.minDivYield != null || preset.minQuality != null;
    if (hasPresetFilter) list = list.filter((i: any) => !i.pending && i.score != null);
    if (preset.minScore    != null) list = list.filter((i: any) => (i.score ?? 0)         >= preset.minScore!);
    if (preset.minDivYield != null) list = list.filter((i: any) => (i.div_yield ?? 0)     >= preset.minDivYield!);
    if (preset.minQuality  != null) list = list.filter((i: any) => (i.quality_score ?? 0) >= preset.minQuality!);

    // Sort — pending (un-scored) instruments always fall to the bottom
    const sk = sortKey;
    list.sort((a: any, b: any) => {
      const aPending = a.pending === true || a.score == null;
      const bPending = b.pending === true || b.score == null;
      if (aPending && !bPending) return 1;
      if (!aPending && bPending) return -1;
      if (aPending && bPending) return (a.name || "").localeCompare(b.name || "");
      const av = a[sk] ?? (sortDir === "desc" ? -Infinity : Infinity);
      const bv = b[sk] ?? (sortDir === "desc" ? -Infinity : Infinity);
      return sortDir === "desc" ? bv - av : av - bv;
    });

    return list;
  }, [instruments, searchQuery, filterType, filterJuris, filterCap, filterSector, filterMomentum, activePreset, sortKey, sortDir]);

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  return (
    <div className="py-8 lg:py-10">
      {/* ── Header ── */}
      <div className="flex flex-col md:flex-row md:items-end md:justify-between mb-6">
        <div>
          <h1 className="font-mono text-2xl md:text-[36px] font-medium text-vs-ink tracking-tight leading-tight">
            Scores
          </h1>
          <p className="text-[13px] text-vs-ink-mid mt-1">
            Filter and sort by value, quality and momentum.
          </p>
        </div>
        <div className="flex items-center gap-2 mt-4 md:mt-0">
          <div className="relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-vs-ink-soft" />
            <input
              type="text"
              placeholder="Search ticker or company…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9 pr-4 py-2 text-[13px] border border-vs-rule bg-vs-bg-card outline-none focus:border-vs-accent w-64"
            />
          </div>
        </div>
      </div>

      {/* ── Preset tabs ── */}
      <div className="border-t border-b border-vs-rule overflow-x-auto [&::-webkit-scrollbar]:hidden">
        <div className="flex">
          {PRESET_LABELS.map((tab) => (
            <button
              key={tab}
              onClick={() => applyPreset(tab)}
              className={cn(
                "text-[11px] font-semibold uppercase tracking-[0.08em] px-5 py-3 border-b-2 transition-colors whitespace-nowrap",
                tab === activePreset
                  ? "text-vs-accent border-vs-accent"
                  : "text-vs-ink-mid border-transparent hover:text-vs-ink"
              )}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      {/* ── Filter bar ── */}
      <div className="flex flex-wrap items-center gap-2 mt-4">
        <FilterDropdown
          label="Type"
          options={["Stock", "ETF", "Money Market"]}
          selected={filterType}
          onChange={(v) => { setFilterType(v); setActivePreset("All"); }}
        />
        <FilterDropdown
          label="Jurisdiction"
          options={["UK", "US", "EU"]}
          selected={filterJuris}
          onChange={(v) => { setFilterJuris(v); setActivePreset("All"); }}
        />
        <FilterDropdown
          label="Cap"
          options={CAP_BANDS.map((b) => b.label)}
          selected={filterCap}
          onChange={(v) => { setFilterCap(v); setActivePreset("All"); }}
        />
        <FilterDropdown
          label="Sector"
          options={allSectors}
          selected={filterSector}
          onChange={(v) => { setFilterSector(v); setActivePreset("All"); }}
        />
        <FilterDropdown
          label="Momentum"
          options={["Recent Risers", "Recent Drops"]}
          selected={filterMomentum}
          onChange={(v) => { setFilterMomentum(v); setActivePreset("All"); }}
        />

        {anyFilterActive && (
          <button
            onClick={clearAllFilters}
            className="ml-1 flex items-center gap-1 text-[11px] font-semibold text-vs-ink-soft hover:text-vs-neg uppercase tracking-wider transition-colors"
          >
            <X className="w-3 h-3" />
            Clear all
          </button>
        )}
      </div>

      {/* ── Table ── */}
      <div className="mt-5 bg-vs-bg-card border border-vs-rule">
        {/* Table header bar */}
        <div className="flex items-center justify-between px-4 py-3 bg-vs-bg-raised border-b border-vs-rule">
          <span className="text-[11px] text-vs-ink-soft font-semibold flex items-center gap-2">
            {loading ? (
              <>
                <span className="w-2 h-2 rounded-full bg-vs-accent animate-pulse inline-block" />
                Waking up server…
              </>
            ) : screenerError ? (
              <>
                <span className="w-2 h-2 rounded-full bg-vs-neg inline-block" />
                Cached data — {filtered.length} results
              </>
            ) : (
              (() => {
                const scored = filtered.filter((i: any) => !i.pending && i.score != null).length;
                const total  = filtered.length;
                return scored < total
                  ? `${scored} scored · ${total - scored} loading`
                  : `${total} result${total !== 1 ? "s" : ""}`;
              })()
            )}
          </span>
          <button
            onClick={() => {
              const headers = ["Ticker","Name","Sector","Asset Class","Score","Price","Div Yield","1Y Return","P/E","Market Cap"];
              const rows = filtered.map((i: any) => [
                i.ticker ?? i.t ?? "",
                i.name ?? "",
                i.sector ?? "",
                i.asset_class ?? "",
                i.score != null ? Math.round(i.score) : "",
                i.price ?? "",
                i.div_yield ?? "",
                i.yr1_pct ?? "",
                i.pe ?? "",
                i.market_cap ?? "",
              ]);
              const csv = [headers, ...rows].map(r => r.map(String).map(v => `"${v.replace(/"/g,'""')}"`).join(",")).join("\n");
              const blob = new Blob([csv], { type: "text/csv" });
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = `bens-shed-scores-${new Date().toISOString().slice(0,10)}.csv`;
              a.click();
              URL.revokeObjectURL(url);
            }}
            className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-vs-ink-mid hover:text-vs-accent"
          >
            <Download className="w-3.5 h-3.5" />
            Export
          </button>
        </div>

        {/* Offline banner */}
        {!loading && screenerError && (
          <div className="px-4 py-2 bg-vs-bg-raised border-b border-vs-rule flex items-center gap-2">
            <span className="text-[11px] text-vs-ink-soft">
              Live data unavailable — showing sample instruments.
            </span>
            <button
              onClick={() => window.location.reload()}
              className="ml-auto text-[11px] font-semibold text-vs-accent hover:text-vs-accent-dark uppercase tracking-wider whitespace-nowrap"
            >
              Retry
            </button>
          </div>
        )}

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
              </tr>
            </thead>
            <tbody>
              {/* Loading skeleton */}
              {loading && Array.from({ length: 10 }).map((_, i) => (
                <tr key={`skel-${i}`} className="border-b border-vs-rule last:border-0">
                  {COLUMNS.map((col) => (
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

              {/* No results */}
              {!loading && filtered.length === 0 && (
                <tr>
                  <td colSpan={COLUMNS.length} className="px-4 py-12 text-center">
                    <p className="text-[13px] text-vs-ink-soft">No instruments match your filters.</p>
                    {anyFilterActive && (
                      <button
                        onClick={clearAllFilters}
                        className="mt-2 text-[11px] font-semibold text-vs-accent uppercase tracking-wider"
                      >
                        Clear filters
                      </button>
                    )}
                  </td>
                </tr>
              )}

              {filtered.map((inst: any) => {
                const ticker    = inst.t || inst.ticker || "";
                const name      = inst.name || inst.company || ticker;
                const score     = inst.score ?? 0;
                const isPending = inst.pending === true || inst.score == null;
                const isOpen    = expandedTicker === ticker;
                const wlState   = watchlistState[ticker] ?? "idle";

                const scoreBg =
                  isPending     ? "bg-vs-bg-subtle"
                  : score >= 80 ? "bg-vs-accent"
                  : score >= 65 ? "bg-vs-ink-mid"
                  : "bg-vs-ink-soft";

                return (
                  <>
                    {/* ── Main row ── */}
                    <tr
                      key={ticker}
                      onClick={() => !isPending && setExpandedTicker(isOpen ? null : ticker)}
                      className={cn(
                        "border-b border-vs-rule transition-colors group",
                        isPending
                          ? "opacity-40 cursor-default"
                          : isOpen
                          ? "bg-vs-bg-raised border-vs-accent/30 cursor-pointer"
                          : "hover:bg-vs-bg-raised cursor-pointer"
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
                          <span className="text-[10px] text-vs-ink-soft uppercase tracking-wider">
                            {ticker}
                          </span>
                        </div>
                      </td>

                      {/* Sector */}
                      <td className="px-4 py-3 text-[13px] text-vs-ink-mid">
                        {inst.sector || "—"}
                      </td>

                      {/* Score */}
                      <td className="px-4 py-3">
                        <span className={cn(
                          "inline-flex items-center justify-center w-10 h-8 font-mono text-[14px] font-medium",
                          isPending ? "text-vs-ink-faint" : "text-white",
                          scoreBg
                        )}>
                          {isPending ? "—" : score > 0 ? Math.round(score) : "—"}
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
                            {inst.yr1_pct >= 0 ? <TrendingUp className="w-3.5 h-3.5 shrink-0" /> : <TrendingDown className="w-3.5 h-3.5 shrink-0" />}
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

                      {/* P/E — backend sends field as `pe`, not `pe_ratio` */}
                      <td className="px-4 py-3 text-[13px] text-vs-ink-mid">
                        {(inst.pe ?? inst.pe_ratio) != null ? Number(inst.pe ?? inst.pe_ratio).toFixed(1) : "—"}
                      </td>
                    </tr>

                    {/* ── Expander row ── */}
                    {isOpen && (
                      <tr key={`${ticker}-expanded`} className="border-b border-vs-rule bg-vs-bg-raised">
                        <td colSpan={COLUMNS.length} className="px-6 py-4">
                          <div className="flex flex-col md:flex-row md:items-start gap-5">

                            {/* Quick stats grid */}
                            <div className="grid grid-cols-3 md:grid-cols-6 gap-3 flex-1">
                              {/* Div Yield */}
                              <div className="flex flex-col gap-0.5">
                                <span className="text-[10px] font-semibold uppercase tracking-widest text-vs-ink-soft">Div. Yield</span>
                                <span className="text-[13px] font-semibold text-vs-ink">
                                  {inst.div_yield != null ? `${Number(inst.div_yield).toFixed(1)}%` : "—"}
                                </span>
                              </div>

                              {/* P/B — backend: `pb` */}
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

                              {/* 52W High — backend: `high_52w` */}
                              <div className="flex flex-col gap-0.5">
                                <span className="text-[10px] font-semibold uppercase tracking-widest text-vs-ink-soft">52W High</span>
                                <span className="text-[13px] font-semibold text-vs-ink">
                                  {fmtRangePx(inst, inst.high_52w ?? inst.week52_high)}
                                </span>
                              </div>

                              {/* 52W Low — backend: `low_52w` */}
                              <div className="flex flex-col gap-0.5">
                                <span className="text-[10px] font-semibold uppercase tracking-widest text-vs-ink-soft">52W Low</span>
                                <span className="text-[13px] font-semibold text-vs-ink">
                                  {fmtRangePx(inst, inst.low_52w ?? inst.week52_low)}
                                </span>
                              </div>

                              {/* Signal label pill — backend: `score_label` */}
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
                                onClick={(e) => handleAddWatchlist(ticker, name, e)}
                                disabled={wlState === "adding"}
                                className={cn(
                                  "flex items-center gap-1.5 px-3.5 py-2 text-[11px] font-semibold uppercase tracking-wider border transition-colors",
                                  wlState === "added"
                                    ? "border-vs-pos text-vs-pos bg-vs-pos/5"
                                    : "border-vs-rule text-vs-ink-mid hover:border-vs-accent hover:text-vs-accent"
                                )}
                              >
                                {wlState === "added"
                                  ? <><BookmarkCheck className="w-3.5 h-3.5" /> Added</>
                                  : <><Bookmark className="w-3.5 h-3.5" /> Watchlist</>
                                }
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
                  </>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
