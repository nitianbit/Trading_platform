import test from "node:test";
import assert from "node:assert/strict";
import { QueryClient, QueryObserver } from "@tanstack/react-query";
import { replaceSession, authKey } from "../src/lib/authSession.ts";
import { roundToTick, adjustPrice } from "../src/lib/price.ts";
import api from "../src/config/api.ts";

test("login, logout and account switching preserve the mounted guard and clear private books", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const observer = new QueryObserver(client, { queryKey: authKey, queryFn: async () => null });
  const stop = observer.subscribe(() => {});
  await observer.refetch();
  const first = { id: 1, username: "first", role: "user" as const, broker_id: 3, broker_username: "broker", email: "first@example.com", is_admin: false, broker: null, broker_authenticated: false, paper_only: true };
  const second = { ...first, id: 2, username: "second", role: "broker" as const, broker_id: null, broker_username: null };
  client.setQueryData(["positions"], [{ owner: 1 }]);
  await replaceSession(client, first);
  assert.deepEqual(observer.getCurrentResult().data, first);
  assert.equal(client.getQueryData(["positions"]), undefined);
  client.setQueryData(["tradebook"], [{ owner: 1 }]);
  await replaceSession(client, null);
  assert.equal(observer.getCurrentResult().data, null);
  assert.equal(client.getQueryData(["tradebook"]), undefined);
  await replaceSession(client, second);
  assert.deepEqual(observer.getCurrentResult().data, second);
  stop(); client.clear();
});

test("a late private request cannot refill another account's cache", async () => {
  const client = new QueryClient();
  let resolve!: (value: string) => void;
  const pending = client.fetchQuery({ queryKey: ["positions"], queryFn: () => new Promise<string>(r => { resolve = r; }) }).catch(() => {});
  await replaceSession(client, null);
  resolve("previous account"); await pending;
  assert.equal(client.getQueryData(["positions"]), undefined);
  client.clear();
});

test("signed-out invitation checks retain their fragment; private pages redirect", async () => {
  for (const path of ["/invite", "/login", "/dashboard"]) {
    const location = { pathname: path, href: path + "#token=test-only" };
    Object.defineProperty(globalThis, "window", { value: { location }, configurable: true });
    await assert.rejects(api.get("/auth/me", { adapter: async () => { throw { response: { status: 401 } }; } }));
    assert.equal(location.href, path === "/dashboard" ? "/login" : path + "#token=test-only");
  }
});

test("currency tick entry and both price buttons retain all four decimals", () => {
  assert.equal(roundToTick(85.0125, 0.0025), 85.0125);
  assert.equal(adjustPrice(85.0125, 0.0025, "up"), 85.015);
  assert.equal(adjustPrice(85.0125, 0.0025, "down"), 85.01);
  assert.equal(adjustPrice(0, 0.0025, "down"), 0);
});
