import { createContext, useContext, useEffect } from "react";
import type { ReactNode } from "react";
import type { TradingMode } from "@/api/trading_mode";
interface TradingModeContextType {
  mode: TradingMode; isSandbox: boolean; isLoading: boolean;
  setMode: (mode: TradingMode) => Promise<TradingMode>; refresh: () => Promise<void>;
}
const TradingModeContext = createContext<TradingModeContextType | null>(null);
export function TradingModeProvider({ children }: { children: ReactNode }) {
  useEffect(() => { document.documentElement.dataset.tradingMode = "sandbox"; }, []);
  return <TradingModeContext.Provider value={{
    mode: "sandbox", isSandbox: true, isLoading: false,
    setMode: async mode => {
      if (mode !== "sandbox") throw new Error("This platform supports paper trading only.");
      return "sandbox";
    },
    refresh: async () => {},
  }}>{children}</TradingModeContext.Provider>;
}
// eslint-disable-next-line react-refresh/only-export-components -- Preserve the established shared component and consumer API.
export function useTradingMode(): TradingModeContextType {
  const context = useContext(TradingModeContext);
  if (!context) throw new Error("useTradingMode must be used within TradingModeProvider");
  return context;
}
