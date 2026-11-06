import type { QueryClient } from "@tanstack/react-query";
import type { UserInfo } from "../types/auth.ts";

export const authKey = ["auth", "me"] as const;

// Preserve the query observed by AuthProvider; cancel in-flight work before
// removing private books so a previous account cannot repopulate them.
export async function replaceSession(client: QueryClient, user: UserInfo | null) {
  await client.cancelQueries();
  client.removeQueries({ predicate: query => !(query.queryKey[0] === "auth" && query.queryKey[1] === "me") });
  client.getMutationCache().clear();
  client.setQueryData(authKey, user);
}
