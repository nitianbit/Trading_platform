// Own disposable Chromium contexts only. Never use an owner's browser profile.
import { chromium } from "playwright";
import { preview } from "vite";
import { readFile, mkdir } from "node:fs/promises";
import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";

assert.match(process.env.DHK_TEST_DB_NAME ?? "", /^dhk_test_[a-f0-9]+$/);
const target = process.env.DHK_QA_URL;
assert.match(target ?? "", /^http:\/\/127\.0\.0\.1:\d+$/);
const accounts = JSON.parse(await readFile(process.env.DHK_QA_RECORD, "utf8"));
const proxy = Object.fromEntries(["/auth/", "/web/", "/api/", "/health"].map(path => [path, { target, changeOrigin: true }]));
const app = await preview({ preview: { host: "127.0.0.1", port: 0, strictPort: false, proxy } });
const base = `http://127.0.0.1:${app.httpServer.address().port}`;
const output = process.env.DHK_BROWSER_ARTIFACTS;
if (output) await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
async function screenshot(page, name) { if (output) await page.screenshot({ path: `${output}/${name}.png`, fullPage: true, animations: "disabled" }); }
async function assertContrast(locator, label) {
  const ratio = await locator.evaluate(element => {
    const canvas = document.createElement("canvas"); canvas.width = canvas.height = 1;
    const context = canvas.getContext("2d");
    const rgba = color => {
      context.clearRect(0, 0, 1, 1); context.fillStyle = color; context.fillRect(0, 0, 1, 1);
      const [r,g,b,a] = context.getImageData(0,0,1,1).data; return [r,g,b,a/255];
    };
    const over = (top, bottom) => top.slice(0,3).map((v,i) => v*top[3] + bottom[i]*(1-top[3]));
    const ancestors = []; for (let node=element; node; node=node.parentElement) ancestors.unshift(node);
    const background = ancestors.reduce((behind,node) => over(rgba(getComputedStyle(node).backgroundColor),behind),[255,255,255]);
    const foreground = over(rgba(getComputedStyle(element).color),background);
    const luminance = rgb => rgb.map(v => v/255).map(v => v<=0.04045 ? v/12.92 : ((v+0.055)/1.055)**2.4).reduce((v,c,i) => v+c*[0.2126,0.7152,0.0722][i],0);
    const a = luminance(foreground), b = luminance(background);
    return (Math.max(a,b)+0.05)/(Math.min(a,b)+0.05);
  });
  assert(ratio >= 4.5, `${label} contrast ${ratio.toFixed(2)}:1 is below 4.5:1`);
}
async function signIn(page, account, destination) {
  await page.goto(base + "/login");
  await page.getByLabel("Username", { exact: true }).fill(account.username);
  await page.getByLabel("Password", { exact: true }).fill(account.password);
  const response = page.waitForResponse(response => response.url().endsWith("/auth/login") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Sign In", exact: true }).click();
  assert.equal((await response).status(), 200, "Browser sign-in request must succeed");
  await page.waitForURL(base + destination);
  await page.getByRole("heading", { level: 1 }).waitFor();
  assert.equal(new URL(page.url()).pathname, destination);
}
try {
  for (const [size, viewport] of [["desktop", { width: 1440, height: 900 }], ["mobile", { width: 390, height: 844 }]]) {
    let browserUser;
    for (const [role, fixture, destination] of [["admin", accounts.admin, "/admin"], ["broker", accounts.brokers[0], "/admin"], ["user", accounts.customers[0], "/dashboard"]]) {
      const account = role === "user" ? browserUser : fixture;
      const context = await browser.newContext({ viewport });
      const page = await context.newPage(); page.setDefaultTimeout(10000);
      await signIn(page, account, destination);
      if (role === "admin") {
        await page.getByRole("heading", { name: "Brokers", exact: true }).waitFor();
        await page.getByText("Loading brokers…", { exact: true }).waitFor({ state: "hidden" });
        await page.getByText("Loading controls…", { exact: true }).waitFor({ state: "hidden" });
      }
      if (role !== "user") {
        await page.getByLabel("Filter by user", { exact: true }).selectOption("");
        await page.getByText("Loading earnings…", { exact: true }).waitFor({ state: "hidden" });
        await page.getByText("Loading user trades…", { exact: true }).waitFor({ state: "hidden" });
      }
      if (role === "user") {
        await page.getByRole("button", { name: "Buy Gold Futures", exact: true }).waitFor();
        await page.getByText(/Brokerage paid since last reset:/).waitFor();
        await page.getByText("Connecting to public prices…", { exact: true }).waitFor({ state: "hidden" });
      }
      const fits = await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1);
      if (!fits) {
        await screenshot(page, `overflow-${role}-${size}`);
        console.error(await page.evaluate(() => [...document.querySelectorAll("body *")].filter(element => {
          const box = element.getBoundingClientRect();
          if (box.right <= innerWidth + 1) return false;
          for (let parent = element.parentElement; parent && parent.tagName !== "MAIN"; parent = parent.parentElement) {
            if (["auto", "scroll"].includes(getComputedStyle(parent).overflowX)) return false;
          }
          return true;
        }).slice(0,12).map(element => ({tag:element.tagName, class:element.className, width:element.getBoundingClientRect().width}))));
      }
      if (!fits) console.error(await page.evaluate(() => ({ width:innerWidth, documentWidth:document.documentElement.scrollWidth, overflow:[...document.querySelectorAll("body *")].filter(e => e.scrollWidth > e.clientWidth + 1).slice(0,15).map(e=>({tag:e.tagName,cls:e.className,width:e.clientWidth,scroll:e.scrollWidth,overflow:getComputedStyle(e).overflowX})) })));
      assert(fits, `${role} overflows on ${size}`);
      await screenshot(page, `${role}-${size}`);
      if (role === "admin") {
        const cap = page.getByLabel("Maximum customer accounts", { exact: true });
        const snapshot = await (await context.request.get(base + "/web/paper/settings")).json();
        await cap.fill("100000");
        const outsideSave = await context.request.put(base + "/web/paper/settings", {data:{...snapshot.policy,revision:snapshot.revision}});
        assert.equal(outsideSave.status(),200);
        const otherBroker = await browser.newContext();
        const other = accounts.brokers[1];
        assert.equal((await otherBroker.request.post(base+"/auth/login",{data:{username:other.username,password:other.password}})).status(),200);
        const suffix = randomBytes(4).toString("hex");
        assert.equal((await otherBroker.request.post(base+"/web/paper/users",{data:{username:"qa_reload_"+suffix,email:suffix+"@example.com"}})).status(),201);
        await otherBroker.close();
        await page.getByRole("button",{name:"Save platform controls",exact:true}).click();
        await page.getByRole("button",{name:"Reload latest controls",exact:true}).click();
        await page.getByText(new RegExp(`${snapshot.customer_count+1} customer accounts now`)).waitFor();
        assert.equal(await cap.inputValue(), snapshot.policy.max_customers===null?"":String(snapshot.policy.max_customers));

        await cap.fill("100000");
        await page.getByRole("link", { name: "Trading desk", exact: true }).click();
        const guard = page.getByRole("dialog");
        await guard.getByRole("heading", { name: "Discard unsaved controls?", exact: true }).waitFor();
        await screenshot(page, `unsaved-controls-${size}`);
        await guard.getByRole("button", { name: "Keep editing", exact: true }).click();
        assert.equal(await cap.inputValue(), "100000");
        await page.getByRole("button", { name: "Sign out", exact: true }).click();
        await guard.getByRole("heading", { name: "Discard unsaved controls?", exact: true }).waitFor();
        await guard.getByRole("button", { name: "Keep editing", exact: true }).click();
        assert.equal((await context.request.get(base + "/auth/me")).status(), 200);
        await page.getByRole("link", { name: "Trading desk", exact: true }).click();
        await guard.getByRole("button", { name: "Discard and leave", exact: true }).click();
        await page.waitForURL(base + "/dashboard");
        await page.goto(base + "/admin");
      }

      if (role === "user") {
        await context.setOffline(true);
        await page.getByRole("alert").filter({ hasText: "Prices paused — reconnecting" }).waitFor();
        assert(await page.getByRole("button", { name: "Buy USD/INR Futures", exact: true }).isDisabled());
        await screenshot(page, `offline-${size}`);
        await context.setOffline(false);
        await page.getByRole("alert").filter({ hasText: "Prices paused — reconnecting" }).waitFor({ state: "hidden" });
        await page.getByRole("button", { name: "Buy USD/INR Futures", exact: true }).click();
        const dialog = page.getByRole("dialog"); await dialog.waitFor();
        await dialog.getByLabel("Price Type", { exact: true }).selectOption("LIMIT");
        const price = dialog.getByLabel("Price", { exact: true });
        await price.fill("85.0125"); await price.press("Tab");
        assert.equal(await price.inputValue(), "85.0125");
        await dialog.getByRole("button", { name: "Increase price by one tick", exact: true }).click();
        assert.equal(await price.inputValue(), "85.015");
        await dialog.getByRole("button", { name: "Decrease price by one tick", exact: true }).click();
        assert.equal(await price.inputValue(), "85.0125");
        await dialog.getByLabel("Quantity", { exact: true }).focus();
        for (let i = 0; i < 25; i++) {
          await page.keyboard.press("Tab");
          assert(await page.evaluate(() => !!document.activeElement?.closest('[role="dialog"]')), `focus escaped ticket at Tab ${i+1}`);
        }
        await assertContrast(dialog.getByRole("button", { name: "BUY", exact: true }), "Ticket BUY");
        await screenshot(page, `ticket-${size}`);
        await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
        await page.route("**/web/paper/market", route => route.fulfill({ status: 503, contentType: "application/json", body: '{"detail":"Market unavailable in regression test"}' }));
        await page.reload();
        await page.getByRole("alert").filter({ hasText: "Market watch is unavailable" }).waitFor();
        assert.equal(await page.getByText("Loading demo instruments…").count(), 0);
        await assertContrast(page.getByRole("alert").filter({ hasText: "Market unavailable in regression test" }), "Market failure alert");
        await screenshot(page, `market-error-${size}`);
      }
      if (role === "broker") {
        const suffix = randomBytes(6).toString("hex");
        const account = { username: "qa_browser_" + suffix, email: suffix + "@example.com", password: randomBytes(24).toString("hex") };
        const response = await context.request.post(base + "/web/paper/users", { data: { username: account.username, email: account.email } });
        assert.equal(response.status(), 201);
        const invitation = await response.json();
        const invited = await browser.newContext({ viewport }); const activation = await invited.newPage();
        await activation.goto(base + "/invite" + new URL(invitation.invitation_url).hash);
        await activation.getByLabel("Choose a password", { exact: true }).waitFor();
        assert.equal(new URL(activation.url()).pathname, "/invite");
        await activation.getByLabel("Choose a password", { exact: true }).fill(account.password);
        await activation.getByLabel("Confirm password", { exact: true }).fill(account.password);
        await activation.getByRole("button", { name: "Activate account", exact: true }).click();
        await activation.getByRole("heading", { name: "Account activated", exact: true }).waitFor();
        await screenshot(activation, `invitation-activated-${size}`);
        assert.equal(new URL(activation.url()).hash, "");
        browserUser = account;
        await signIn(activation, account, "/dashboard");
        const apiKeyResponse = await invited.request.get(base + "/web/apikey");
        const { api_key } = await apiKeyResponse.json();
        const placed = await invited.request.post(base + "/api/v1/placeorder", { data: { apikey: api_key, symbol: "NIFTY-DEMO-FUT", exchange: "NFO", action: "BUY", quantity: 50, pricetype: "MARKET", product: "NRML" } });
        assert.equal(placed.status(), 200);
        await activation.goto(base + "/positions");
        const reduce = activation.getByRole("button", { name: "Reduce / Close", exact: true });
        await reduce.waitFor();
        const box = await reduce.boundingBox();
        assert(box && box.x >= 0 && box.x + box.width <= viewport.width, "Position exit must be visible without sideways scrolling");
        await reduce.click();
        const exitDialog = activation.getByRole("dialog");
        await exitDialog.getByLabel("Quantity to close", { exact: true }).fill("25");
        await exitDialog.getByText(/25 units remain open/).waitFor();
        await assertContrast(exitDialog.getByRole("button", { name: "Reduce or close position", exact: true }), "Partial exit confirmation");
        await screenshot(activation, `partial-position-${size}`);
        await exitDialog.getByRole("button", { name: "Reduce or close position", exact: true }).click();
        await activation.getByRole("cell", { name: "25", exact: true }).waitFor();
        await exitDialog.waitFor({ state: "hidden" });
        await screenshot(activation, `position-result-${size}`);
        const positionResponse = await invited.request.get(base + "/web/positions");
        const positionRows = (await positionResponse.json()).data;
        assert.equal(positionRows.find(row => row.symbol === "NIFTY-DEMO-FUT").quantity, 25);
        await activation.goto(base + "/tradebook");
        await activation.getByRole("cell", { name: "NIFTY-DEMO-FUT", exact: true }).first().waitFor();
        await screenshot(activation, `tradebook-${size}`);
        await invited.close();
      }
      await page.getByRole("button", { name: "Sign out", exact: true }).click();
      await page.waitForURL(base + "/login");
      // A second login in this mounted app covers logout -> login cache lifetime.
      if (size === "desktop") await signIn(page, account, destination);
      await context.close();
    }
    const context = await browser.newContext({ viewport }); const page = await context.newPage();
    await page.goto(base + "/invite#token=" + "x".repeat(43));
    await page.getByRole("alert").waitFor();
    assert.equal(new URL(page.url()).pathname, "/invite");
    await screenshot(page, `invalid-invitation-${size}`); await context.close();
  }
  console.log("PASS: desktop/mobile invitation activation, all three role logins, logout/login, modal keyboard focus, 0.0025 tick prices, market failure and page overflow");
} finally { await browser.close(); await new Promise(resolve => app.httpServer.close(resolve)); }
