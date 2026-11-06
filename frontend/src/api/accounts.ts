import api from "@/config/api";

export interface ManagedAccount {
  id: number; username: string; email: string; role: "super_admin" | "broker" | "user";
  broker_id: number | null; broker_username: string | null; is_active: boolean; password_set: boolean;
  max_users: number | null;
  users?: number; broker_active?: boolean | null;
}
export interface Invitation extends ManagedAccount { invitation_url: string; expires_at: string }
export const getBrokers = async () => (await api.get<ManagedAccount[]>("/web/paper/brokers")).data;
