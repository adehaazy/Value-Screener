import { createBrowserRouter } from "react-router";
import ProtectedRoot from "./components/ProtectedRoot";
import Home from "./components/Home";
import Deepdive from "./components/Deepdive";
import Screener from "./components/Screener";
import Compare from "./components/Compare";
import Briefing from "./components/Briefing";
import Settings from "./components/Settings";
import Portfolio from "./components/Portfolio";
import Watchlist from "./components/Watchlist";
import Analyses from "./components/Analyses";
import Login from "./components/Login";
import ForgotPasscode from "./components/ForgotPasscode";
import ChangePasscode from "./components/ChangePasscode";

export const router = createBrowserRouter([
  /* ── Public routes (no auth required) ───────────────────── */
  { path: "/login",            Component: Login },
  { path: "/forgot-passcode",  Component: ForgotPasscode },
  { path: "/change-passcode",  Component: ChangePasscode },

  /* ── Protected app shell ────────────────────────────────── */
  {
    path: "/",
    Component: ProtectedRoot,
    children: [
      { index: true,         Component: Home },
      { path: "deepdive",    Component: Deepdive },
      { path: "screener",    Component: Screener },
      { path: "compare",     Component: Compare },
      { path: "watchlist",   Component: Watchlist },
      { path: "briefing",    Component: Briefing },
      { path: "settings",    Component: Settings },
      { path: "portfolio",   Component: Portfolio },
      { path: "analyses",    Component: Analyses },
    ],
  },
]);
