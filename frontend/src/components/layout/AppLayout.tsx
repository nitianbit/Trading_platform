import { NavLink, Outlet, Form } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { LogOut, ChartNoAxesCombined } from "lucide-react";

const links = [["/dashboard", "Trading desk"], ["/orderbook", "Orders"], ["/positions", "Positions"], ["/tradebook", "Trades"], ["/sandbox/mypnl", "P&L history"]];
export function AppLayout() {
  const { user } = useAuth();
  return <div className="min-h-screen bg-background text-foreground">
    <header className="border-b border-border bg-card">
      <div className="mx-auto flex max-w-[1440px] items-center justify-between gap-4 px-4 py-4 sm:px-6">
        <NavLink to="/dashboard" className="inline-flex items-center gap-2.5 font-semibold tracking-tight">
          <ChartNoAxesCombined className="size-6 text-primary" aria-hidden /><span>DHK Paper</span>
        </NavLink>
        <div className="flex items-center gap-3">
          <span className="rounded-md bg-primary/10 px-2.5 py-1 text-xs font-semibold text-primary">Paper only</span>
          <span className="hidden text-sm text-muted-foreground sm:inline">{user?.username}</span>
          <Form method="post" action="/logout"><Button type="submit" variant="ghost" size="sm">
            <LogOut className="size-4" aria-hidden /><span>Sign out</span>
          </Button></Form>
        </div>
      </div>
      <nav aria-label="Main navigation" className="mx-auto flex max-w-[1440px] gap-1 overflow-x-auto px-4 sm:px-6">
        {[...links, ...(user?.role !== "user" ? [["/admin", user?.is_admin ? "Super Admin" : "Broker"], ["/customers", "Users"]] : []), ...(user?.is_admin ? [["/sandbox", "Paper settings"]] : [])].map(([to, label]) =>
          <NavLink key={to} to={to} className={({ isActive }) => cn(
            "shrink-0 border-b-2 px-3 py-3 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-ring",
            isActive ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground",
          )}>{label}</NavLink>)}
      </nav>
    </header>
    <div className="border-b border-border bg-muted/50 px-4 py-2 text-center text-xs leading-relaxed text-muted-foreground">
      Paper fills use synthetic prices · Public reference prices labeled separately · Virtual funds
    </div>
    <main className="mx-auto min-w-0 w-full max-w-[1440px] px-4 py-6 sm:px-6 sm:py-8"><Outlet /></main>
    <footer className="mx-auto flex max-w-[1440px] flex-wrap justify-between gap-2 px-4 py-6 text-xs text-muted-foreground sm:px-6">
      <span>Demo contracts use virtual INR. Public references use USD. All orders stay inside DHK Paper.</span>
      <a href={import.meta.env.PROD ? "/source.tar.gz" : "https://github.com/marketcalls/openbull"} className="underline underline-offset-4">Source · Built on OpenBull · AGPL-3.0</a>
    </footer>
  </div>;
}
