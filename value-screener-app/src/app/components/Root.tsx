import { Outlet, Link, useLocation, useNavigate } from "react-router";
import { useEffect, useState } from "react";
import {
  Home,
  BarChart2,
  ListFilter,
  PieChart,
  FileText,
  Moon,
  Settings,
  Bookmark,
  BookmarkCheck,
  LogOut,
} from "lucide-react";
import { API_BASE } from "../../api/client";
import { useAuth } from "../AuthContext";

const LAST_SEEN_KEY = "last_seen_briefing_at";

const NAV_ITEMS = [
  { name: "Home",      path: "/",           icon: Home },
  { name: "Scores",    path: "/screener",   icon: ListFilter },
  { name: "Deepdive",  path: "/deepdive",   icon: BarChart2 },
  { name: "Analyses",  path: "/analyses",   icon: BookmarkCheck },
  { name: "Portfolio", path: "/portfolio",  icon: PieChart },
  { name: "Watchlist", path: "/watchlist",  icon: Bookmark },
  { name: "Briefing",  path: "/briefing",   icon: FileText, hasBadge: true },
];

export default function Root() {
  const location = useLocation();
  const navigate = useNavigate();
  const { logout, user } = useAuth();
  const [briefingUpdated, setBriefingUpdated] = useState(false);

  const handleLogout = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  // Poll for briefing updates — check generated_at against what the user last saw
  useEffect(() => {
    let cancelled = false;

    async function checkBriefing() {
      try {
        const res = await fetch(`${API_BASE}/api/briefing`, { method: "GET" });
        if (!res.ok) return;
        const data = await res.json();
        const generatedAt: string | undefined = data?.briefing?.generated_at;
        if (!generatedAt) return;

        const lastSeen = localStorage.getItem(LAST_SEEN_KEY);
        if (!cancelled) {
          setBriefingUpdated(lastSeen !== generatedAt);
        }
      } catch {
        // Silently ignore — badge simply won't show if offline
      }
    }

    checkBriefing();
    // Re-check every 5 minutes
    const interval = setInterval(checkBriefing, 5 * 60 * 1000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  // When user visits /briefing, mark it as seen
  useEffect(() => {
    if (location.pathname === "/briefing") {
      // We need the current generated_at to mark as seen
      fetch(`${API_BASE}/api/briefing`, { method: "GET" })
        .then((r) => r.json())
        .then((data) => {
          const generatedAt = data?.briefing?.generated_at;
          if (generatedAt) {
            localStorage.setItem(LAST_SEEN_KEY, generatedAt);
            setBriefingUpdated(false);
          }
        })
        .catch(() => {});
    }
  }, [location.pathname]);

  const isActive = (item: (typeof NAV_ITEMS)[0]) =>
    location.pathname === item.path ||
    (item.path !== "/" && location.pathname.startsWith(item.path));

  const showBadge = (item: (typeof NAV_ITEMS)[0]) =>
    "hasBadge" in item && item.hasBadge && briefingUpdated;

  return (
    <div className="flex flex-col min-h-screen bg-vs-bg">
      {/* ── Top Nav ── */}
      <nav className="sticky top-0 z-50 bg-vs-bg-card border-b border-vs-rule h-14 flex items-center px-4 md:px-10">
        {/* LEFT: Brand */}
        <Link
          to="/"
          className="font-mono text-sm font-medium text-vs-ink uppercase tracking-[0.15em] shrink-0"
        >
          Ben's Shed
        </Link>

        {/* CENTER: Desktop nav links */}
        <div className="hidden md:flex items-center justify-center flex-1 gap-0">
          {NAV_ITEMS.map((item) => {
            const active = isActive(item);
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`text-[11px] font-semibold uppercase tracking-widest px-5 h-14 flex items-center border-b-3 transition-colors relative ${
                  active
                    ? "text-vs-accent border-vs-accent"
                    : "text-vs-ink-mid border-transparent hover:text-vs-ink"
                }`}
              >
                {item.name}
                {showBadge(item) && (
                  <span className="w-2 h-2 rounded-full bg-vs-neg absolute top-3 -right-0.5" />
                )}
              </Link>
            );
          })}
        </div>

        {/* RIGHT: Settings + Sign out (desktop only) */}
        <div className="hidden md:flex items-center gap-4 shrink-0">
          <Link
            to="/settings"
            className="text-[11px] font-semibold uppercase tracking-widest text-vs-ink-mid hover:text-vs-ink transition-colors"
          >
            Settings
          </Link>
          <button
            onClick={handleLogout}
            className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-widest text-vs-ink-mid hover:text-vs-ink transition-colors"
          >
            <LogOut className="w-3.5 h-3.5" />
            Sign out
          </button>
        </div>
      </nav>

      {/* ── Main Content ── */}
      <main className="flex-1 w-full max-w-[1200px] mx-auto px-4 md:px-10 pb-20 md:pb-0">
        <Outlet />
      </main>

      {/* ── Bottom Nav (mobile only) ── */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 z-50 bg-vs-bg-card border-t border-vs-rule h-16 flex items-center justify-around">
        {[...NAV_ITEMS, { name: "Settings", path: "/settings", icon: Settings }].map(
          (item) => {
            const active = isActive(item);
            const Icon = item.icon;
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`flex flex-col items-center gap-0.5 relative ${
                  active ? "text-vs-accent" : "text-vs-ink-soft"
                }`}
              >
                <Icon
                  className="w-5 h-5"
                  strokeWidth={active ? 2.5 : 2}
                />
                {showBadge(item as (typeof NAV_ITEMS)[0]) && (
                  <span className="w-1.5 h-1.5 rounded-full bg-vs-neg absolute top-2.5 right-[calc(50%-12px)]" />
                )}
                <span className="text-[9px] font-semibold uppercase tracking-wider">
                  {item.name}
                </span>
              </Link>
            );
          }
        )}
      </nav>
    </div>
  );
}
