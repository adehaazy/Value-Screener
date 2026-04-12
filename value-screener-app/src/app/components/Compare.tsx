import { Link } from "react-router";
import { Plus } from "lucide-react";

export default function Compare() {
  return (
    <div className="py-8 lg:py-10 max-w-[1200px] mx-auto">
      {/* ── Header ── */}
      <div className="flex items-end justify-between mb-8">
        <div>
          <h1 className="font-mono text-2xl md:text-[36px] font-medium text-vs-ink tracking-tight leading-tight">
            Compare
          </h1>
          <p className="text-[14px] text-vs-ink-mid mt-1">
            Side-by-side analysis of selected instruments.
          </p>
        </div>
        <button className="flex items-center gap-1.5 bg-vs-accent text-white text-[11px] font-semibold uppercase tracking-widest px-4 py-2.5 hover:bg-vs-accent-dark transition-colors">
          <Plus className="w-4 h-4" />
          Add Ticker
        </button>
      </div>

      {/* ── Empty State ── */}
      <div className="bg-vs-bg-card border border-vs-rule min-h-[400px] flex flex-col items-center justify-center text-center px-6">
        <div className="w-16 h-16 border-2 border-vs-rule rounded-full flex items-center justify-center mb-6">
          <Plus className="w-6 h-6 text-vs-ink-soft" />
        </div>
        <h2 className="font-mono text-xl font-medium text-vs-ink mb-2">
          Nothing to compare yet.
        </h2>
        <p className="text-[13px] text-vs-ink-mid leading-relaxed max-w-md mb-6">
          Add two or more stocks to see scores, valuations and metrics side by side.
        </p>
        <Link
          to="/screener"
          className="text-[11px] font-semibold uppercase tracking-widest border border-vs-ink px-5 py-2.5 hover:bg-vs-ink hover:text-white transition-colors"
        >
          Go to Screener
        </Link>
      </div>
    </div>
  );
}
