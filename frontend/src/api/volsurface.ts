import api from "@/config/api";
import { resolveApiKey } from "@/api/apikey";

export interface VolSurfaceExpiry {
  date: string;
  dte: number;
}

export interface VolSurfaceData {
  underlying: string;
  underlying_ltp: number;
  atm_strike: number;
  strikes: number[];
  expiries: VolSurfaceExpiry[];
  surface: (number | null)[][]; // surface[expiry_idx][strike_idx]
}

export interface VolSurfaceResponse {
  status: "success" | "error";
  data?: VolSurfaceData;
  message?: string;
}


export async function fetchVolSurface(params: {
  underlying: string;
  exchange: "NFO" | "BFO";
  expiry_dates: string[];
  strike_count: number;
}): Promise<VolSurfaceResponse> {
  const apikey = await resolveApiKey();
  const response = await api.post<VolSurfaceResponse>("/api/v1/volsurface", {
    apikey,
    ...params,
  });
  return response.data;
}
