import { useState } from "react";
import { Link } from "react-router";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  PieChart as RechartsPieChart,
  Pie,
  Cell,
} from "recharts";
import { TrendingUp, Activity } from "lucide-react";
import { cn } from "../utils";
import { useAppData } from "../useAppData";

/* ── Static chart data ── */
const PERF_DATA = [
  { month: "Jan", value: 1120000 },
  { month: "Feb", value: 1135000 },
  { month: "Mar", value: 1098000 },
  { month: "Apr", value: 1142000 },
  { month: "May", value: 1160000 },
  { month: "Jun", value: 1155000 },
  { month: "Jul", value: 1178000 },
  { month: "Aug", value: 1165000 },
  { month: "Sep", value: 1190000 },
  { month: "Oct", value: 1200000 },
];

const PIE_DATA = [
  { name: "Equities", value: 62, color: "#1a1a1a" },
  { name: "Fixed Income", value: 20, color: "#4d4d4d" },
  { name: "Alternatives", value: 12, color: "#808080" },
  { name: "Cash", value: 6, color: "#b3b3b3" },
];

const TIME_FILTERS = ["1M", "3M", "YTD", "1Y", "ALL"];

function currencySymbol(inst: any): string {
  const c = (inst.currency || "").toUpperCase();
  if (c === "GBP" || c === "GBX") return "£";
  if (c === "EUR") return "€";
  return "$";
}

/* ── Mock holdings fallback ── */
const MOCK_HOLDINGS = [
  { ticker: "AAPL", name: "Apple Inc.", price: 178.72, shares: 150, value: 26808, weight: 22.3, returnPct: 12.4 },
  { ticker: "MSFT", name: "Microsoft Corp.", price: 378.91, shares: 80, value: 30313, weight: 25.3, returnPct: 18.7 },
  { ticker: "BP.L", name: "BP plc", price: 4.85, shares: 2000, value: 9700, weight: 8.1, returnPct: -3.2 },
  { ticker: "VOD.L", name: "Vodafone Group", price: 0.72, shares: 5000, value: 3600, weight: 3.0, returnPct: -8.1 },
  { ticker: "SHEL.L", name: "Shell plc", price: 27.12, shares: 400, value: 10848, weight: 9.0, returnPct: 6.5 },
  { ticker: "TSLA", name: "Tesla Inc.", price: 248.50, shares: 60, value: 14910, weight: 12.4, returnPct: -4.9 },
];

export default function Portfolio() {
  const [activeFilter, setActiveFilter] = useState(2); // YTD
  const { holdings: liveHoldings, portfolioLoading } = useAppData();

  const holdings = liveHoldings?.length
    ? liveHoldings.map((h: any) => ({
        ticker: h.ticker,
        name: h.name || h.company || h.ticker,
        price: h.current_price ?? h.price ?? 0,
        shares: h.shares ?? 0,
        value: h.market_value ?? (h.shares ?? 0) * (h.current_price ?? h.price ?? 0),
        weight: h.weight ?? 0,
        returnPct: h.return_pct ?? h.pnl_pct ?? 0,
      }))
    : MOCK_HOLDINGS;

  const totalValue = holdings.reduce((s: number, h: any) => s + h.value, 0);

  // Compute allocation from actual holdings by asset_class
  const allocationData = (() => {
    const groups: Record<string, number> = {};
    holdings.forEach((h: any) => {
      const cls = h.asset_class || (liveHoldings.find((l: any) => l.ticker === h.ticker)?.asset_class) || "Equities";
      groups[cls] = (groups[cls] || 0) + h.value;
    });
    const total = Object.values(groups).reduce((s, v) => s + v, 0) || 1;
    const COLORS = ["#1a1a1a","#4d4d4d","#808080","#b3b3b3","#cccccc","#e0e0e0"];
    return Object.entries(groups).map(([name, value], i) => ({
      name,
      value: Math.round((value / total) * 100),
      color: COLORS[i % COLORS.length],
    }));
  })();

  const totalCost = liveHoldings.reduce((s: number, h: any) => s + ((h.avg_cost ?? h.price ?? 0) * (h.shares ?? 0)), 0);
  const totalReturn = totalValue - totalCost;
  const totalReturnPct = totalCost > 0 ? (totalReturn / totalCost) * 100 : 0;

  return (
    <div className="py-8 lg:py-10">
      {/* ── Hero Band ── */}
      <div className="bg-vs-accent -mx-4 md:-mx-10 px-4 md:px-10 py-10 md:py-12 flex flex-col md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="font-mono text-2xl md:text-[36px] font-medium text-white tracking-tight leading-tight">
            Portfolio
          </h1>
          <p className="text-[14px] text-white/80 mt-2">
            Track performance, allocation, and individual holdings.
          </p>
        </div>
        <div className="mt-4 md:mt-0 md:text-right">
          <p className="font-mono text-3xl md:text-4xl font-medium text-white leading-none">
            ${totalValue.toLocaleString()}
          </p>
          <p className="text-[14px] font-semibold text-vs-pos mt-1 flex items-center md:justify-end gap-1">
            <TrendingUp className="w-4 h-4" />
            {totalReturn >= 0 ? "+" : ""}{currencySymbol(liveHoldings[0] || {})}{Math.abs(totalReturn).toLocaleString(undefined, {maximumFractionDigits: 0})} ({totalReturnPct >= 0 ? "+" : ""}{totalReturnPct.toFixed(1)}%) total return
          </p>
        </div>
      </div>

      {/* ── Charts Grid ── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mt-8">
        {/* Area Chart */}
        <div className="lg:col-span-2 bg-vs-bg-card border border-vs-rule p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] border-b-2 border-vs-ink pb-2">
              Performance
            </h2>
            <div className="flex gap-1">
              {TIME_FILTERS.map((f, i) => (
                <button
                  key={f}
                  onClick={() => setActiveFilter(i)}
                  className={cn(
                    "text-[11px] font-semibold uppercase tracking-wider px-3 py-1",
                    i === activeFilter
                      ? "bg-vs-ink text-white"
                      : "text-vs-ink-soft hover:bg-vs-bg-raised"
                  )}
                >
                  {f}
                </button>
              ))}
            </div>
          </div>

          <ResponsiveContainer width="100%" height={280}>
            <AreaChart data={PERF_DATA}>
              <defs key="defs">
                <linearGradient id="portfolioColorValue" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#6B7F5E" stopOpacity={0.15} />
                  <stop offset="95%" stopColor="#6B7F5E" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis
                key="xaxis"
                dataKey="month"
                axisLine={false}
                tickLine={false}
                tick={{ fill: "#808080", fontSize: 10 }}
              />
              <YAxis
                key="yaxis"
                axisLine={false}
                tickLine={false}
                tick={{ fill: "#808080", fontSize: 10 }}
                tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`}
              />
              <Tooltip
                key="tooltip"
                contentStyle={{
                  borderRadius: "2px",
                  backgroundColor: "#fff",
                  border: "1px solid #e5e5e5",
                  fontSize: "12px",
                  fontWeight: "bold",
                }}
                formatter={(v: number) => [`$${v.toLocaleString()}`, "Value"]}
              />
              <Area
                key="area-value"
                type="monotone"
                dataKey="value"
                stroke="#6B7F5E"
                strokeWidth={2}
                fill="url(#portfolioColorValue)"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Pie Chart */}
        <div className="bg-vs-bg-card border border-vs-rule p-5">
          <h2 className="text-[13px] font-bold uppercase tracking-[0.08em] border-b-2 border-vs-ink pb-2 mb-4">
            Allocation
          </h2>
          <div className="relative">
            <ResponsiveContainer width="100%" height={200}>
              <RechartsPieChart>
                <Pie
                  data={allocationData}
                  dataKey="value"
                  innerRadius={60}
                  outerRadius={80}
                  paddingAngle={2}
                  stroke="none"
                >
                  {allocationData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
              </RechartsPieChart>
            </ResponsiveContainer>
            {/* Center label */}
            <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
              <span className="font-mono text-[20px] font-medium">{allocationData.length}</span>
              <span className="text-[9px] font-semibold uppercase tracking-widest text-vs-ink-soft">
                Assets
              </span>
            </div>
          </div>

          {/* Legend */}
          <div className="mt-4 space-y-2">
            {allocationData.map((item) => (
              <div key={item.name} className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div
                    className="w-3 h-3 shrink-0"
                    style={{ backgroundColor: item.color }}
                  />
                  <span className="text-[13px] text-vs-ink-mid">{item.name}</span>
                </div>
                <span className="text-[13px] font-semibold text-vs-ink">
                  {item.value}%
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── Holdings Table ── */}
      <div className="mt-8 bg-vs-bg-card border border-vs-rule">
        <div className="flex items-center justify-between p-4 border-b border-vs-rule">
          <h2 className="text-[13px] font-bold uppercase tracking-[0.08em]">
            Holdings
          </h2>
          <span className="text-[11px] text-vs-ink-soft font-semibold">
            {holdings.length} assets
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[700px]">
            <thead>
              <tr className="bg-vs-bg-subtle">
                {["Asset", "Price", "Shares", "Value", "Weight", "Return"].map(
                  (col) => (
                    <th
                      key={col}
                      className="text-left text-[10px] font-bold uppercase tracking-widest text-vs-ink-soft px-4 py-3"
                    >
                      {col}
                    </th>
                  )
                )}
              </tr>
            </thead>
            <tbody>
              {holdings.map((h: any) => {
                const positive = h.returnPct >= 0;
                return (
                  <tr
                    key={h.ticker}
                    className="border-b border-vs-rule last:border-0 hover:bg-vs-bg-raised transition-colors"
                  >
                    <td className="px-4 py-3">
                      <Link
                        to={`/deepdive?ticker=${h.ticker}`}
                        className="text-[14px] font-semibold text-vs-ink hover:text-vs-accent"
                      >
                        {h.ticker}
                      </Link>
                      <span className="block text-[10px] text-vs-ink-soft uppercase tracking-wider">
                        {h.name}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-[13px] font-semibold text-vs-ink">
                      ${h.price.toFixed(2)}
                    </td>
                    <td className="px-4 py-3 text-[13px] text-vs-ink-mid">
                      {h.shares.toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-[13px] font-semibold text-vs-ink">
                      ${h.value.toLocaleString()}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div className="w-16 h-1.5 bg-vs-bg-subtle overflow-hidden">
                          <div
                            className="h-full bg-vs-ink"
                            style={{ width: `${Math.min(h.weight, 100)}%` }}
                          />
                        </div>
                        <span className="text-[13px] font-semibold text-vs-ink">
                          {h.weight.toFixed(1)}%
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={cn(
                          "text-[13px] font-bold flex items-center gap-1",
                          positive ? "text-vs-pos" : "text-vs-neg"
                        )}
                      >
                        {positive ? (
                          <TrendingUp className="w-3.5 h-3.5" />
                        ) : (
                          <Activity className="w-3.5 h-3.5" />
                        )}
                        {positive ? "+" : ""}
                        {h.returnPct.toFixed(1)}%
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
