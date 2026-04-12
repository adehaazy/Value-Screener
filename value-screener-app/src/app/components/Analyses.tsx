import { useState, useEffect, useCallback } from "react";
import { Link, useNavigate } from "react-router";
import {
  FileText,
  Trash2,
  RefreshCw,
  ExternalLink,
  Loader2,
  AlertCircle,
  Clock,
  ChevronRight,
} from "lucide-react";
import { cn } from "../utils";

// ─── API base ─────────────────────────────────────────────────────────────────
const API_BASE = "https://value-screener.onrender.com";

// ─── Types ────────────────────────────────────────────────────────────────────
interface AnalysisItem {
  ticker: string;
  name: string;
  sector: string | null;
  generated_at: string | null;
  age_days: number | null;
  expires_in: number | null;
  excerpt: string;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso + "Z").toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  } catch {
    return "—";
  }
}

function fmtAge(days: number | null): string {
  if (days == null) return "—";
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  return `${days}d ago`;
}

function expiryColour(expires_in: number | null): string {
  if (expires_in == null) return "text-vs-ink-faint";
  if (expires_in <= 1) return "text-vs-neg";
  if (expires_in <= 3) return "text-yellow-600";
  return "text-vs-ink-faint";
}

// ─── Empty state ──────────────────────────────────────────────────────────────
function EmptyState() {
  return (
    <div className="py-20 flex flex-col items-center gap-4 border border-dashed border-vs-rule">
      <FileText className="w-10 h-10 text-vs-ink-faint" />
      <div className="text-center">
        <p className="text-[14px] font-semibold text-vs-ink-mid mb-1">
          Nothing here yet.
        </p>
        <p className="text-[12px] text-vs-ink-faint">
          Run a{" "}
          <Link to="/deepdive" className="text-vs-accent font-semibold hover:underline">
            Deep Dive
          </Link>{" "}
          on a stock to get started.
        </p>
      </div>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────
export default function Analyses() {
  const navigate = useNavigate();

  const [analyses, setAnalyses] = useState<AnalysisItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Per-ticker action states
  const [deleting, setDeleting] = useState<Set<string>>(new Set());
  const [refreshing, setRefreshing] = useState<Set<string>>(new Set());
  const [refreshError, setRefreshError] = useState<Record<string, string>>({});
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  // ── Fetch analyses list ──────────────────────────────────────────────────
  const fetchAnalyses = useCallback(() => {
    setLoading(true);
    setError(null);
    fetch(`${API_BASE}/api/analyses`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((d) => {
        if (d.ok) setAnalyses(d.analyses || []);
        else setError("Could not load analyses.");
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchAnalyses();
  }, [fetchAnalyses]);

  // ── Delete handler ───────────────────────────────────────────────────────
  const handleDelete = useCallback(
    async (ticker: string) => {
      setDeleteConfirm(null);
      setDeleting((prev) => new Set(prev).add(ticker));
      try {
        const r = await fetch(`${API_BASE}/api/analyses/${encodeURIComponent(ticker)}`, {
          method: "DELETE",
        });
        if (!r.ok) throw new Error(`${r.status}`);
        setAnalyses((prev) => prev.filter((a) => a.ticker !== ticker));
      } catch {
        // silently revert — item stays in list
      } finally {
        setDeleting((prev) => {
          const next = new Set(prev);
          next.delete(ticker);
          return next;
        });
      }
    },
    []
  );

  // ── Refresh handler ──────────────────────────────────────────────────────
  const handleRefresh = useCallback(async (ticker: string) => {
    setRefreshError((prev) => {
      const next = { ...prev };
      delete next[ticker];
      return next;
    });
    setRefreshing((prev) => new Set(prev).add(ticker));
    try {
      const r = await fetch(
        `${API_BASE}/api/analyses/${encodeURIComponent(ticker)}/refresh`,
        { method: "POST" }
      );
      const data = await r.json();
      if (!r.ok) {
        const msg =
          r.status === 429
            ? "Daily limit reached — resets at midnight UTC"
            : data.detail || "Refresh failed";
        setRefreshError((prev) => ({ ...prev, [ticker]: msg }));
        return;
      }
      // Update the item in list with new generated_at / excerpt
      setAnalyses((prev) =>
        prev.map((a) => {
          if (a.ticker !== ticker) return a;
          const newThesis: string = data.thesis || "";
          const firstSentence = newThesis.split(".")[0];
          const excerpt =
            firstSentence.length > 200
              ? firstSentence.slice(0, 200) + "…"
              : firstSentence + ".";
          return {
            ...a,
            generated_at: data.generated_at || new Date().toISOString(),
            age_days: 0,
            expires_in: 7,
            excerpt,
          };
        })
      );
    } catch (e: any) {
      setRefreshError((prev) => ({ ...prev, [ticker]: e.message || "Network error" }));
    } finally {
      setRefreshing((prev) => {
        const next = new Set(prev);
        next.delete(ticker);
        return next;
      });
    }
  }, []);

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <div className="py-8 lg:py-10 max-w-[1000px] mx-auto">
      {/* ── Page header ── */}
      <div className="flex items-end justify-between border-b border-vs-rule pb-5 mb-8">
        <div>
          <h1 className="font-mono text-2xl md:text-[36px] font-medium text-vs-ink tracking-tight leading-tight">
            Saved Analyses
          </h1>
          <p className="text-[13px] text-vs-ink-soft mt-1">
            AI-generated investment theses cached for up to 7 days
          </p>
        </div>
        {!loading && analyses.length > 0 && (
          <span className="text-[11px] font-semibold uppercase tracking-widest text-vs-ink-soft">
            {analyses.length} {analyses.length === 1 ? "analysis" : "analyses"}
          </span>
        )}
      </div>

      {/* ── Loading ── */}
      {loading && (
        <div className="py-20 flex flex-col items-center gap-3">
          <Loader2 className="w-7 h-7 animate-spin text-vs-accent" />
          <p className="text-[13px] text-vs-ink-soft">Loading saved analyses…</p>
        </div>
      )}

      {/* ── Error ── */}
      {error && !loading && (
        <div className="flex items-start gap-3 bg-[#FDECEA] border border-[#F5C6C6] p-4 mb-6">
          <AlertCircle className="w-5 h-5 text-[#B71C1C] shrink-0 mt-0.5" />
          <div>
            <p className="text-[13px] font-bold text-[#B71C1C] mb-1">Could not load analyses</p>
            <p className="text-[12px] text-[#7F1010]">{error}</p>
          </div>
        </div>
      )}

      {/* ── Empty ── */}
      {!loading && !error && analyses.length === 0 && <EmptyState />}

      {/* ── Analyses list ── */}
      {!loading && !error && analyses.length > 0 && (
        <div className="space-y-3">
          {analyses.map((item) => {
            const isDeleting  = deleting.has(item.ticker);
            const isRefreshing = refreshing.has(item.ticker);
            const rErr        = refreshError[item.ticker];
            const isConfirming = deleteConfirm === item.ticker;

            return (
              <div
                key={item.ticker}
                className={cn(
                  "bg-vs-bg-card border border-vs-rule transition-opacity",
                  isDeleting && "opacity-40 pointer-events-none"
                )}
              >
                {/* ── Card header ── */}
                <div className="p-5 flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    {/* Ticker + name */}
                    <div className="flex items-center gap-2 mb-1 flex-wrap">
                      <span className="text-[10px] font-bold uppercase tracking-widest bg-vs-accent text-white px-2 py-0.5">
                        {item.ticker}
                      </span>
                      <h2 className="text-[15px] font-bold text-vs-ink truncate">
                        {item.name}
                      </h2>
                      {item.sector && (
                        <span className="text-[11px] text-vs-ink-soft">· {item.sector}</span>
                      )}
                    </div>

                    {/* Metadata row */}
                    <div className="flex items-center gap-4 flex-wrap mt-1">
                      <span className="flex items-center gap-1 text-[11px] text-vs-ink-soft">
                        <Clock className="w-3 h-3" />
                        Generated {fmtDate(item.generated_at)} · {fmtAge(item.age_days)}
                      </span>
                      <span className={cn("text-[11px]", expiryColour(item.expires_in))}>
                        {item.expires_in != null
                          ? item.expires_in <= 0
                            ? "Expired"
                            : `Expires in ${item.expires_in}d`
                          : ""}
                      </span>
                    </div>

                    {/* Excerpt */}
                    {item.excerpt && (
                      <p className="text-[13px] text-vs-ink-mid leading-relaxed mt-3 line-clamp-2">
                        {item.excerpt}
                      </p>
                    )}

                    {/* Refresh error inline */}
                    {rErr && (
                      <p className="text-[11px] text-vs-neg mt-2 flex items-center gap-1">
                        <AlertCircle className="w-3 h-3 shrink-0" />
                        {rErr}
                      </p>
                    )}
                  </div>

                  {/* ── Action buttons ── */}
                  <div className="flex items-center gap-2 shrink-0 pt-0.5">
                    {/* Refresh */}
                    <button
                      onClick={() => handleRefresh(item.ticker)}
                      disabled={isRefreshing || isDeleting}
                      title="Regenerate thesis"
                      className={cn(
                        "flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider px-3 py-1.5 border transition-colors",
                        isRefreshing
                          ? "border-vs-accent text-vs-accent cursor-not-allowed"
                          : "border-vs-rule text-vs-ink-soft hover:border-vs-accent hover:text-vs-accent"
                      )}
                    >
                      <RefreshCw className={cn("w-3.5 h-3.5", isRefreshing && "animate-spin")} />
                      {isRefreshing ? "Refreshing…" : "Refresh"}
                    </button>

                    {/* View deepdive */}
                    <button
                      onClick={() => navigate(`/deepdive?ticker=${item.ticker}`)}
                      title="Open deep dive"
                      className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider px-3 py-1.5 border border-vs-ink text-vs-ink hover:bg-vs-ink hover:text-white transition-colors"
                    >
                      <ExternalLink className="w-3.5 h-3.5" />
                      View
                    </button>

                    {/* Delete (with confirm) */}
                    {isConfirming ? (
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => handleDelete(item.ticker)}
                          className="text-[11px] font-semibold uppercase tracking-wider px-3 py-1.5 bg-vs-neg text-white border border-vs-neg"
                        >
                          Confirm
                        </button>
                        <button
                          onClick={() => setDeleteConfirm(null)}
                          className="text-[11px] font-semibold uppercase tracking-wider px-3 py-1.5 border border-vs-rule text-vs-ink-soft hover:text-vs-ink"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setDeleteConfirm(item.ticker)}
                        disabled={isDeleting}
                        title="Delete cached thesis"
                        className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider px-3 py-1.5 border border-vs-rule text-vs-ink-soft hover:border-vs-neg hover:text-vs-neg transition-colors"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                        Delete
                      </button>
                    )}
                  </div>
                </div>

                {/* ── Expandable full excerpt row ── */}
                <div
                  className="px-5 pb-4 flex items-center gap-1 cursor-pointer text-[11px] font-semibold uppercase tracking-wider text-vs-ink-soft hover:text-vs-accent transition-colors w-fit"
                  onClick={() => navigate(`/deepdive?ticker=${item.ticker}`)}
                >
                  Open full analysis
                  <ChevronRight className="w-3.5 h-3.5" />
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ── Footer note ── */}
      {!loading && analyses.length > 0 && (
        <p className="text-[11px] text-vs-ink-faint mt-8 text-center">
          Theses are cached server-side for 7 days and generated using AI from publicly available data.
          Refreshing a thesis counts against your daily limit of 5 generations.
        </p>
      )}
    </div>
  );
}
