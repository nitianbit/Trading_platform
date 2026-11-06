import type { QueryClient } from "@tanstack/react-query";
import { logout } from "@/api/auth";
import { replaceSession } from "@/lib/authSession";
export async function signOut(client: QueryClient) {
  await logout();
  await replaceSession(client, null);
}
