import { useState } from "react";
import type { FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Navigate, Link } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import api from "@/config/api";
import { getBrokers } from "@/api/accounts";
import type { ManagedAccount, Invitation } from "@/api/accounts";
import { AccountActions } from "@/components/accounts/AccountActions";
import { InvitationLink } from "@/components/accounts/InvitationLink";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/apiError";

function LegacyAssignment({ accountId, brokers }: { accountId: number; brokers: ManagedAccount[] }) {
  const [brokerId, setBrokerId] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const client = useQueryClient();
  return <div className="space-y-2"><Label htmlFor={"assign-" + accountId} className="sr-only">Assign permanent broker</Label>
    <select id={"assign-" + accountId} value={brokerId} onChange={event => setBrokerId(event.target.value)} disabled={pending} className="h-9 max-w-52 rounded-md border border-input bg-background px-2 text-sm focus-visible:outline-2 focus-visible:outline-ring">
      <option value="">Choose permanent broker</option>{brokers.filter(row => row.is_active && row.password_set).map(row => <option key={row.id} value={row.id}>{row.username}</option>)}
    </select>
    <Button size="sm" variant="outline" disabled={!brokerId || pending} onClick={async () => {
      setPending(true); setError("");
      try { await api.post(`/web/paper/users/${accountId}/assign-broker`, { broker_id: Number(brokerId) });
        for (const key of ["paper-users", "paper-brokers", "paper-admin"]) void client.invalidateQueries({ queryKey: [key] });
      } catch (err) { setError(errorMessage(err)); } finally { setPending(false); }
    }}>{pending ? "Assigning…" : "Assign permanently"}</Button>
    {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
  </div>;
}

export default function Customers() {
  const { user } = useAuth();
  const client = useQueryClient();
  const manager = user?.role === "broker" || user?.role === "super_admin";
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [invitation, setInvitation] = useState<Invitation | null>(null);
  const query = useQuery({ queryKey: ["paper-users", user?.username], enabled: manager,
    queryFn: async () => (await api.get<ManagedAccount[]>("/web/paper/users")).data });
  const brokers = useQuery({ queryKey: ["paper-brokers"], queryFn: getBrokers, enabled: user?.role === "super_admin" });
  const capacity = useQuery({ queryKey: ["broker-capacity", user?.username], enabled: user?.role === "broker",
    queryFn: async () => (await api.get<{ users: number; max_users: number | null }>("/web/paper/broker-capacity")).data,
    refetchInterval: 5000 });
  const atCapacity = capacity.data?.max_users != null && capacity.data.users >= capacity.data.max_users;
  if (!manager) return <Navigate to="/dashboard" replace />;
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setPending(true); setError(""); setInvitation(null);
    try {
      setInvitation((await api.post<Invitation>("/web/paper/users", { username: data.get("username"), email: data.get("email") })).data);
      form.reset();
      for (const key of ["paper-users", "paper-settings", "paper-admin", "broker-capacity"]) void client.invalidateQueries({ queryKey: [key] });
    } catch (err) { setError(errorMessage(err)); }
    finally { setPending(false); }
  };
  return <div className="space-y-6">
    <div><h1 className="text-2xl font-semibold tracking-tight">{user?.role === "broker" ? "Your users" : "All users"}</h1>
      <p className="mt-1 text-sm text-muted-foreground">{user?.role === "broker" ? "Users created here belong permanently to your broker account." : "Oversee users across brokers. Only brokers can create new users."}</p></div>
    {user?.role === "broker" ? <form onSubmit={submit} className="space-y-4 rounded-xl border border-border bg-card p-5">
      <h2 className="font-semibold">Invite a user</h2>
      {capacity.data && <p className="text-sm text-muted-foreground">{capacity.data.users} users · {capacity.data.max_users === null ? "Unlimited broker capacity" : `Broker limit: ${capacity.data.max_users}`}</p>}
      {atCapacity && <p role="status" className="text-sm text-destructive">Your user limit has been reached. Ask Super Admin to increase it.</p>}
      <p className="text-xs leading-relaxed text-muted-foreground">Create the account, then share its single-use link privately. The user chooses their own password. Platform capacity is checked before creating the invitation.</p>
      <div className="grid gap-4 sm:grid-cols-2"><div className="space-y-2"><Label htmlFor="customer-username">Username</Label><Input id="customer-username" name="username" required minLength={3} maxLength={80} pattern="[a-zA-Z0-9_]+" autoComplete="off" /></div>
        <div className="space-y-2"><Label htmlFor="customer-email">Email</Label><Input id="customer-email" name="email" type="email" maxLength={120} required autoComplete="off" /></div></div>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <Button type="submit" disabled={pending || atCapacity}>{pending ? "Creating…" : "Create user invitation"}</Button>
    </form> : <p className="text-sm text-muted-foreground"><Link to="/admin" className="text-primary underline underline-offset-4">Manage brokers and platform capacity</Link>. Legacy users without a broker can be assigned once below; that choice is permanent.</p>}
    {invitation && <section className="rounded-xl border border-border bg-card p-5"><InvitationLink key={invitation.invitation_url} invitation={invitation} /></section>}
    <section className="rounded-xl border border-border bg-card p-5"><h2 className="mb-4 font-semibold">User accounts</h2>
      {query.isLoading ? <p role="status" className="text-sm text-muted-foreground">Loading users…</p> : query.isError ?
        <div role="alert"><p className="text-sm text-destructive">{errorMessage(query.error)}</p><Button variant="outline" onClick={() => void query.refetch()}>Retry users</Button></div> :
        query.data?.length === 0 ? <p className="text-sm text-muted-foreground">No users yet. {user?.role === "broker" ? "Create an invitation above." : "Your brokers can invite users after activating their accounts."}</p> :
        <div className="overflow-x-auto"><table className="w-full text-left text-sm"><caption className="sr-only">Users and permanent broker assignments</caption><thead><tr className="border-b border-border text-xs text-muted-foreground">
          {["Username", "Email", "Broker", "Status", "Actions"].map(label => <th key={label} scope="col" className="px-2 pb-3 font-medium first:pl-0">{label}</th>)}</tr></thead>
          <tbody className="divide-y divide-border">{query.data?.map(row => <tr key={row.id}><th scope="row" className="py-3 pr-2 font-medium">{row.username}</th><td className="px-2 py-3">{row.email}</td>
            <td className="px-2 py-3">{row.broker_username ?? (user?.role === "super_admin" ? <LegacyAssignment accountId={row.id} brokers={brokers.data ?? []} /> : "Unassigned")}</td>
            <td className="whitespace-nowrap px-2 py-3">{!row.is_active ? "Disabled" : row.broker_active === false ? "Broker disabled" : row.password_set ? "Active" : "Awaiting activation"}</td><td className="px-2 py-3"><AccountActions account={row} onInvitation={setInvitation} /></td></tr>)}</tbody>
        </table></div>}
    </section>
  </div>;
}
