import api from "@/config/api";
import { resolveApiKey } from "@/api/apikey";

export interface MaxPainStrike {
  strike: number;
  ce_oi: number;
  pe_oi: number;
  total_pain: number;
}

export interface MaxPainResponse {
  status: "success" | "error";
  underlying: string;
  spot_price: number;
  quote_symbol?: string;
  quote_exchange?: string;
  atm_strike: number;
  max_pain_strike: number;
  total_ce_oi: number;
  total_pe_oi: number;
  pcr_oi: number;
  expiry_date: string;
  chain: MaxPainStrike[];
  message?: string;
}


export async function fetchMaxPain(params: {
  underlying: string;
  exchange: "NFO" | "BFO";
  expiry_date: string;
}): Promise<MaxPainResponse> {
  const apikey = await resolveApiKey();
  const response = await api.post<MaxPainResponse>("/api/v1/maxpain", {
    apikey,
    ...params,
  });
  return response.data;
}
