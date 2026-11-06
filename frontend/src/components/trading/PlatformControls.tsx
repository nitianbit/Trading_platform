import { useCallback } from "react";
import { useBlocker, useBeforeUnload } from "react-router-dom";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useState } from "react";
import type { FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/config/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { errorMessage } from "@/lib/apiError";

import { getPlatformSettings } from "@/api/paper";
import type { PlatformSettings } from "@/api/paper";

const toggle = (values: string[], key: string) => values.includes(key) ? values.filter(value => value !== key) : [...values, key];

function PolicyEditor({ settings }: { settings: PlatformSettings }) {
  const [policy, setPolicy] = useState(settings.policy);
  const [baseline, setBaseline] = useState(settings.policy);
  const dirty = JSON.stringify(policy) !== JSON.stringify(baseline);
  const blocker = useBlocker(dirty);
  useBeforeUnload(useCallback(event => { if (dirty) { event.preventDefault(); event.returnValue = ""; } }, [dirty]));
  const [revision, setRevision] = useState(settings.revision);
  const [conflict, setConflict] = useState(false);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const client = useQueryClient();
  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setPending(true); setMessage(""); setError("");
    try {
      const { data } = await api.put("/web/paper/settings", { ...policy, revision });
      setPolicy(data.policy); setBaseline(data.policy); setRevision(data.revision);
      setMessage("Platform controls saved.");
      for (const key of ["paper-settings", "paper-market", "reference-prices", "paper-users"]) {
        void client.invalidateQueries({ queryKey: [key] });
      }
    } catch (err) {
      setError(errorMessage(err));
      if ((err as { response?: { status?: number } }).response?.status === 409) setConflict(true);
    }
    finally { setPending(false); }
  };
  return <><form onSubmit={save} className="mt-5 space-y-6">
    <fieldset disabled={pending} className="min-w-0 space-y-6">
      <div className="max-w-lg space-y-2">
        <Label htmlFor="max-customers">Maximum customer accounts</Label>
        <Input id="max-customers" type="number" min={0} max={2147483647} step={1}
          value={policy.max_customers ?? ""} placeholder="Unlimited" aria-describedby="capacity-help"
          onChange={event => setPolicy({ ...policy, max_customers: event.target.value === "" ? null : Number(event.target.value) })} />
        <p id="capacity-help" className="text-xs leading-relaxed text-muted-foreground">{settings.customer_count} customer accounts now. Leave blank for unlimited; 0 pauses creation. Super Admin and broker accounts do not count. Lowering the limit preserves existing accounts and their access.</p>
      </div>
      <fieldset className="space-y-4 border-t border-border pt-5">
        <legend className="float-left mb-4 w-full font-medium">Markets and instruments</legend>
        <p className="clear-both text-xs leading-relaxed text-muted-foreground">Off removes instruments from Market watch and blocks new entries through every order API. Existing positions can still be reduced or closed. Pending opening orders are rejected at their next fill attempt.</p>
        <div className="grid gap-x-8 gap-y-6 md:grid-cols-2 lg:grid-cols-3">
          {settings.groups.map(group => {
            const enabled = !policy.disabled_groups.includes(group);
            const id = "market-" + group.replaceAll(" ", "-");
            return <div key={group}>
              <div className="flex items-center justify-between gap-3 border-b border-border pb-3">
                <Label htmlFor={id} className="font-semibold">{group}</Label>
                <Switch id={id} checked={enabled} onCheckedChange={() => setPolicy({ ...policy, disabled_groups: toggle(policy.disabled_groups, group) })} />
              </div>
              <ul className="mt-2 space-y-1">{settings.instruments.filter(row => row.group === group).map(row => {
                const key = row.exchange + ":" + row.symbol;
                return <li key={key} className="flex min-h-11 items-center justify-between gap-3 py-1">
                  <Label htmlFor={key} className={enabled ? "text-sm font-normal" : "text-sm font-normal text-muted-foreground"}>{row.name}</Label>
                  <Switch id={key} disabled={!enabled} checked={enabled && !policy.disabled_instruments.includes(key)}
                    onCheckedChange={() => setPolicy({ ...policy, disabled_instruments: toggle(policy.disabled_instruments, key) })} />
                </li>;
              })}</ul>
            </div>;
          })}
        </div>
      </fieldset>
      <fieldset className="space-y-4 border-t border-border pt-5">
        <legend className="float-left mb-4 w-full font-medium">Public reference prices</legend>
        <div className="clear-both flex items-center justify-between gap-4">
          <div><Label htmlFor="public-quotes">Show free public feed</Label>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">Gold API · USD reference prices · About 30-second updates · No API key</p></div>
          <Switch id="public-quotes" checked={policy.public_feed_enabled} onCheckedChange={checked => setPolicy({ ...policy, public_feed_enabled: checked })} />
        </div>
        <p className="text-xs leading-relaxed text-muted-foreground">Reference prices are separate from demo contracts and do not price paper fills. MCX, NSE, BSE, MSE and crude exchange feeds are not connected. <a href="https://gold-api.com/terms" target="_blank" rel="noreferrer" className="underline underline-offset-4">Provider terms</a></p>
        <div className="grid gap-x-8 sm:grid-cols-2 lg:grid-cols-3">{settings.reference_assets.map(asset =>
          <div key={asset.symbol} className="flex min-h-11 items-center justify-between gap-3 py-1">
            <Label htmlFor={"reference-" + asset.symbol} className="font-normal">{asset.name}</Label>
            <Switch id={"reference-" + asset.symbol} disabled={!policy.public_feed_enabled}
              checked={policy.public_feed_enabled && !policy.disabled_reference_assets.includes(asset.symbol)}
              onCheckedChange={() => setPolicy({ ...policy, disabled_reference_assets: toggle(policy.disabled_reference_assets, asset.symbol) })} />
          </div>)}</div>
      </fieldset>
    </fieldset>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {message && <p role="status" className="text-sm text-primary">{message}</p>}
    {conflict && <Button type="button" variant="outline" disabled={pending} onClick={async () => {
      setPending(true);
      try {
        const latest = await getPlatformSettings();
        setPolicy(latest.policy); setBaseline(latest.policy); setRevision(latest.revision); setConflict(false); setError("");
        client.setQueryData(["paper-settings"], latest);
        setMessage("Latest controls loaded. Review them before saving.");
      } catch (err) { setError(errorMessage(err)); }
      finally { setPending(false); }
    }}>Reload latest controls</Button>}
    <Button type="submit" disabled={pending || conflict}>{pending ? "Saving…" : "Save platform controls"}</Button>
  </form>
    <ConfirmDialog open={blocker.state === "blocked"} title="Discard unsaved controls?"
      description="Your platform controls have unsaved changes. Leave this page and discard them, or keep editing."
      confirmLabel="Discard and leave" cancelLabel="Keep editing" variant="destructive"
      onConfirm={() => { if (blocker.state === "blocked") blocker.proceed(); }}
      onOpenChange={open => { if (!open && blocker.state === "blocked") blocker.reset(); }} />
  </>;
}

export function PlatformControls() {
  const query = useQuery({ queryKey: ["paper-settings"], queryFn: getPlatformSettings, refetchOnWindowFocus: false });
  return <section id="platform-controls" className="rounded-xl border border-border bg-card p-5">
    <h2 className="font-semibold">Platform controls</h2>
    <p className="mt-1 text-sm text-muted-foreground">Choose what customers see and manage account capacity.</p>
    {query.isLoading ? <p role="status" className="mt-4 text-sm text-muted-foreground">Loading controls…</p> : query.isError ?
      <div role="alert" className="mt-4 space-y-3"><p className="text-sm text-destructive">{errorMessage(query.error)}</p><Button variant="outline" onClick={() => void query.refetch()}>Try again</Button></div> :
      query.data && <PolicyEditor settings={query.data} />}
  </section>;
}
