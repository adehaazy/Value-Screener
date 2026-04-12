import { useState, useEffect, useCallback, useMemo } from "react";
import { useNavigate } from "react-router";
import {
  RefreshCw,
  AlertCircle,
  TrendingUp,
  TrendingDown,
  ExternalLink,
  Loader2,
  Clock,
  Newspaper,
  BarChart2,
  ArrowUpRight,
  ArrowDownRight,
  ChevronDown,
  ChevronUp,
  Activity,
} from "lucide-react";
import { cn } from "../utils";
import { useAppData } from "../useAppData";

// ─── API base ─────────────────────────────────────────────────────────────────
const API_BASE = "https://value-screener.onrender.com";

// ─── Types ────────────────────────────────────────────────────────────────────
interface MacroMetric {
  label: string;
  value: string;
}

interface MacroSection {
  tone: "constructive" | "mixed" | "cautious";
  tone_detail: string;
  metrics: string[];
  warnings: number;
}

interface ScoreSignal {
  ticker: string;
  title: string;
  detail: string;
  drift: number;
  score: number;
  severity: string;
  type: string;
}

interface Opportunity {
  ticker: string;
  name: string;
  score: number;
  label: string;
  group: string;
  verdict: string;
}

interface NewsItem {
  title: string;
  link: string;
  publisher: string;
  pub_time: string | null;
  sentiment?: number;
  source_type: "watchlist" | "market";
  ticker: string | null;
}

interface Briefing {
  headline: string;
  date_str: string;
  generated_at: string;
  macro: MacroSection;
  signal_summary: { total: number; high: number; medium: number; by_type: Record<string, number> };
  signals: ScoreSignal[];
  opportunities: Opportunity[];
  watchlist: any[];
  news_highlights: any[];
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function toneBadge(tone: string) {
  if (tone === "constructive") return { label: "Constructive", cls: "bg-[#D6EDDF] text-[#1E5C38]" };
  if (tone === "cautious")     return { label: "Cautious",     cls: "bg-[#FDECEA] text-[#B71C1C]" };
  return                              { label: "Mixed",        cls: "bg-[#FFF8E1] text-[#A67C00]" };
}

function severityBadge(sev: string) {
  if (sev === "high")   return "bg-[#FDECEA] text-[#B71C1C]";
  if (sev === "medium") return "bg-[#FFF8E1] text-[#A67C00]";
  return "bg-vs-bg-raised text-vs-ink-mid";
}

function fmtAge(hours: number | null): string {
  if (hours == null) return "";
  if (hours < 1)    return "Just updated";
  if (hours < 24)   return `${Math.floor(hours)}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function fmtPubTime(raw: string | null): string {
  if (!raw) return "";
  // Handle Unix timestamp numbers stored as string
  const num = Number(raw);
  if (!isNaN(num) && num > 1e9) {
    return new Date(num * 1000).toLocaleDateString("en-GB", {
      day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
    });
  }
  try {
    return new Date(raw).toLocaleDateString("en-GB", {
      day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
    });
  } catch { return ""; }
}

function sentimentColour(s: number | undefined) {
  if (s == null) return "";
  if (s > 0.3)  return "border-l-[3px] border-[#2E7D52]";
  if (s < -0.3) return "border-l-[3px] border-[#B71C1C]";
  return "";
}

// ─── Collapsible section ──────────────────────────────────────────────────────
function Section({
  icon: Icon,
  title,
  count,
  defaultOpen = true,
  children,
}: {
  icon: any;
  title: string;
  count?: number;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section>
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 border-b-2 border-vs-ink pb-2 mb-5 group"
      >
        <Icon className="w-4 h-4 text-vs-ink shrink-0" />
        <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] text-vs-ink flex-1 text-left">
          {title}
        </h2>
        {count != null && (
          <span className="text-[11px] font-semibold text-vs-ink-soft">{count}</span>
        )}
        {open
          ? <ChevronUp className="w-4 h-4 text-vs-ink-soft group-hover:text-vs-ink transition-colors shrink-0" />
          : <ChevronDown className="w-4 h-4 text-vs-ink-soft group-hover:text-vs-ink transition-colors shrink-0" />
        }
      </button>
      {open && children}
    </section>
  );
}

// ─── Empty / coming soon state ─────────────────────────────────────────────────
function EmptyCard({ message }: { message: string }) {
  return (
    <div className="py-8 text-center border border-dashed border-vs-rule">
      <p className="text-[12px] text-vs-ink-faint">{message}</p>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────
export default function Briefing() {
  const navigate = useNavigate();
  const { watchlist } = useAppData();

  // Derive watchlist tickers
  const watchlistTickers = useMemo(
    () => watchlist.map((w: any) => (w.ticker || w.t || "").toUpperCase()).filter(Boolean),
    [watchlist]
  );

  // Briefing data
  const [briefing, setBriefing]     = useState<Briefing | null>(null);
  const [ageHours, setAgeHours]     = useState<number | null>(null);
  const [stale, setStale]           = useState(false);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  // News data (separate fetch)
  const [watchlistNews, setWatchlistNews] = useState<NewsItem[]>([]);
  const [marketNews, setMarketNews]       = useState<NewsItem[]>([]);
  const [newsLoading, setNewsLoading]     = useState(false);

  // ── Fetch briefing ─────────────────────────────────────────────────────────
  const fetchBriefing = useCallback((data?: any) => {
    if (data) {
      setBriefing(data.briefing);
      setAgeHours(data.age_hours ?? 0);
      setStale(data.stale ?? false);
      return;
    }
    setLoading(true);
    setError(null);
    fetch(`${API_BASE}/api/briefing`)
      .then((r) => { if (!r.ok) throw new Error(`${r.status}`); return r.json(); })
      .then((d) => {
        if (d.ok && d.briefing) {
          setBriefing(d.briefing);
          setAgeHours(d.age_hours ?? null);
          setStale(d.stale ?? false);
        } else {
          setError(d.message || "No briefing available yet.");
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetchBriefing(); }, [fetchBriefing]);

  // ── Fetch news (once briefing loads and we have watchlist tickers) ─────────
  const fetchNews = useCallback((tickers: string[]) => {
    setNewsLoading(true);
    const qs = tickers.length ? `?tickers=${tickers.map(encodeURIComponent).join(",")}` : "";
    fetch(`${API_BASE}/api/briefing/news${qs}`)
      .then((r) => r.json())
      .then((d) => {
        if (d.ok) {
          setWatchlistNews(d.watchlist_news || []);
          setMarketNews(d.market_news || []);
        }
      })
      .catch(() => {})
      .finally(() => setNewsLoading(false));
  }, []);

  // Trigger news fetch once briefing is loaded
  useEffect(() => {
    if (!loading && (briefing || error)) {
      fetchNews(watchlistTickers);
    }
  }, [loading, briefing, error, watchlistTickers, fetchNews]);

  // ── Refresh handler ────────────────────────────────────────────────────────
  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const r = await fetch(`${API_BASE}/api/briefing/refresh`, { method: "POST" });
      const d = await r.json();
      if (d.ok && d.briefing) {
        fetchBriefing(d);
        fetchNews(watchlistTickers);
      }
    } catch { /* silent */ }
    finally { setRefreshing(false); }
  }, [fetchBriefing, fetchNews, watchlistTickers]);

  // ── Derive score drift signals from signals array ─────────────────────────
  const scoreDriftSignals = useMemo(() => {
    if (!briefing?.signals) return [];
    return briefing.signals
      .filter((s: any) => s.type === "score_drift")
      .sort((a: any, b: any) => Math.abs(b.drift ?? 0) - Math.abs(a.drift ?? 0));
  }, [briefing]);

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="py-8 lg:py-10 max-w-[1000px] mx-auto">

      {/* ── Page header ── */}
      <div className="flex items-start justify-between border-b border-vs-rule pb-5 mb-8">
        <div>
          <h1 className="font-mono text-2xl md:text-[36px] font-medium text-vs-ink tracking-tight leading-tight">
            Market Briefing
          </h1>
          {briefing?.date_str && (
            <p className="text-[12px] text-vs-ink-soft mt-1 flex items-center gap-1.5">
              <Clock className="w-3.5 h-3.5" />
              {briefing.date_str}
              {ageHours != null && (
                <span className="text-vs-ink-faint">· {fmtAge(ageHours)}</span>
              )}
            </p>
          )}
        </div>

        <button
          onClick={handleRefresh}
          disabled={refreshing || loading}
          className={cn(
            "flex items-center gap-2 text-[11px] font-semibold uppercase tracking-widest px-4 py-2 border transition-colors mt-1",
            refreshing
              ? "border-vs-accent text-vs-accent cursor-not-allowed"
              : "border-vs-rule text-vs-ink-soft hover:border-vs-accent hover:text-vs-accent"
          )}
        >
          <RefreshCw className={cn("w-3.5 h-3.5", refreshing && "animate-spin")} />
          {refreshing ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {/* ── Stale warning ── */}
      {stale && !loading && briefing && (
        <div className="flex items-start gap-3 bg-[#FFF8E1] border border-[#FFD54F] p-3 mb-6">
          <AlertCircle className="w-4 h-4 text-[#A67C00] shrink-0 mt-0.5" />
          <p className="text-[12px] text-[#7A5800]">
            Briefing is {ageHours != null ? `${Math.floor(ageHours)} hours` : "more than 4 hours"} old.
            Hit Refresh to pull the latest macro data and news.
          </p>
        </div>
      )}

      {/* ── Loading ── */}
      {loading && (
        <div className="py-20 flex flex-col items-center gap-3">
          <Loader2 className="w-7 h-7 animate-spin text-vs-accent" />
          <p className="text-[13px] text-vs-ink-soft">Loading briefing…</p>
        </div>
      )}

      {/* ── No briefing yet ── */}
      {!loading && error && (
        <div className="flex items-start gap-3 bg-[#FDECEA] border border-[#F5C6C6] p-4 mb-6">
          <AlertCircle className="w-5 h-5 text-[#B71C1C] shrink-0 mt-0.5" />
          <div>
            <p className="text-[13px] font-bold text-[#B71C1C] mb-1">Briefing unavailable</p>
            <p className="text-[12px] text-[#7F1010]">{error}</p>
            <button
              onClick={handleRefresh}
              disabled={refreshing}
              className="mt-3 text-[11px] font-semibold uppercase tracking-wider text-[#B71C1C] underline"
            >
              {refreshing ? "Generating…" : "Generate now"}
            </button>
          </div>
        </div>
      )}

      {/* ── Main content (when briefing exists) ── */}
      {!loading && briefing && (
        <div className="space-y-10">

          {/* ══ 1. MACRO SNAPSHOT ══════════════════════════════════════════ */}
          <Section icon={Activity} title="Macro Snapshot">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
              {/* Tone card */}
              <div className="md:col-span-1 bg-vs-bg-card border border-vs-rule p-5 flex flex-col gap-3">
                <p className="text-[10px] font-bold uppercase tracking-[0.1em] text-vs-ink-soft">
                  Overall Tone
                </p>
                {(() => {
                  const tb = toneBadge(briefing.macro?.tone ?? "mixed");
                  return (
                    <>
                      <span className={cn("text-[11px] font-bold px-3 py-1.5 inline-block w-fit", tb.cls)}>
                        {tb.label}
                      </span>
                      <p className="text-[12px] text-vs-ink-mid leading-relaxed">
                        {briefing.macro?.tone_detail}
                      </p>
                      {(briefing.macro?.warnings ?? 0) > 0 && (
                        <p className="text-[11px] text-vs-neg font-semibold">
                          {briefing.macro.warnings} stress signal{briefing.macro.warnings > 1 ? "s" : ""} active
                        </p>
                      )}
                    </>
                  );
                })()}
              </div>

              {/* Metrics grid */}
              <div className="md:col-span-2 grid grid-cols-2 gap-[1px] bg-vs-rule">
                {(briefing.macro?.metrics ?? []).map((line: string, i: number) => {
                  const [label, ...rest] = line.split(":");
                  const value = rest.join(":").trim();
                  return (
                    <div key={i} className="bg-vs-bg-card px-4 py-3">
                      <p className="text-[10px] font-bold uppercase tracking-[0.08em] text-vs-ink-soft mb-0.5">
                        {label.trim()}
                      </p>
                      <p className="text-[13px] font-semibold text-vs-ink">{value || "—"}</p>
                    </div>
                  );
                })}
                {(briefing.macro?.metrics ?? []).length === 0 && (
                  <div className="col-span-2 bg-vs-bg-card px-4 py-6 text-center">
                    <p className="text-[12px] text-vs-ink-faint">Macro data unavailable — run a surveillance scan.</p>
                  </div>
                )}
              </div>
            </div>
          </Section>

          {/* ══ 2. SCORE CHANGES ═══════════════════════════════════════════ */}
          <Section
            icon={BarChart2}
            title="Score Changes"
            count={scoreDriftSignals.length > 0 ? scoreDriftSignals.length : undefined}
            defaultOpen={true}
          >
            {scoreDriftSignals.length === 0 ? (
              <EmptyCard message="No score changes since the last scan. Scores update when surveillance runs." />
            ) : (
              <div className="bg-vs-bg-card border border-vs-rule divide-y divide-vs-rule">
                {scoreDriftSignals.map((sig: any, i: number) => {
                  const up = (sig.drift ?? 0) > 0;
                  const prevScore = sig.score - sig.drift;
                  return (
                    <div
                      key={sig.ticker || i}
                      className="flex items-center gap-4 px-5 py-3.5 hover:bg-vs-bg-raised cursor-pointer transition-colors"
                      onClick={() => navigate(`/deepdive?ticker=${sig.ticker}`)}
                    >
                      {/* Direction icon */}
                      <div className={cn(
                        "w-7 h-7 flex items-center justify-center shrink-0",
                        up ? "text-vs-pos" : "text-vs-neg"
                      )}>
                        {up
                          ? <ArrowUpRight className="w-5 h-5" />
                          : <ArrowDownRight className="w-5 h-5" />
                        }
                      </div>

                      {/* Ticker + detail */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-[10px] font-bold uppercase tracking-widest bg-vs-accent text-white px-2 py-0.5">
                            {sig.ticker}
                          </span>
                          <p className="text-[13px] font-semibold text-vs-ink truncate">
                            {sig.detail?.split("(")[0]?.trim() || sig.ticker}
                          </p>
                        </div>
                        <p className="text-[11px] text-vs-ink-soft mt-0.5">{sig.detail}</p>
                      </div>

                      {/* Score change */}
                      <div className="text-right shrink-0">
                        <p className="text-[13px] font-bold text-vs-ink">
                          {Math.round(prevScore)}
                          <span className="text-vs-ink-faint mx-1">→</span>
                          <span className={up ? "text-vs-pos" : "text-vs-neg"}>
                            {Math.round(sig.score)}
                          </span>
                        </p>
                        <span className={cn(
                          "text-[10px] font-bold px-2 py-0.5 inline-block mt-0.5",
                          severityBadge(sig.severity)
                        )}>
                          {(sig.drift > 0 ? "+" : "") + Math.round(sig.drift)} pts
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </Section>

          {/* ══ 3. WATCHLIST NEWS ══════════════════════════════════════════ */}
          <Section
            icon={Newspaper}
            title="Watchlist News"
            count={watchlistNews.length > 0 ? watchlistNews.length : undefined}
            defaultOpen={true}
          >
            {newsLoading ? (
              <div className="py-10 flex items-center justify-center gap-2">
                <Loader2 className="w-5 h-5 animate-spin text-vs-accent" />
                <p className="text-[12px] text-vs-ink-soft">Fetching news…</p>
              </div>
            ) : watchlistTickers.length === 0 ? (
              <EmptyCard message="Add stocks to your watchlist to see news here." />
            ) : watchlistNews.length === 0 ? (
              <EmptyCard message="No recent news for your watchlist. Check back later." />
            ) : (
              <div className="space-y-1">
                {/* Group by ticker */}
                {watchlistTickers
                  .filter((t) => watchlistNews.some((n) => n.ticker === t))
                  .map((ticker) => {
                    const items = watchlistNews.filter((n) => n.ticker === ticker);
                    const wlInst = (briefing.watchlist || []).find((w: any) => w.ticker === ticker);
                    return (
                      <div key={ticker} className="bg-vs-bg-card border border-vs-rule mb-3">
                        {/* Ticker header */}
                        <div
                          className="flex items-center gap-3 px-5 py-3 border-b border-vs-rule cursor-pointer hover:bg-vs-bg-raised"
                          onClick={() => navigate(`/deepdive?ticker=${ticker}`)}
                        >
                          <span className="text-[10px] font-bold uppercase tracking-widest bg-vs-accent text-white px-2 py-0.5">
                            {ticker}
                          </span>
                          {wlInst?.name && (
                            <span className="text-[12px] font-semibold text-vs-ink">{wlInst.name}</span>
                          )}
                          {wlInst?.score != null && (
                            <span className="ml-auto text-[11px] text-vs-ink-soft">
                              Score: <strong>{Math.round(wlInst.score)}</strong>
                            </span>
                          )}
                        </div>
                        {/* Headlines */}
                        <div className="divide-y divide-vs-rule">
                          {items.slice(0, 5).map((item, i) => (
                            <a
                              key={i}
                              href={item.link || "#"}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="flex items-start justify-between gap-4 px-5 py-3.5 hover:bg-vs-bg-raised transition-colors group"
                            >
                              <div className="flex-1 min-w-0">
                                <p className="text-[13px] text-vs-ink font-medium group-hover:text-vs-accent transition-colors leading-snug">
                                  {item.title}
                                </p>
                                <p className="text-[11px] text-vs-ink-faint mt-1">
                                  {item.publisher}
                                  {item.pub_time && ` · ${fmtPubTime(item.pub_time)}`}
                                </p>
                              </div>
                              {item.link && (
                                <ExternalLink className="w-3.5 h-3.5 text-vs-ink-faint shrink-0 mt-0.5 opacity-0 group-hover:opacity-100 transition-opacity" />
                              )}
                            </a>
                          ))}
                        </div>
                      </div>
                    );
                  })}
              </div>
            )}
          </Section>

          {/* ══ 4. MARKET HEADLINES ═══════════════════════════════════════ */}
          <Section
            icon={TrendingUp}
            title="Market Headlines"
            count={marketNews.length > 0 ? marketNews.length : undefined}
            defaultOpen={true}
          >
            {newsLoading ? (
              <div className="py-10 flex items-center justify-center gap-2">
                <Loader2 className="w-5 h-5 animate-spin text-vs-accent" />
                <p className="text-[12px] text-vs-ink-soft">Fetching headlines…</p>
              </div>
            ) : marketNews.length === 0 ? (
              <EmptyCard message="No market headlines yet. They'll appear on the next refresh." />
            ) : (
              <div className="bg-vs-bg-card border border-vs-rule divide-y divide-vs-rule">
                {marketNews.slice(0, 15).map((item, i) => (
                  <a
                    key={i}
                    href={item.link || "#"}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={cn(
                      "flex items-start justify-between gap-4 px-5 py-4 hover:bg-vs-bg-raised transition-colors group",
                      sentimentColour(item.sentiment)
                    )}
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1 flex-wrap">
                        <span className="text-[10px] font-semibold uppercase tracking-wider text-vs-ink-soft border border-vs-rule px-1.5 py-0.5">
                          {item.publisher}
                        </span>
                        {item.sentiment != null && Math.abs(item.sentiment) > 0.3 && (
                          <span className={cn(
                            "flex items-center gap-0.5 text-[10px] font-semibold",
                            item.sentiment > 0 ? "text-vs-pos" : "text-vs-neg"
                          )}>
                            {item.sentiment > 0
                              ? <TrendingUp className="w-3 h-3" />
                              : <TrendingDown className="w-3 h-3" />
                            }
                            {item.sentiment > 0 ? "Positive" : "Negative"}
                          </span>
                        )}
                      </div>
                      <p className="text-[13px] text-vs-ink font-medium group-hover:text-vs-accent transition-colors leading-snug">
                        {item.title}
                      </p>
                      {item.pub_time && (
                        <p className="text-[11px] text-vs-ink-faint mt-1">{fmtPubTime(item.pub_time)}</p>
                      )}
                    </div>
                    {item.link && (
                      <ExternalLink className="w-3.5 h-3.5 text-vs-ink-faint shrink-0 mt-1 opacity-0 group-hover:opacity-100 transition-opacity" />
                    )}
                  </a>
                ))}
              </div>
            )}
          </Section>

        </div>
      )}
    </div>
  );
}
