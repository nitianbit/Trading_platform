import { useQuery } from "@tanstack/react-query";
import { Link, Navigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import api from "@/config/api";
import { buttonVariants } from "@/components/ui/button";
import { BrokerageEarnings } from "@/components/accounts/BrokerageEarnings";
import { UserTrades } from "@/components/accounts/UserTrades";
import { BrokerManagement } from "@/components/accounts/BrokerManagement";
import { PlatformControls } from "@/components/trading/PlatformControls";
import { errorMessage } from "@/lib/apiError";

interface Account {
  id: number; username: string; email: string; is_admin: boolean; role: string; broker_id: number | null; is_active: boolean; password_set: boolean;
  available: number | null; used_margin: number | null; realized_pnl: number | null;
  unrealized_pnl: number; open_positions: number; pending_orders: number; fills: number;
}
interface Overview {
  customers: number; open_positions: number; pending_orders: number; fills: number;
  updated_at: string; accounts: Account[];
}
const money = (value: number | null) => value === null ? "Not started" :
  new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 }).format(value);

export default function Admin() {
  const { user } = useAuth();
  const query = useQuery({
    queryKey: ["paper-admin", user?.username], enabled: user?.role === "super_admin" || user?.role === "broker",
    queryFn: async () => (await api.get<Overview>("/web/paper/admin")).data,
    refetchInterval: 5000,
  });
  if (user?.role !== "super_admin" && user?.role !== "broker") return <Navigate to="/dashboard" replace />;
  return <div className="min-w-0 space-y-6">
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div><h1 className="text-2xl font-semibold tracking-tight">{user.role === "super_admin" ? "Super Admin overview" : "Broker overview"}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{user.role === "super_admin" ? "Manage brokers, users and platform settings." : "Monitor the users and paper activity under your broker account."}</p></div>
      <div className="flex flex-wrap gap-2">
        <Link className={buttonVariants()} to="/customers">Manage users</Link>
        {user.is_admin && <Link className={buttonVariants({ variant: "outline" })} to="/sandbox">Paper settings</Link>}
      </div>
    </div>
    {query.isLoading ? <p role="status" className="text-sm text-muted-foreground">Loading platform activity…</p> :
      query.isError ? <div role="alert" className="space-y-3 text-sm text-destructive">
        <p>{errorMessage(query.error)}</p><button className={buttonVariants({ variant: "outline" })} onClick={() => void query.refetch()}>Try again</button>
      </div> : query.data && <>
        <dl className="grid grid-cols-2 gap-4 rounded-xl border border-border bg-card p-5 lg:grid-cols-4">
          {([["Customers", query.data.customers], ["Open positions", query.data.open_positions], ["Pending orders", query.data.pending_orders], ["Paper fills", query.data.fills]] as const).map(([label, value]) =>
            <div key={label}><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-2 text-2xl font-semibold tabular-nums">{value}</dd></div>)}
        </dl>
        {user.is_admin && <><BrokerManagement /><PlatformControls /></>}
        <BrokerageEarnings />
        <UserTrades />
        <section className="rounded-xl border border-border bg-card p-5">
          <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2"><h2 className="font-semibold">Account activity</h2>
            <p className="text-xs text-muted-foreground">Updated {new Date(query.data.updated_at).toLocaleTimeString()} · Refreshes every 5 seconds</p></div>
          {query.data.customers === 0 && <p className="mb-4 text-sm text-muted-foreground">No customers yet. Brokers can create user invitations from Manage users.</p>}
          <div className="relative min-w-0 max-w-full overflow-x-auto"><table className="w-full text-left text-sm">
            <caption className="sr-only">All platform accounts with virtual balances and paper activity</caption>
            <thead><tr className="border-b border-border text-xs text-muted-foreground">
              {["Account", "Available funds", "Used margin", "Net realized P&L", "Open P&L", "Positions", "Pending", "Fills"].map(label => <th key={label} scope="col" className="whitespace-nowrap px-3 pb-3 font-medium first:pl-0 last:pr-0">{label}</th>)}
            </tr></thead>
            <tbody className="divide-y divide-border">{query.data.accounts.map(row => <tr key={row.id}>
              <th scope="row" className="py-4 pr-3 text-left font-medium"><span>{row.username}</span><span className="mt-1 block text-xs font-normal text-muted-foreground">{row.role === "super_admin" ? "Super Admin" : row.role === "broker" ? "Broker" : "User"}</span></th>
              {[money(row.available), money(row.used_margin), money(row.realized_pnl), money(row.unrealized_pnl), row.open_positions, row.pending_orders, row.fills].map((value, index) =>
                <td key={index} className="whitespace-nowrap px-3 py-4 text-right tabular-nums last:pr-0">{value}</td>)}
            </tr>)}</tbody>
          </table></div>
          <p className="mt-4 text-xs text-muted-foreground">Balances initialize when an account first opens its trading desk. All values are virtual INR.</p>
        </section>
      </>}
  </div>;
}
