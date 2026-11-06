import api from "@/config/api";
import { resolveApiKey } from "@/api/apikey";
import type {
  ExpiryResponse,
  FnoExchange,
  OptionChainResponse,
  PlaceOrderRequest,
  PlaceOrderResponse,
  UnderlyingsResponse,
} from "@/types/optionchain";



export async function fetchOptionChain(params: {
  underlying: string;
  exchange: string;
  expiry_date: string;
  strike_count: number;
}): Promise<OptionChainResponse> {
  const apikey = await resolveApiKey();
  const response = await api.post<OptionChainResponse>("/api/v1/optionchain", {
    apikey,
    ...params,
  });
  return response.data;
}

export async function fetchExpiries(params: {
  symbol: string;
  exchange: string;
  instrumenttype?: string;
}): Promise<ExpiryResponse> {
  const apikey = await resolveApiKey();
  const response = await api.post<ExpiryResponse>("/api/v1/expiry", {
    apikey,
    instrumenttype: params.instrumenttype ?? "options",
    ...params,
  });
  return response.data;
}

export async function fetchUnderlyings(exchange: FnoExchange): Promise<UnderlyingsResponse> {
  const response = await api.get<UnderlyingsResponse>("/web/symbols/underlyings", {
    params: { exchange },
  });
  return response.data;
}

export async function placeOrder(req: Omit<PlaceOrderRequest, "apikey">): Promise<PlaceOrderResponse> {
  const apikey = await resolveApiKey();
  const response = await api.post<PlaceOrderResponse>("/api/v1/placeorder", {
    apikey,
    ...req,
  });
  return response.data;
}
