import { useState, useCallback } from "react";
import { Settings as SettingsIcon, Save, RotateCcw, Info, AlertTriangle, CheckCircle } from "lucide-react";
import { cn } from "../utils";
import { API_BASE } from "../../api/client";

/* ================================================================
   Types & Defaults — mirror scoring.py exactly
   ================================================================ */
interface Weights {
  // Non-financial stocks
  wt_evebitda:  number;
  wt_roic:      number;
  wt_pfcf:      number;
  wt_pe:        number;
  wt_pb:        number;
  wt_52w:       number;
  wt_divyield:  number;
  // Financial stocks
  wt_fin_ptb:   number;
  wt_fin_roe:   number;
  wt_fin_yield: number;
  wt_fin_52w:   number;
}

interface Thresholds {
  min_roe:            number;
  max_de:             number;
  min_profit_margin:  number;
  require_pos_fcf:    boolean;
  fin_min_roe:        number;
  fin_max_price_book: number;
}

const DEFAULT_WEIGHTS: Weights = {
  wt_evebitda:  25,
  wt_roic:      20,
  wt_pfcf:      20,
  wt_pe:        12,
  wt_pb:         8,
  wt_52w:        8,
  wt_divyield:   7,
  wt_fin_ptb:   35,
  wt_fin_roe:   30,
  wt_fin_yield: 20,
  wt_fin_52w:   15,
};

const DEFAULT_THRESHOLDS: Thresholds = {
  min_roe:            8,
  max_de:             3,
  min_profit_margin:  2,
  require_pos_fcf:    true,
  fin_min_roe:        6,
  fin_max_price_book: 2.0,
};

/* ================================================================
   Sub-components
   ================================================================ */

/** A single weight row: label | info | range slider | live % */
function WeightSlider({
  label,
  description,
  value,
  onChange,
}: {
  label: string;
  description: string;
  value: number;
  onChange: (v: number) => void;
}) {
  const [showTip, setShowTip] = useState(false);

  return (
    <div className="flex items-center gap-4 group">
      {/* Label + tooltip */}
      <div className="w-44 shrink-0 flex items-center gap-1.5">
        <span className="text-[13px] font-semibold text-vs-ink">{label}</span>
        <button
          type="button"
          className="relative"
          onMouseEnter={() => setShowTip(true)}
          onMouseLeave={() => setShowTip(false)}
          onFocus={() => setShowTip(true)}
          onBlur={() => setShowTip(false)}
        >
          <Info className="w-3 h-3 text-vs-ink-faint hover:text-vs-ink-soft transition-colors" />
          {showTip && (
            <div className="absolute left-5 top-0 z-20 w-52 bg-vs-ink text-white text-[11px] leading-relaxed px-3 py-2 pointer-events-none">
              {description}
            </div>
          )}
        </button>
      </div>

      {/* Slider */}
      <div className="flex-1 relative">
        {/* Track background */}
        <div className="absolute top-1/2 -translate-y-1/2 w-full h-1 bg-vs-bg-subtle" />
        {/* Filled portion */}
        <div
          className="absolute top-1/2 -translate-y-1/2 h-1 bg-vs-accent transition-all"
          style={{ width: `${value}%` }}
        />
        <input
          type="range"
          min={0}
          max={60}
          step={1}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="relative w-full h-4 appearance-none bg-transparent cursor-pointer
            [&::-webkit-slider-thumb]:appearance-none
            [&::-webkit-slider-thumb]:w-4
            [&::-webkit-slider-thumb]:h-4
            [&::-webkit-slider-thumb]:bg-vs-accent
            [&::-webkit-slider-thumb]:border-2
            [&::-webkit-slider-thumb]:border-white
            [&::-webkit-slider-thumb]:shadow-[0_0_0_1px_var(--color-vs-accent)]
            [&::-webkit-slider-thumb]:rounded-full
            [&::-webkit-slider-thumb]:transition-transform
            [&::-webkit-slider-thumb]:hover:scale-110
            [&::-moz-range-thumb]:w-4
            [&::-moz-range-thumb]:h-4
            [&::-moz-range-thumb]:bg-vs-accent
            [&::-moz-range-thumb]:border-2
            [&::-moz-range-thumb]:border-white
            [&::-moz-range-thumb]:rounded-full"
        />
      </div>

      {/* Live readout */}
      <span className="w-11 text-right text-[14px] font-bold text-vs-ink shrink-0 tabular-nums">
        {value}%
      </span>
    </div>
  );
}

/** Sum badge — turns red if ≠ target, green if equal */
function SumBadge({ sum, target = 100 }: { sum: number; target?: number }) {
  const ok = sum === target;
  return (
    <div className="flex flex-col items-end">
      <div
        className={cn(
          "flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-widest px-3 py-1 border transition-colors",
          ok
            ? "text-vs-pos border-vs-pos bg-vs-pos-bg"
            : "text-vs-neg border-vs-neg bg-vs-neg-bg"
        )}
      >
        {ok ? (
          <CheckCircle className="w-3 h-3" />
        ) : (
          <AlertTriangle className="w-3 h-3" />
        )}
        Sum: {sum}%
      </div>
      {sum !== target && (
        <span className="text-[10px] text-vs-neg mt-0.5">
          Adjust by {sum > target ? `-${sum - target}` : `+${target - sum}`}% to enable Save
        </span>
      )}
    </div>
  );
}

/** Panel wrapper — section label + sum badge + children */
function WeightPanel({
  title,
  sum,
  children,
}: {
  title: string;
  sum: number;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-vs-bg-card border border-vs-rule p-6 mb-6">
      <div className="flex items-center justify-between border-b border-vs-rule pb-3 mb-6">
        <p className="text-[10px] font-bold uppercase tracking-[0.1em] text-vs-accent">
          {title}
        </p>
        <SumBadge sum={sum} />
      </div>
      <div className="space-y-5">{children}</div>
    </div>
  );
}

/** Threshold numeric input row */
function ThresholdInput({
  label,
  description,
  value,
  unit,
  step,
  min,
  max,
  onChange,
}: {
  label: string;
  description: string;
  value: number;
  unit: string;
  step: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="flex items-center justify-between py-3 border-b border-vs-rule last:border-0">
      <div className="flex-1 min-w-0 pr-6">
        <p className="text-[13px] font-semibold text-vs-ink">{label}</p>
        <p className="text-[11px] text-vs-ink-soft mt-0.5">{description}</p>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <input
          type="number"
          value={value}
          step={step}
          min={min}
          max={max}
          onChange={(e) => {
            const v = parseFloat(e.target.value);
            if (!isNaN(v)) onChange(v);
          }}
          className="w-20 text-right bg-vs-bg-card border border-vs-rule px-2.5 py-1.5
            text-[13px] font-bold text-vs-ink outline-none focus:border-vs-accent
            [appearance:textfield]
            [&::-webkit-outer-spin-button]:appearance-none
            [&::-webkit-inner-spin-button]:appearance-none"
        />
        <span className="text-[12px] text-vs-ink-soft w-8">{unit}</span>
      </div>
    </div>
  );
}

/** FCF toggle */
function Toggle({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between py-3 border-b border-vs-rule last:border-0">
      <div className="flex-1 min-w-0 pr-6">
        <p className="text-[13px] font-semibold text-vs-ink">{label}</p>
        <p className="text-[11px] text-vs-ink-soft mt-0.5">{description}</p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cn(
          "relative w-10 h-5 shrink-0 border transition-colors duration-200",
          checked ? "bg-vs-accent border-vs-accent" : "bg-vs-bg-subtle border-vs-rule"
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 w-4 h-4 bg-white border transition-all duration-200",
            checked ? "left-5 border-vs-accent-dark" : "left-0.5 border-vs-rule"
          )}
        />
      </button>
    </div>
  );
}

/* ================================================================
   Main Settings component
   ================================================================ */
interface GlobalFilters {
  min_market_cap: string;
  sector: string;
  min_div_yield: string;
}

const DEFAULT_FILTERS: GlobalFilters = {
  min_market_cap: "Any",
  sector:         "All Sectors",
  min_div_yield:  "Any",
};

export default function Settings() {
  const [weights, setWeights] = useState<Weights>({ ...DEFAULT_WEIGHTS });
  const [thresholds, setThresholds] = useState<Thresholds>({ ...DEFAULT_THRESHOLDS });
  const [filters, setFilters] = useState<GlobalFilters>({ ...DEFAULT_FILTERS });
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedOk, setSavedOk] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [resetConfirm, setResetConfirm] = useState(false);

  /* ── Weight helpers ── */
  const setWeight = useCallback(
    (key: keyof Weights, val: number) => {
      setWeights((w) => ({ ...w, [key]: val }));
      setDirty(true);
      setSavedOk(false);
    },
    []
  );

  const setThreshold = useCallback(
    (key: keyof Thresholds, val: number | boolean) => {
      setThresholds((t) => ({ ...t, [key]: val }));
      setDirty(true);
      setSavedOk(false);
    },
    []
  );

  const setFilter = useCallback(
    (key: keyof GlobalFilters, val: string) => {
      setFilters((f) => ({ ...f, [key]: val }));
      setDirty(true);
      setSavedOk(false);
    },
    []
  );

  /* ── Sum validation ── */
  const nonFinSum =
    weights.wt_evebitda +
    weights.wt_roic +
    weights.wt_pfcf +
    weights.wt_pe +
    weights.wt_pb +
    weights.wt_52w +
    weights.wt_divyield;

  const finSum =
    weights.wt_fin_ptb +
    weights.wt_fin_roe +
    weights.wt_fin_yield +
    weights.wt_fin_52w;

  const canSave = nonFinSum === 100 && finSum === 100 && dirty;

  /* ── Save ── */
  async function handleSave() {
    if (!canSave) return;
    setSaving(true);
    try {
      await fetch(`${API_BASE}/api/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ weights, thresholds, filters }),
      });
      setSavedOk(true);
      setDirty(false);
      setTimeout(() => setSavedOk(false), 2500);
    } catch {
      setSaveError("Could not reach server — settings saved locally only.");
      setTimeout(() => setSaveError(null), 3500);
    } finally {
      setSaving(false);
    }
  }

  /* ── Reset ── */
  function handleReset() {
    if (!resetConfirm) {
      setResetConfirm(true);
      setTimeout(() => setResetConfirm(false), 3000);
      return;
    }
    setWeights({ ...DEFAULT_WEIGHTS });
    setThresholds({ ...DEFAULT_THRESHOLDS });
    setFilters({ ...DEFAULT_FILTERS });
    setDirty(false);
    setSavedOk(false);
    setResetConfirm(false);
  }

  return (
    <div className="py-8 lg:py-10 max-w-[800px] mx-auto">

      {/* ── Header ── */}
      <div className="flex items-center gap-3 mb-1">
        <SettingsIcon className="w-8 h-8 text-vs-ink" strokeWidth={1.5} />
        <h1 className="font-mono text-2xl md:text-[36px] font-medium text-vs-ink tracking-tight leading-tight">
          Settings
        </h1>
      </div>
      <p className="text-[13px] text-vs-ink-mid mb-8">
        Adjust scoring weights and quality thresholds. Weights must sum to 100% per track to save.
      </p>

      {/* ══════════════════════════════════════════════
          PANEL 1 — Non-Financial Stock Weights
      ══════════════════════════════════════════════ */}
      <WeightPanel title="Stock Scoring Weights (Non-Financials)" sum={nonFinSum}>
        <WeightSlider
          label="EV/EBITDA"
          description="Enterprise value vs earnings before interest, tax, depreciation. Best single measure of sector-relative cheapness."
          value={weights.wt_evebitda}
          onChange={(v) => setWeight("wt_evebitda", v)}
        />
        <WeightSlider
          label="ROIC"
          description="Return on invested capital — measures how efficiently management deploys capital. New in scoring v2."
          value={weights.wt_roic}
          onChange={(v) => setWeight("wt_roic", v)}
        />
        <WeightSlider
          label="P/FCF"
          description="Price to free cash flow. Rewards real cash generation and is harder to manipulate than earnings."
          value={weights.wt_pfcf}
          onChange={(v) => setWeight("wt_pfcf", v)}
        />
        <WeightSlider
          label="P/E Ratio"
          description="Price to earnings. Widely understood but noisy — subject to accounting choices. Lower weight in v2."
          value={weights.wt_pe}
          onChange={(v) => setWeight("wt_pe", v)}
        />
        <WeightSlider
          label="P/Book"
          description="Sector-relative price to book value. Useful as an asset backing floor and mean-reversion check."
          value={weights.wt_pb}
          onChange={(v) => setWeight("wt_pb", v)}
        />
        <WeightSlider
          label="Momentum"
          description="6–12 month price momentum. Acts as a trend confirmation — avoids catching falling knives."
          value={weights.wt_52w}
          onChange={(v) => setWeight("wt_52w", v)}
        />
        <WeightSlider
          label="Dividend Yield"
          description="Income signal and management confidence indicator. Less weight than before in favour of ROIC."
          value={weights.wt_divyield}
          onChange={(v) => setWeight("wt_divyield", v)}
        />

        {/* Helper text */}
        {nonFinSum !== 100 && (
          <p className="text-[11px] text-vs-neg font-semibold pt-2">
            Adjust weights so they total exactly 100% to enable saving.
            Currently {nonFinSum > 100 ? `${nonFinSum - 100}% over` : `${100 - nonFinSum}% under`}.
          </p>
        )}
      </WeightPanel>

      {/* ══════════════════════════════════════════════
          PANEL 2 — Financial Stock Weights
      ══════════════════════════════════════════════ */}
      <WeightPanel title="Stock Scoring Weights (Financials)" sum={finSum}>
        <p className="text-[11px] text-vs-ink-soft -mt-2 mb-2">
          Applies to banks, insurers, asset managers. Uses P/Tangible Book and ROE instead of EV/EBITDA.
        </p>
        <WeightSlider
          label="P/Tangible Book"
          description="Primary valuation anchor for banks and insurers. Above 2x tangible book is rarely deep value."
          value={weights.wt_fin_ptb}
          onChange={(v) => setWeight("wt_fin_ptb", v)}
        />
        <WeightSlider
          label="ROE vs Sector"
          description="Return on equity measured against sector median — rewards quality at a reasonable price."
          value={weights.wt_fin_roe}
          onChange={(v) => setWeight("wt_fin_roe", v)}
        />
        <WeightSlider
          label="Dividend Yield"
          description="Especially meaningful for banks and insurers where dividend consistency signals financial health."
          value={weights.wt_fin_yield}
          onChange={(v) => setWeight("wt_fin_yield", v)}
        />
        <WeightSlider
          label="Momentum"
          description="12-month price momentum as a contrarian and trend confirmation signal."
          value={weights.wt_fin_52w}
          onChange={(v) => setWeight("wt_fin_52w", v)}
        />

        {finSum !== 100 && (
          <p className="text-[11px] text-vs-neg font-semibold pt-2">
            Adjust weights so they total exactly 100% to enable saving.
            Currently {finSum > 100 ? `${finSum - 100}% over` : `${100 - finSum}% under`}.
          </p>
        )}
      </WeightPanel>

      {/* ══════════════════════════════════════════════
          PANEL 3 — Quality Gate Thresholds
      ══════════════════════════════════════════════ */}
      <div className="bg-vs-bg-card border border-vs-rule p-6 mb-6">
        <div className="border-b border-vs-rule pb-3 mb-2">
          <p className="text-[10px] font-bold uppercase tracking-[0.1em] text-vs-accent">
            Quality Gate Thresholds
          </p>
        </div>

        {/* Non-financial */}
        <p className="text-[10px] font-bold uppercase tracking-[0.08em] text-vs-ink-soft mt-4 mb-1">
          Non-Financial Stocks
        </p>
        <div>
          <ThresholdInput
            label="Minimum ROE"
            description="Stocks below this return on equity fail the quality gate"
            value={thresholds.min_roe}
            unit="%"
            step={0.5}
            min={0}
            max={25}
            onChange={(v) => setThreshold("min_roe", v)}
          />
          <ThresholdInput
            label="Maximum D/E Ratio"
            description="Stocks above this debt-to-equity ratio are excluded"
            value={thresholds.max_de}
            unit="×"
            step={0.1}
            min={0}
            max={10}
            onChange={(v) => setThreshold("max_de", v)}
          />
          <ThresholdInput
            label="Minimum Profit Margin"
            description="Minimum net profit margin required to pass"
            value={thresholds.min_profit_margin}
            unit="%"
            step={0.5}
            min={0}
            max={20}
            onChange={(v) => setThreshold("min_profit_margin", v)}
          />
          <Toggle
            label="Require Positive FCF"
            description="Exclude stocks with negative free cash flow in the trailing 12 months"
            checked={thresholds.require_pos_fcf}
            onChange={(v) => setThreshold("require_pos_fcf", v)}
          />
        </div>

        {/* Financial */}
        <p className="text-[10px] font-bold uppercase tracking-[0.08em] text-vs-ink-soft mt-6 mb-1">
          Financial Stocks
        </p>
        <div>
          <ThresholdInput
            label="Minimum ROE"
            description="Banks typically earn less — a lower bar is appropriate"
            value={thresholds.fin_min_roe}
            unit="%"
            step={0.5}
            min={0}
            max={20}
            onChange={(v) => setThreshold("fin_min_roe", v)}
          />
          <ThresholdInput
            label="Max P/Tangible Book"
            description="Above 2× tangible book value is rarely deep value for financials"
            value={thresholds.fin_max_price_book}
            unit="×"
            step={0.1}
            min={0}
            max={5}
            onChange={(v) => setThreshold("fin_max_price_book", v)}
          />
        </div>
      </div>

      {/* ══════════════════════════════════════════════
          PANEL 4 — Global Screener Filters
      ══════════════════════════════════════════════ */}
      <div className="bg-vs-bg-card border border-vs-rule p-6 mb-8">
        <p className="text-[10px] font-bold uppercase tracking-[0.1em] text-vs-accent border-b border-vs-rule pb-3 mb-6">
          Global Screener Filters
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <label className="block text-[13px] font-semibold text-vs-ink mb-2">
              Market Cap Minimum
            </label>
            <select
              value={filters.min_market_cap}
              onChange={(e) => setFilter("min_market_cap", e.target.value)}
              className="w-full bg-vs-bg-card border border-vs-rule p-2.5 text-[13px] outline-none focus:border-vs-accent"
            >
              <option>Any</option>
              <option>£100M+</option>
              <option>£500M+</option>
              <option>£1B+</option>
              <option>£10B+</option>
            </select>
          </div>
          <div>
            <label className="block text-[13px] font-semibold text-vs-ink mb-2">
              Sectors
            </label>
            <select
              value={filters.sector}
              onChange={(e) => setFilter("sector", e.target.value)}
              className="w-full bg-vs-bg-card border border-vs-rule p-2.5 text-[13px] outline-none focus:border-vs-accent"
            >
              <option>All Sectors</option>
              <option>Technology</option>
              <option>Financials</option>
              <option>Healthcare</option>
              <option>Energy</option>
              <option>Consumer Staples</option>
            </select>
          </div>
          <div>
            <label className="block text-[13px] font-semibold text-vs-ink mb-2">
              Dividend Yield Minimum
            </label>
            <select
              value={filters.min_div_yield}
              onChange={(e) => setFilter("min_div_yield", e.target.value)}
              className="w-full bg-vs-bg-card border border-vs-rule p-2.5 text-[13px] outline-none focus:border-vs-accent"
            >
              <option>Any</option>
              <option>1%+</option>
              <option>2%+</option>
              <option>3%+</option>
              <option>5%+</option>
            </select>
          </div>
        </div>
      </div>

      {/* ── Save error banner ── */}
      {saveError && (
        <div className="flex items-center gap-2 bg-[#FDECEA] border border-[#F5C6C6] px-4 py-3 mb-4">
          <AlertTriangle className="w-4 h-4 text-[#B71C1C] shrink-0" />
          <p className="text-[12px] text-[#B71C1C]">{saveError}</p>
        </div>
      )}

      {/* ── Action Row ── */}
      <div className="flex items-center justify-between">
        {/* Dirty indicator */}
        <p className={cn(
          "text-[11px] font-semibold transition-opacity",
          dirty ? "text-vs-ink-soft opacity-100" : "opacity-0"
        )}>
          Unsaved changes
        </p>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={handleReset}
            className={cn(
              "flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-widest border px-5 py-2.5 transition-colors",
              resetConfirm
                ? "border-vs-neg text-vs-neg hover:bg-vs-neg hover:text-white"
                : "border-vs-rule text-vs-ink-mid hover:border-vs-ink hover:text-vs-ink"
            )}
          >
            <RotateCcw className="w-3.5 h-3.5" />
            {resetConfirm ? "Confirm Reset" : "Reset Defaults"}
          </button>

          <button
            type="button"
            onClick={handleSave}
            disabled={!canSave || saving}
            className={cn(
              "flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-widest px-5 py-2.5 transition-colors",
              savedOk
                ? "bg-vs-pos text-white border border-vs-pos"
                : canSave
                  ? "bg-vs-accent text-white hover:bg-vs-accent-dark"
                  : "bg-vs-bg-subtle text-vs-ink-faint border border-vs-rule cursor-not-allowed"
            )}
          >
            {savedOk ? (
              <>
                <CheckCircle className="w-4 h-4" />
                Saved
              </>
            ) : saving ? (
              <>
                <Save className="w-4 h-4 animate-pulse" />
                Saving…
              </>
            ) : (
              <>
                <Save className="w-4 h-4" />
                Save Changes
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
