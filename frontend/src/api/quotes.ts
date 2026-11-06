import api from "@/config/api";
import { resolveApiKey } from "@/api/apikey";

/**
 * A single row from POST /api/v1/multiquotes. OpenBull returns flat rows
 * (ltp/open/high/... at the top level) keyed by symbol/exchange.
 */
export interface MultiQuoteRow {
  symbol: string;
  exchange: string;
  ltp?: number;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  prev_close?: number;
  volume?: number;
  oi?: number;
  [k: string]: unknown;
}



/**
 * Fetch quotes for many symbols in one call via the public API. Used as the
 * REST fallback for live price overlays when the WebSocket feed is unavailable.
 * Returns [] on any error (it is a best-effort fallback, never throws).
 */
export async function getMultiQuotes(
  symbols: Array<{ symbol: string; exchange: string }>,
): Promise<MultiQuoteRow[]> {
  if (!symbols.length) return [];
  try {
    const apikey = await resolveApiKey();
    const resp = await api.post<{ status: string; results?: MultiQuoteRow[] }>(
      "/api/v1/multiquotes",
      { apikey, symbols },
    );
    if (resp.data?.status === "success" && Array.isArray(resp.data.results)) {
      return resp.data.results;
    }
  } catch {
    // Best-effort fallback — swallow errors and let the caller keep last data.
  }
  return [];
}
