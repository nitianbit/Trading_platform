import api from "@/config/api";
import { resolveApiKey } from "@/api/apikey";

export interface IVSmileStrike {
  strike: number;
  ce_iv: number | null;
  pe_iv: number | null;
}

export interface IVSmileResponse {
  status: "success" | "error";
  underlying: string;
  spot_price: number;
  atm_strike: number;
  atm_iv: number | null;
  skew: number | null;
  expiry_date: string;
  chain: IVSmileStrike[];
  message?: string;
}


export async function fetchIVSmile(params: {
  underlying: string;
  exchange: "NFO" | "BFO";
  expiry_date: string;
}): Promise<IVSmileResponse> {
  const apikey = await resolveApiKey();
  const response = await api.post<IVSmileResponse>("/api/v1/ivsmile", {
    apikey,
    ...params,
  });
  return response.data;
}
