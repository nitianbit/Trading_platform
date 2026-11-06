import { useState } from "react";
import type { FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/config/api";
import { getBrokers } from "@/api/accounts";
import type { Invitation, ManagedAccount } from "@/api/accounts";
import { AccountActions } from "./AccountActions";
import { InvitationLink } from "./InvitationLink";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/apiError";

function BrokerLimitEditor({ broker }: { broker: ManagedAccount }) {
  const [value, setValue] = useState(broker.max_users === null ? "" : String(broker.max_users));
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const client = useQueryClient();
  return <form className="min-w-52 space-y-2" onSubmit={async event => {
    event.preventDefault(); setPending(true); setError(""); setSaved(false);
    try {
      await api.patch(`/web/paper/brokers/${broker.id}/limit`, { max_users: value === "" ? null : Number(value) });
      setSaved(true);
      for (const key of ["paper-brokers", "paper-admin", "broker-capacity"]) void client.invalidateQueries({ queryKey: [key] });
    } catch (err) { setError(errorMessage(err)); } finally { setPending(false); }
  }}>
    <Label htmlFor={"broker-limit-" + broker.id} className="sr-only">Maximum users for {broker.username}</Label>
    <div className="flex gap-2"><Input id={"broker-limit-" + broker.id} type="number" min={0} max={2147483647} step={1} value={value} placeholder="Unlimited" disabled={pending}
      className="w-28" onChange={event => { setValue(event.target.value); setSaved(false); }} />
      <Button size="sm" variant="outline" disabled={pending} aria-label={"Save user limit for " + broker.username}>{pending ? "Saving…" : "Save limit"}</Button></div>
    {error && <p role="alert" className="max-w-xs text-xs text-destructive">{error}</p>}
    {saved && <p role="status" className="text-xs text-primary">Limit saved.</p>}
  </form>;
}

export function BrokerManagement() {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["paper-brokers"], queryFn: getBrokers });
  const [invitation, setInvitation] = useState<Invitation | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    setPending(true); setError(""); setInvitation(null);
    try {
      setInvitation((await api.post<Invitation>("/web/paper/brokers", { username: values.get("username"), email: values.get("email") })).data);
      form.reset();
      await client.invalidateQueries({ queryKey: ["paper-brokers"] });
      await client.invalidateQueries({ queryKey: ["paper-admin"] });
    } catch (err) { setError(errorMessage(err)); }
    finally { setPending(false); }
  };
  return <section className="min-w-0 space-y-5 rounded-xl border border-border bg-card p-5">
    <div><h2 className="font-semibold">Brokers</h2><p className="mt-1 text-sm text-muted-foreground">Create brokers here. Each broker invites and manages their own users.</p></div>
    <form onSubmit={submit} className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2"><div className="space-y-2"><Label htmlFor="broker-username">Broker username</Label><Input id="broker-username" name="username" required minLength={3} maxLength={80} pattern="[a-zA-Z0-9_]+" autoComplete="off" /></div>
        <div className="space-y-2"><Label htmlFor="broker-email">Broker email</Label><Input id="broker-email" name="email" type="email" maxLength={120} required autoComplete="off" /></div></div>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <Button disabled={pending}>{pending ? "Creating…" : "Create broker invitation"}</Button>
    </form>
    {invitation && <InvitationLink key={invitation.invitation_url} invitation={invitation} />}
    <p className="text-xs leading-relaxed text-muted-foreground">Disabling a broker blocks the broker and every user under them. Existing accounts and paper books are preserved. User limits include pending invitations and disabled users; blank means unlimited and 0 pauses creation. Lowering a limit preserves existing access.</p>
    {query.isLoading ? <p role="status" className="text-sm text-muted-foreground">Loading brokers…</p> : query.isError ?
      <div role="alert"><p className="text-sm text-destructive">{errorMessage(query.error)}</p><Button variant="outline" onClick={() => void query.refetch()}>Retry brokers</Button></div> :
      query.data?.length === 0 ? <p className="text-sm text-muted-foreground">No brokers yet. Create the first broker above.</p> :
      <div className="relative min-w-0 max-w-full overflow-x-auto"><table className="w-full text-left text-sm"><caption className="sr-only">Brokers and account access</caption>
        <thead><tr className="border-b border-border text-xs text-muted-foreground">{["Broker", "Email", "Users", "User limit", "Status", "Actions"].map(label => <th key={label} scope="col" className="px-2 pb-3 font-medium first:pl-0">{label}</th>)}</tr></thead>
        <tbody className="divide-y divide-border">{query.data?.map(row => <tr key={row.id}><th scope="row" className="py-3 pr-2 font-medium">{row.username}</th><td className="px-2 py-3">{row.email}</td><td className="px-2 py-3 tabular-nums">{row.users}</td><td className="px-2 py-3"><BrokerLimitEditor broker={row} /></td>
          <td className="px-2 py-3">{!row.is_active ? "Disabled" : row.password_set ? "Active" : "Awaiting activation"}</td><td className="px-2 py-3"><AccountActions account={row} onInvitation={setInvitation} /></td></tr>)}</tbody>
      </table></div>}
  </section>;
}
