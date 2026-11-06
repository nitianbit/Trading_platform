import type { ReactNode } from "react";
import { createBrowserRouter, createRoutesFromElements, RouterProvider, Outlet, redirect, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider, useAuth } from "@/contexts/AuthContext";
import { ThemeProvider } from "@/contexts/ThemeContext";
import { TradingModeProvider } from "@/contexts/TradingModeContext";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppLayout } from "@/components/layout/AppLayout";
import AcceptInvitation from "@/pages/AcceptInvitation";
import Login from "@/pages/Login";
import Setup from "@/pages/Setup";
import Dashboard from "@/pages/Dashboard";
import Admin from "@/pages/Admin";
import Customers from "@/pages/Customers";
import OrderBook from "@/pages/OrderBook";
import TradeBook from "@/pages/TradeBook";
import Positions from "@/pages/Positions";
import Sandbox from "@/pages/Sandbox";
import SandboxMyPnL from "@/pages/SandboxMyPnL";
import NotFound from "@/pages/NotFound";
import { signOut } from "@/lib/signOut";
import { Toaster } from "@/components/ui/sonner";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } });
function AdminOnly({ children }: { children: ReactNode }) { const { user } = useAuth(); return user?.is_admin ? children : <Navigate to="/dashboard" replace />; }
function Private({ children }: { children: ReactNode }) { return <ProtectedRoute>{children}</ProtectedRoute>; }

const router = createBrowserRouter(createRoutesFromElements(
  <Route element={<AuthProvider><TradingModeProvider><Outlet /><Toaster /></TradingModeProvider></AuthProvider>}>
      <Route path="/logout" action={async () => { await signOut(queryClient); return redirect("/login"); }} />
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="/invite" element={<AcceptInvitation />} />
      <Route path="/login" element={<Login />} />
      <Route path="/setup" element={<Setup />} />
      <Route element={<Private><AppLayout /></Private>}>
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/orderbook" element={<OrderBook />} />
        <Route path="/tradebook" element={<TradeBook />} />
        <Route path="/positions" element={<Positions />} />
        <Route path="/admin" element={<Admin />} />
        <Route path="/customers" element={<Customers />} />
        <Route path="/sandbox" element={<AdminOnly><Sandbox /></AdminOnly>} />
        <Route path="/sandbox/mypnl" element={<SandboxMyPnL />} />
      </Route>
      <Route path="*" element={<NotFound />} />
  </Route>
));
export default function App() {
  return <QueryClientProvider client={queryClient}><ThemeProvider><RouterProvider router={router} /></ThemeProvider></QueryClientProvider>;
}
