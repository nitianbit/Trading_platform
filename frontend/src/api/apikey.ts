import api from "@/config/api";

export interface ApiKeyResponse {
  api_key: string;
}

export async function getApiKey(): Promise<ApiKeyResponse> {
  const response = await api.get<ApiKeyResponse>("/web/apikey");
  return response.data;
}

export async function generateApiKey(): Promise<ApiKeyResponse> {
  const response = await api.post<ApiKeyResponse>("/web/apikey");
  return response.data;
}

/** Resolve against the current session; never retain account credentials globally. */
export async function resolveApiKey(): Promise<string> {
  const { api_key } = await getApiKey();
  if (!api_key) throw new Error("Your platform API key is unavailable. Sign in again.");
  return api_key;
}
