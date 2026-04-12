/**
 * dataContext.ts — context definition, types, and hook.
 *
 * Kept separate from DataContext.tsx (which exports DataProvider, a component)
 * so Vite Fast Refresh works: component files must not export non-components.
 */
import { createContext, useContext } from "react";

/* ── Types ─────────────────────────────────────────────────── */
export interface AppData {
  instruments:  any[];
  watchlist:    any[];
  holdings:     any[];
  signals:      any[];
  screenerLoading:  boolean;
  watchlistLoading: boolean;
  portfolioLoading: boolean;
  signalsLoading:   boolean;
  screenerError:    string | null;
  watchlistError:   string | null;
  portfolioError:   string | null;
  refetchScreener:  () => void;
  refetchPortfolio: () => void;
  refetchWatchlist: () => void;
}

export const defaultData: AppData = {
  instruments:  [],
  watchlist:    [],
  holdings:     [],
  signals:      [],
  screenerLoading:  true,
  watchlistLoading: true,
  portfolioLoading: true,
  signalsLoading:   true,
  screenerError:    null,
  watchlistError:   null,
  portfolioError:   null,
  refetchScreener:  () => {},
  refetchPortfolio: () => {},
  refetchWatchlist: () => {},
};

export const DataContext = createContext<AppData>(defaultData);

/* ── Hook ── */
export function useAppData() {
  return useContext(DataContext);
}
