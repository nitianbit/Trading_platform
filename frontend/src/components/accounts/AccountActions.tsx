import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import api from "@/config/api";
import type { ManagedAccount, Invitation } from "@/api/accounts";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/apiError";

export function AccountActions({ account, onInvitation }: { account: ManagedAccount; onInvitation: (invite: Invitation) => void }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const client = useQueryClient();
  const run = async (invite: boolean) => {
    setPending(true); setError("");
    try {
      if (invite) onInvitation((await api.post<Invitation>(`/web/paper/accounts/${account.id}/invitation`)).data);
      else await api.patch(`/web/paper/accounts/${account.id}`, { is_active: !account.is_active });
      for (const key of ["paper-users", "paper-brokers", "paper-admin"]) void client.invalidateQueries({ queryKey: [key] });
    } catch (err) { setError(errorMessage(err)); }
    finally { setPending(false); }
  };
  return <div className="space-y-2"><div className="flex flex-wrap gap-2">
    <Button type="button" size="sm" variant="outline" disabled={pending} aria-label={(account.is_active ? "Disable " : "Enable ") + account.username} onClick={() => void run(false)}>{account.is_active ? "Disable" : "Enable"}</Button>
    {!account.password_set && account.is_active && <Button type="button" size="sm" variant="outline" disabled={pending} aria-label={"New invitation for " + account.username} onClick={() => void run(true)}>New link</Button>}
  </div>{error && <p role="alert" className="max-w-xs text-xs text-destructive">{error}</p>}</div>;
}
