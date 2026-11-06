import api from "@/config/api";

export interface Policy {
  max_customers: number | null;
  disabled_groups: string[];
  disabled_instruments: string[];
  public_feed_enabled: boolean;
  disabled_reference_assets: string[];
}
export interface PlatformSettings {
  policy: Policy; revision: number; customer_count: number; groups: string[];
  instruments: { symbol: string; exchange: string; group: string; name: string }[];
  reference_assets: { symbol: string; name: string }[];
}
export const getPlatformSettings = async () => (await api.get<PlatformSettings>("/web/paper/settings")).data;
