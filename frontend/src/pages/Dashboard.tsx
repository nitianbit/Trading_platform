import { useNow } from "@/hooks/useNow";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { onlineManager, useQuery, useQueryClient } from "@tanstack/react-query";
import { createChart, LineSeries, ColorType } from "lightweight-charts";
import type { UTCTimestamp, IChartApi, ISeriesApi } from "lightweight-charts";
import { Link } from "react-router-dom";
import api from "@/config/api";
import { getDashboard, getPositions } from "@/api/dashboard";
import { PlaceOrderDialog } from "@/components/trading/PlaceOrderDialog";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ReferencePrices } from "@/components/trading/ReferencePrices";
import { formatPrice } from "@/lib/price";
import { errorMessage } from "@/lib/apiError";

interface Instrument {
  symbol: string; name: string; exchange: string; group: string;
  lot: number; tick: number; ltp: number; change_percent: number;
}
interface Market { data_source: "synthetic_demo"; instruments: Instrument[] }

const money = (value: number) => new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 }).format(value);

// Lightweight Charts accepts RGB/hex; canvas resolves the app's OKLCH tokens once.
function chartColor(value: string): string {
  const context = document.createElement("canvas").getContext("2d");
  if (!context) return "#64748b";
  context.fillStyle = value;
  context.fillRect(0, 0, 1, 1);
  const [r, g, b, alpha] = context.getImageData(0, 0, 1, 1).data;
  return `rgba(${r},${g},${b},${alpha / 255})`;
}

function PriceChart({ instrument }: { instrument: Instrument }) {
  const target = useRef<HTMLDivElement>(null);
  const chartState = useRef<{ chart: IChartApi; series: ISeriesApi<"Line">; fitted: boolean } | null>(null);
  const query = useQuery({
    queryKey: ["paper-chart", instrument.symbol, instrument.exchange],
    queryFn: async () => (await api.get<{ points: { time: number; value: number }[] }>("/web/paper/chart", {
      params: { symbol: instrument.symbol, exchange: instrument.exchange },
    })).data.points,
    refetchInterval: 10000,
  });
  useEffect(() => {
    if (!target.current) return;
    const style = getComputedStyle(target.current);
    const chart = createChart(target.current, {
      width: target.current.clientWidth, height: 230,
      layout: { background: { type: ColorType.Solid, color: chartColor(style.backgroundColor) }, textColor: chartColor(style.color) },
      grid: { vertLines: { visible: false }, horzLines: { color: "rgba(148,163,184,0.12)" } },
      timeScale: { timeVisible: true, secondsVisible: false, borderVisible: false },
      rightPriceScale: { borderVisible: false },
    });
    const series = chart.addSeries(LineSeries, { color: "#818cf8", lineWidth: 2, priceLineVisible: false });
    chartState.current = { chart, series, fitted: false };
    const resize = new ResizeObserver(([entry]) => {
      if (entry.contentRect.width <= 0) return;
      chart.applyOptions({ width: entry.contentRect.width });
      chart.timeScale().fitContent();
    });
    resize.observe(target.current);
    return () => { resize.disconnect(); chartState.current = null; chart.remove(); };
  }, [instrument.symbol, instrument.exchange]);
  useEffect(() => {
    const state = chartState.current;
    if (!state || !query.data) return;
    state.series.setData(query.data.map(point => ({ ...point, time: point.time as UTCTimestamp })));
    if (!state.fitted) { state.chart.timeScale().fitContent(); state.fitted = true; }
  }, [query.data, instrument.symbol, instrument.exchange]);
  return <section className="rounded-xl border border-border bg-card p-4 sm:p-5">
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
      <div><h2 className="font-semibold">{instrument.name}</h2><p className="text-xs text-muted-foreground">Synthetic price history · Two hours · Chart times in UTC</p></div>
      <span className="text-lg font-semibold tabular-nums">{money(instrument.ltp)}</span>
    </div>
    {query.isLoading && <p className="text-sm text-muted-foreground">Loading demo chart…</p>}
    {query.isError && <p role="alert" className="text-sm text-destructive">{errorMessage(query.error)}</p>}
    <div ref={target} className="h-[230px] w-full bg-card text-muted-foreground" aria-label={instrument.name + " synthetic price chart"} />
  </section>;
}

export default function Dashboard() {
  const [group, setGroup] = useState("All markets");
  const [chartSymbol, setChartSymbol] = useState("NIFTY-DEMO-FUT");
  const [ticket, setTicket] = useState<{ instrument: Instrument; action: "BUY" | "SELL" } | null>(null);
  const client = useQueryClient();
  const market = useQuery({
    queryKey: ["paper-market"], queryFn: async () => (await api.get<Market>("/web/paper/market")).data,
    refetchInterval: 2000, retry: false,
  });
  const funds = useQuery({ queryKey: ["dashboard"], queryFn: getDashboard, refetchInterval: 3000 });
  const positions = useQuery({ queryKey: ["positions"], queryFn: getPositions, refetchInterval: 3000 });
  const online = useSyncExternalStore(onlineManager.subscribe.bind(onlineManager), onlineManager.isOnline.bind(onlineManager), () => true);
  const now = useNow();
  const pricesPaused = !online || market.fetchStatus === "paused" || !market.dataUpdatedAt || now - market.dataUpdatedAt > 6000;
  const rows = market.data?.instruments ?? [];
  const groups = ["All markets", ...new Set(rows.map(row => row.group))];
  const activeGroup = groups.includes(group) ? group : "All markets";
  const selected = rows.find(row => row.symbol === chartSymbol) ?? rows[0];
  const active = positions.data?.filter(row => row.quantity !== 0) ?? [];
  const refreshBooks = () => { for (const key of ["dashboard", "positions", "orderbook", "tradebook"]) void client.invalidateQueries({ queryKey: [key] }); };
  return <div className="space-y-6">
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div><h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Trading desk</h1>
        <p className="mt-1 text-sm text-muted-foreground">Practice a trade, track your position, and build confidence.</p></div>
      <span className="text-xs text-muted-foreground">{pricesPaused ? "Demo prices paused" : "Demo feed · Updates every 2 seconds"}</span>
    </div>
    {pricesPaused && market.data && <p role="alert" className="rounded-lg border border-border bg-muted p-3 text-sm">Prices paused — reconnecting. New orders are unavailable until fresh prices return.</p>}
    {(funds.isError || market.isError || positions.isError) && <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
      {errorMessage(funds.error ?? market.error ?? positions.error)}
      <Button className="ml-3" size="sm" variant="outline" onClick={() => { void funds.refetch(); void market.refetch(); void positions.refetch(); }}>Retry</Button>
    </div>}
    <dl className="grid grid-cols-2 gap-x-5 gap-y-5 rounded-xl border border-border bg-card p-5 lg:grid-cols-4">
      {[
        ["Available virtual funds", funds.data?.availablecash],
        ["Margin in use", funds.data?.utiliseddebits],
        ["Open P&L", funds.data?.m2munrealized],
        ["Net realized P&L", funds.data?.m2mrealized],
      ].map(([label, value]) => <div key={String(label)}>
        <dt className="text-xs text-muted-foreground">{label}</dt>
        <dd className={cn("mt-2 text-xl font-semibold tracking-tight tabular-nums sm:text-2xl",
          String(label).includes("P&L") && typeof value === "number" && (value < 0 ? "text-red-700" : value > 0 ? "text-emerald-700" : ""))}>
          {typeof value === "number" ? money(value) : "—"}
        </dd>
      </div>)}
    </dl>
    {funds.data && <p className="text-sm text-muted-foreground">Brokerage paid since last reset: {money(funds.data.brokerage_paid)} · Realized P&L includes these charges.</p>}
    <section className="rounded-xl border border-border bg-card">
      <div className="p-4 sm:p-5"><h2 className="font-semibold">Market watch</h2>
        <p className="mt-1 text-xs text-muted-foreground">Sample contracts. Select an instrument to view its chart.</p>
        <div role="group" aria-label="Market category" className="mt-4 flex flex-wrap gap-2">
          {groups.map(name => <Button key={name} size="sm" variant={activeGroup === name ? "default" : "outline"} aria-pressed={activeGroup === name} onClick={() => setGroup(name)}>{name}</Button>)}
        </div>
      </div>
      {market.isError && !market.data ? <p role="alert" className="px-5 py-8 text-sm text-destructive">Market watch is unavailable. Use Retry above to reconnect.</p> : market.isLoading ? <p className="px-5 py-8 text-sm text-muted-foreground">Loading demo instruments…</p> :
        <div className="relative overflow-x-auto"><table className="w-full text-sm">
          <caption className="sr-only">Demo instruments and paper order actions</caption>
          <thead className="border-y border-border bg-muted/40 text-xs text-muted-foreground">
            <tr><th className="px-4 py-3 text-left font-medium">Instrument</th><th className="px-3 py-3 text-right font-medium">Demo price</th>
              <th className="hidden px-3 py-3 text-right font-medium sm:table-cell">Change</th><th className="hidden px-3 py-3 text-right font-medium md:table-cell">Demo lot</th>
              <th className="px-4 py-3 text-right font-medium">Paper order</th></tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.length === 0 && !market.isError && <tr><td colSpan={5} className="px-5 py-8 text-muted-foreground">No instruments are enabled. Your existing positions remain available in Positions.</td></tr>}
            {rows.filter(row => activeGroup === "All markets" || row.group === activeGroup).map(row => <tr key={row.symbol} className={cn("hover:bg-muted/30", selected?.symbol === row.symbol && "bg-primary/5")}>
              <td className="px-4 py-3"><button className="text-left font-medium underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-ring" onClick={() => setChartSymbol(row.symbol)}>
                {row.name}<span className="mt-0.5 block text-xs font-normal text-muted-foreground">{row.exchange} · {row.symbol}</span>
              </button></td>
              <td className="whitespace-nowrap px-3 py-3 text-right font-medium tabular-nums">₹{formatPrice(row.ltp)}</td>
              <td className={cn("hidden px-3 py-3 text-right tabular-nums sm:table-cell", row.change_percent < 0 ? "text-red-700" : "text-emerald-700")}>{row.change_percent > 0 ? "+" : ""}{row.change_percent.toFixed(2)}%</td>
              <td className="hidden px-3 py-3 text-right tabular-nums md:table-cell">{row.lot}</td>
              <td className="px-4 py-3"><div className="flex justify-end gap-2">
                <Button size="sm" className="bg-emerald-700 text-white hover:bg-emerald-800" disabled={pricesPaused} aria-label={"Buy " + row.name} onClick={() => setTicket({ instrument: row, action: "BUY" })}>Buy</Button>
                <Button size="sm" variant="outline" disabled={pricesPaused} aria-label={"Sell " + row.name} onClick={() => setTicket({ instrument: row, action: "SELL" })}>Sell</Button>
              </div></td>
            </tr>)}
          </tbody>
        </table></div>}
    </section>
    <section className="rounded-xl border border-border bg-card p-4 sm:p-5">
      <div className="flex items-center justify-between gap-3"><h2 className="font-semibold">Your open positions</h2><Link to="/positions" className="text-sm text-primary underline underline-offset-4">Manage positions</Link></div>
      {positions.isLoading ? <p className="py-6 text-sm text-muted-foreground">Loading positions…</p> : active.length === 0 ?
        <p className="py-6 text-sm text-muted-foreground">Your first filled paper order will appear here. Choose Buy or Sell in Market watch.</p> :
        <ul className="mt-4 divide-y divide-border">{active.map(row => <li key={row.symbol + row.product} className="flex flex-wrap justify-between gap-2 py-3 text-sm">
          <div><span className="font-medium">{row.symbol}</span><span className="ml-2 text-muted-foreground">{row.quantity} units · {row.product}</span></div>
          <span className={cn("font-semibold tabular-nums", row.pnl < 0 ? "text-red-700" : "text-emerald-700")}>{money(row.pnl)}</span>
        </li>)}</ul>}
    </section>
    {selected && <PriceChart instrument={selected} />}
    <ReferencePrices />
    {ticket && <PlaceOrderDialog open onOpenChange={open => { if (!open) setTicket(null); }} symbol={ticket.instrument.symbol}
      exchange={ticket.instrument.exchange} action={ticket.action} ltp={ticket.instrument.ltp}
      lotSize={ticket.instrument.lot} tickSize={ticket.instrument.tick} strategy="PaperDesk" onSuccess={refreshBooks} disabled={pricesPaused} />}
  </div>;
}
