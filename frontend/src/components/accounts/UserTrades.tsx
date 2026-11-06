import { formatPrice } from "@/lib/price";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/contexts/AuthContext";
import api from "@/config/api";
import type { ManagedAccount } from "@/api/accounts";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/apiError";

interface Trade {
  brokerage: number; broker_credit: number; admin_credit: number;
  id: number; user_id: number; username: string; broker_username: string | null;
  tradeid: string; symbol: string; exchange: string; action: string; product: string;
  quantity: number; average_price: number; trade_value: number; executed_at: string;
}
interface TradePage { trades: Trade[]; next_before_id: number | null }
const money = (value: number) => new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 }).format(value);

export function UserTrades() {
  const { user } = useAuth();
  const [userId, setUserId] = useState("");
  const [before, setBefore] = useState<number | null>(null);
  const [earlier, setEarlier] = useState<(number | null)[]>([]);
  const users = useQuery({ queryKey: ["paper-users", user?.username],
    queryFn: async () => (await api.get<ManagedAccount[]>("/web/paper/users")).data });
  const query = useQuery({ queryKey: ["managed-trades", user?.username, userId, before],
    queryFn: async () => (await api.get<TradePage>("/web/paper/trades", {
      params: { limit: 50, ...(userId ? { user_id: Number(userId) } : {}), ...(before ? { before_id: before } : {}) },
    })).data, refetchInterval: before === null ? 5000 : false });
  return <section className="space-y-4 rounded-xl border border-border bg-card p-5">
    <div className="flex flex-wrap items-start justify-between gap-4"><div><h2 className="font-semibold">User trades</h2>
      <p className="mt-1 text-sm text-muted-foreground">{user?.role === "broker" ? "Executed trades from your users only." : "Executed user trades across all brokers."} Includes earlier sessions.</p></div>
      <div className="min-w-0 w-full space-y-2 sm:w-auto sm:max-w-xs"><Label htmlFor="trade-user-filter">Filter by user</Label>
        <select id="trade-user-filter" value={userId} onChange={event => { setUserId(event.target.value); setBefore(null); setEarlier([]); }}
          className="h-9 min-w-0 w-full max-w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-2 focus-visible:outline-ring" disabled={users.isLoading}>
          <option value="">{user?.role === "broker" ? "All your users" : "All users"}</option>{users.data?.map(row => <option key={row.id} value={row.id}>{row.username}</option>)}
        </select></div>
    </div>
    {users.isError && <p role="alert" className="text-sm text-destructive">User filter: {errorMessage(users.error)}</p>}
    {query.isLoading ? <p role="status" className="py-6 text-sm text-muted-foreground">Loading user trades…</p> : query.isError ?
      <div role="alert" className="space-y-3"><p className="text-sm text-destructive">{errorMessage(query.error)}</p><Button variant="outline" onClick={() => void query.refetch()}>Retry trades</Button></div> :
      query.data?.trades.length === 0 ? <p className="py-6 text-sm text-muted-foreground">No executed trades in this view.</p> :
      <div className="relative min-w-0 max-w-full overflow-x-auto"><table className="w-full text-left text-sm"><caption className="sr-only">Executed paper trades within your account-management scope</caption>
        <thead><tr className="border-b border-border text-xs text-muted-foreground">{["Time", "User", "Broker", "Instrument", "Side", "Quantity", "Fill price", "Trade value", "Brokerage", "Broker credit", "Admin credit"].map(label => <th key={label} scope="col" className="whitespace-nowrap px-3 pb-3 font-medium first:pl-0">{label}</th>)}</tr></thead>
        <tbody className="divide-y divide-border">{query.data?.trades.map(row => <tr key={row.id}>
          <td className="whitespace-nowrap py-3 pr-3 text-xs"><time dateTime={row.executed_at}>{new Date(row.executed_at).toLocaleString()}</time></td>
          <th scope="row" className="px-3 py-3 font-medium">{row.username}</th><td className="px-3 py-3">{row.broker_username ?? "Legacy · unassigned"}</td>
          <td className="px-3 py-3"><span className="font-medium">{row.symbol}</span><span className="mt-1 block text-xs text-muted-foreground">{row.exchange} · {row.product}</span></td>
          <td className="px-3 py-3">{row.action}</td><td className="px-3 py-3 text-right tabular-nums">{row.quantity}</td>
          <td className="whitespace-nowrap px-3 py-3 text-right tabular-nums">₹{formatPrice(row.average_price)}</td><td className="whitespace-nowrap px-3 py-3 text-right tabular-nums">{money(row.trade_value)}</td>
          <td className="whitespace-nowrap px-3 py-3 text-right tabular-nums">{money(row.brokerage)}</td>
          <td className="whitespace-nowrap px-3 py-3 text-right tabular-nums">{money(row.broker_credit)}</td>
          <td className="whitespace-nowrap px-3 py-3 text-right tabular-nums">{money(row.admin_credit)}</td>
        </tr>)}</tbody>
      </table></div>}
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4"><p className="text-xs text-muted-foreground">Up to 50 fills per page · Latest trades refresh every 5 seconds</p>
      <div className="flex gap-2"><Button size="sm" variant="outline" disabled={earlier.length === 0 || query.isFetching} onClick={() => { setBefore(earlier[earlier.length - 1]); setEarlier(earlier.slice(0, -1)); }}>Newer</Button>
        <Button size="sm" variant="outline" disabled={!query.data?.next_before_id || query.isFetching} onClick={() => { setEarlier([...earlier, before]); setBefore(query.data?.next_before_id ?? null); }}>Older</Button></div>
    </div>
  </section>;
}
