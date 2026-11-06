import axios from "axios";
export function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const body = error.response?.data as { detail?: unknown; message?: unknown } | undefined;
    if (typeof body?.detail === "string") return body.detail;
    if (typeof body?.message === "string") return body.message;
    if (Array.isArray(body?.detail)) return body.detail.map((item: { msg?: unknown }) =>
      typeof item.msg === "string" ? item.msg : "Invalid form value").join(". ");
  }
  return error instanceof Error ? error.message : "The request failed. Please try again.";
}

