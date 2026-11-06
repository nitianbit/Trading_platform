export interface UserInfo {
  id: number;
  role: "super_admin" | "broker" | "user";
  broker_id: number | null;
  broker_username: string | null;
  username: string;
  email: string;
  is_admin: boolean;
  broker: string | null;
  broker_authenticated: boolean;
  paper_only: boolean;
}

export interface SetupRequest {
  setup_token?: string;
  username: string;
  email: string;
  password: string;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface AuthResponse {
  status: string;
  message: string;
}

export interface SetupCheckResponse {
  needs_setup: boolean;
}
