import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/contexts/AuthContext";
import api from "@/config/api";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/apiError";

interface Earnings { balance: number; rate_percent: number; virtual: boolean; currency: string }
const money = (value: number) => new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 }).format(value);
export function BrokerageEarnings() {
  const { user } = useAuth();
  const query = useQuery({ queryKey: ["brokerage-earnings", user?.username],
    queryFn: async () => (await api.get<Earnings>("/web/paper/earnings")).data, refetchInterval: 5000 });
  return <section className="rounded-xl border border-border bg-card p-5">
    <h2 className="font-semibold">Your virtual brokerage earnings</h2>
    {query.isLoading ? <p role="status" className="mt-3 text-sm text-muted-foreground">Loading earnings…</p> : query.isError ?
      <div role="alert" className="mt-3 flex flex-wrap items-center gap-3"><p className="text-sm text-destructive">{errorMessage(query.error)}</p><Button size="sm" variant="outline" onClick={() => void query.refetch()}>Retry earnings</Button></div> : query.data && <>
        <p className="mt-3 text-2xl font-semibold tabular-nums">{money(query.data.balance)}</p>
        <p className="mt-2 max-w-prose text-sm leading-relaxed text-muted-foreground">Your {query.data.rate_percent}% share from executed user buys and sells. Users pay 4% total: 3% to their broker and 1% to Super Admin. This virtual earnings balance is separate from trading capital.</p>
      </>}
  </section>;
}
