/**
 * DataContext.tsx — exports only DataProvider (a component).
 *
 * Types, the context object, and the useAppData hook live in appDataStore.ts
 * so Vite Fast Refresh works correctly: component files must not export
 * non-component values or hooks.
 */
import {
  useEffect,
  useRef,
  useState,
  useCallback,
  type ReactNode,
} from "react";
import {
  getScreener,
  getWatchlist,
  getPortfolio,
  getSignals,
} from "../api/client";
import { DataContext } from "./appDataStore";

/* ── Retry helper ──────────────────────────────────────────── */
async function fetchWithRetry<T>(
  fn: () => Promise<T>,
  retries = 3,
  delayMs = 4000
): Promise<T> {
  let lastErr: unknown;
  for (let i = 0; i < retries; i++) {
    try {
      return await fn();
    } catch (e) {
      lastErr = e;
      if (i < retries - 1) {
        await new Promise((r) => setTimeout(r, delayMs * (i + 1)));
      }
    }
  }
  throw lastErr;
}

/* ── Provider ──────────────────────────────────────────────── */
export function DataProvider({ children }: { children: ReactNode }) {
  const [instruments,  setInstruments]  = useState<any[]>([]);
  const [watchlist,    setWatchlist]    = useState<any[]>([]);
  const [holdings,     setHoldings]     = useState<any[]>([]);
  const [signals,      setSignals]      = useState<any[]>([]);

  const [screenerLoading,  setScreenerLoading]  = useState(true);
  const [watchlistLoading, setWatchlistLoading] = useState(true);
  const [portfolioLoading, setPortfolioLoading] = useState(true);
  const [signalsLoading,   setSignalsLoading]   = useState(true);

  const [screenerError,  setScreenerError]  = useState<string | null>(null);
  const [watchlistError, setWatchlistError] = useState<string | null>(null);
  const [portfolioError, setPortfolioError] = useState<string | null>(null);

  const hasFetchedScreener  = useRef(false);
  const hasFetchedWatchlist = useRef(false);
  const hasFetchedPortfolio = useRef(false);

  /* ── Fetchers ── */
  const fetchScreener = useCallback(async () => {
    setScreenerLoading(true);
    setScreenerError(null);
    try {
      // Screener timeout is 3 min (set in client.js) — first run after a fresh
      // deploy fetches 648 tickers from yfinance, can take 3-10 min.
      // No retries: one long patient wait, then fall back to mock data.
      const data = await fetchWithRetry(getScreener, 1, 5000);
      setInstruments(data?.instruments ?? []);
    } catch (e: any) {
      setScreenerError(e?.message ?? "Server unavailable — showing sample data");
    } finally {
      setScreenerLoading(false);
    }
  }, []);

  const fetchWatchlist = useCallback(async () => {
    setWatchlistLoading(true);
    setWatchlistError(null);
    try {
      const data = await fetchWithRetry(getWatchlist, 2, 3000);
      setWatchlist(data?.instruments ?? []);
    } catch (e: any) {
      setWatchlistError(e?.message ?? "Failed to load");
    } finally {
      setWatchlistLoading(false);
    }
  }, []);

  const fetchPortfolio = useCallback(async () => {
    setPortfolioLoading(true);
    setPortfolioError(null);
    try {
      const data = await fetchWithRetry(getPortfolio, 2, 3000);
      setHoldings(data?.holdings ?? []);
    } catch (e: any) {
      setPortfolioError(e?.message ?? "Failed to load");
    } finally {
      setPortfolioLoading(false);
    }
  }, []);

  const fetchSignals = useCallback(async () => {
    setSignalsLoading(true);
    try {
      const data = await getSignals();
      setSignals(data?.signals ?? []);
    } catch {
      // signals failing is non-critical — swallow silently
    } finally {
      setSignalsLoading(false);
    }
  }, []);

  /* ── Kick off all fetches on mount, once only ── */
  useEffect(() => {
    if (!hasFetchedScreener.current) {
      hasFetchedScreener.current = true;
      fetchScreener();
    }
    if (!hasFetchedWatchlist.current) {
      hasFetchedWatchlist.current = true;
      fetchWatchlist();
    }
    if (!hasFetchedPortfolio.current) {
      hasFetchedPortfolio.current = true;
      fetchPortfolio();
    }
    fetchSignals();
  }, [fetchScreener, fetchWatchlist, fetchPortfolio, fetchSignals]);

  return (
    <DataContext.Provider
      value={{
        instruments,
        watchlist,
        holdings,
        signals,
        screenerLoading,
        watchlistLoading,
        portfolioLoading,
        signalsLoading,
        screenerError,
        watchlistError,
        portfolioError,
        refetchScreener:  fetchScreener,
        refetchPortfolio: fetchPortfolio,
        refetchWatchlist: fetchWatchlist,
      }}
    >
      {children}
    </DataContext.Provider>
  );
}
