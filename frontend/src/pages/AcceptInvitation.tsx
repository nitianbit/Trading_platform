import { useState } from "react";
import type { FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import api from "@/config/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/apiError";

interface Preview { username: string; email: string; role: string; broker_username: string | null }
export default function AcceptInvitation() {
  const [token] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get("token") ?? "");
  const [pending, setPending] = useState(false);
  const [complete, setComplete] = useState(false);
  const [error, setError] = useState("");
  const query = useQuery({ queryKey: ["invitation", token], enabled: !!token, retry: false,
    queryFn: async () => (await api.post<Preview>("/auth/invite/preview", { token })).data });
  const accept = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    if (values.get("password") !== values.get("confirmation")) { setError("Passwords do not match."); return; }
    setPending(true); setError("");
    try {
      await api.post("/auth/invite/accept", { token, password: values.get("password") });
      window.history.replaceState(null, "", "/invite");
      setComplete(true);
    } catch (err) { setError(errorMessage(err)); } finally { setPending(false); }
  };
  return <main className="flex min-h-screen items-center justify-center bg-background px-4 py-8"><section className="w-full max-w-md space-y-5 rounded-xl border border-border bg-card p-6">
    <h1 className="text-2xl font-semibold tracking-tight">{complete ? "Account activated" : "Join DHK Paper"}</h1>
    {complete ? <><p role="status" className="text-sm text-muted-foreground">Your password is set. Sign in with your username. If another account is already signed in, sign out of it first.</p><Link to="/login" className="text-primary underline underline-offset-4">Go to sign in</Link></> :
      !token ? <p role="alert" className="text-sm text-destructive">This page needs an invitation link. Ask your broker for one.</p> : query.isLoading ?
      <p role="status" className="text-sm text-muted-foreground">Checking your invitation…</p> : query.isError ?
      <p role="alert" className="text-sm text-destructive">{errorMessage(query.error)}</p> : query.data && <>
        <div className="space-y-2 text-sm"><p>Username: <strong>{query.data.username}</strong></p><p className="break-words text-muted-foreground">{query.data.email}</p>
          <p className="leading-relaxed text-muted-foreground">{query.data.role === "broker" ? "You have been invited as a broker. After activation, you can create and manage your own users." : `Your broker is ${query.data.broker_username}. Your account remains permanently under this broker.`}</p></div>
        <form onSubmit={accept} className="space-y-4">
          <div className="space-y-2"><Label htmlFor="invite-password">Choose a password</Label><Input id="invite-password" name="password" type="password" minLength={8} maxLength={128} autoComplete="new-password" required /></div>
          <div className="space-y-2"><Label htmlFor="invite-confirmation">Confirm password</Label><Input id="invite-confirmation" name="confirmation" type="password" minLength={8} maxLength={128} autoComplete="new-password" required /></div>
          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
          <Button type="submit" disabled={pending} className="w-full">{pending ? "Activating…" : "Activate account"}</Button>
        </form>
      </>}
    <p className="text-xs leading-relaxed text-muted-foreground">Virtual funds and paper trades only.</p>
  </section></main>;
}
