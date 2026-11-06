import { useQuery } from "@tanstack/react-query";
import api from "@/config/api";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/apiError";

interface Quote {
  symbol: string; name: string; unit: string; price: number | null;
  updated_at: string | null; status: "live" | "stale" | "unavailable" | "disabled";
}
interface Feed { enabled: boolean; assets: Quote[] }
const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 4 });

export function ReferencePrices() {
  const query = useQuery({ queryKey: ["reference-prices"],
    queryFn: async () => (await api.get<Feed>("/web/paper/reference-prices")).data, refetchInterval: 10000 });
  if (query.data && (!query.data.enabled || query.data.assets.length === 0)) return null;
  return <section className="rounded-xl border border-border bg-card p-4 sm:p-5">
    <div className="flex flex-wrap items-baseline justify-between gap-2"><h2 className="font-semibold">Public reference prices</h2>
      <a href="https://gold-api.com/" target="_blank" rel="noreferrer" className="text-xs text-muted-foreground underline underline-offset-4">Source: Gold API</a></div>
    <p className="mt-1 text-xs leading-relaxed text-muted-foreground">USD prices, refreshed about every 30 seconds. Precious metals per troy ounce; copper uses the provider’s quoted unit. Reference only; paper orders use the separate demo feed.</p>
    {query.isLoading ? <p role="status" className="mt-4 text-sm text-muted-foreground">Connecting to public prices…</p> : query.isError ?
      <div role="alert" className="mt-4 flex flex-wrap items-center gap-3"><p className="text-sm text-destructive">{errorMessage(query.error)}</p><Button size="sm" variant="outline" onClick={() => void query.refetch()}>Retry prices</Button></div> :
      <dl className="mt-4 grid gap-x-6 gap-y-4 sm:grid-cols-2 lg:grid-cols-4">{query.data?.assets.map(row => <div key={row.symbol}>
        <dt className="text-sm font-medium">{row.name}<span className="ml-2 text-xs font-normal text-muted-foreground">{row.symbol}</span></dt>
        <dd className="mt-1 text-lg font-semibold tabular-nums">{row.price === null ? "—" : usd.format(row.price)}
          <span className="ml-2 text-xs font-normal text-muted-foreground">{row.status === "live" ? "Updated" : row.status === "stale" ? "Stale · paused" : "Unavailable"}</span></dd>
        <dd className="mt-1 text-xs text-muted-foreground">{row.updated_at ? <>Source time <time dateTime={row.updated_at}>{new Date(row.updated_at).toLocaleString()}</time></> : "Waiting for source data"}</dd>
      </div>)}</dl>}
  </section>;
}
