# Market data and platform controls

Verified against provider documentation on 5 November 2026. Paper fills remain platform-owned and synthetic.

## What is connected

Gold API's no-key public price endpoint supplies Gold (XAU), Silver (XAG), Platinum (XPT), Palladium (XPD), Copper (HG), Bitcoin and Ethereum as **reference prices only**. Responses include their source timestamp and USD currency. Precious metals use troy ounces; the provider does not document the copper unit in its free endpoint documentation, so the UI explicitly leaves it as the provider's quoted unit. There is no INR/MCX mapping, currency conversion or exchange contract metadata inferred from these prices.

[API documentation](https://gold-api.com/llms.txt) describes 30-second updates and requests cached for at least 30 seconds. The shared backend fetches sequentially, spaces calls by 1.1 seconds and waits 30 seconds between passes. Customers never trigger upstream requests. [Provider terms](https://gold-api.com/terms) permit commercial web-app use. This is a free public service, not a verified open-source server implementation. No paid tier, registration, key or new package is required.

Prices are displayed only when valid and less than 90 seconds old by both provider timestamp and last successful fetch. Failed, missing or stale data is visibly unavailable/stale with no generated fallback. Disabling the feed hides the panel immediately; an in-flight pass may complete before polling stops. Restarting clears the in-memory reference cache. Reference data is never inserted into the paper execution cache.

## What remains demo

17 illustrative contracts span NSE equity/futures/options, BSE futures, MSE currency, MCX, GIFT NIFTY and Global. MCX samples include crude, gold, silver, natural gas, copper, zinc, aluminium and lead. Lot sizes, prices, expiry and margins are illustrative. Sample MSE currency support is not a connection to that exchange. Historical charts remain generated demo history.

No free, documented, redistributable real-time feed for all requested Indian exchange contracts was established. Open-source scraper/SDK code alone does not supply exchange data rights, service availability or contract-master accuracy. Official exchange products are described here:

- [NSE real-time data subscription](https://www.nseindia.com/static/market-data/real-time-data-subscription)
- [BSE market-data tariff](https://www.bseindia.com/downloads1/Information_Products_Pricing_Sheet.pdf)
- [MCX technology and data-feed FAQ](https://beta.mcxindia.com/en/faq/technology-services)
- [MSE data-feed products](https://www.msei.in/Technology/Datafeed-Products)

Live MCX crude and live NSE/BSE/MSE contracts remain unconnected. A data source with documented coverage and permitted multi-user usage is needed before those can be advertised as live. Real broker order modules remain disabled.

## Admin controls

Admin → Platform controls edits persistent settings in `app_settings.paper_platform_policy`. Save applies the complete form. Markets can be disabled as groups and instruments disabled individually; group-off takes priority, and individual choices are retained when a group is restored. Market watch and its chart endpoint omit disabled items. New orders, modifications and fill-time rechecks enforce the same policy, including direct API calls. Existing positions stay visible; only orders that reduce or close the remaining position are permitted. Pending opening orders release reservations and become rejected at their next eligible fill attempt; cancellation remains possible. The demo feed continues for hidden symbols to mark and close existing positions.

The customer limit counts accounts with role `user`, including those awaiting activation; Super Admin and broker accounts are excluded. It does not count simultaneous sessions. Blank means unlimited, zero pauses account creation, and a lower cap never deletes or logs out existing customers. PostgreSQL transaction advisory locking serializes customer creation and policy updates, including the first settings write. Invalid limits and unknown market identifiers are rejected. Only admins can view or save settings. Customer creation is also checked by the server regardless of UI state.

Free reference-feed and per-asset switches are independent of demo market controls. They control reference-price visibility only. Both default on; all demo instruments default enabled; customer capacity defaults unlimited until the administrator chooses a cap.

## Verification

Disposable PostgreSQL regressions cover disabled entry/reversal rejection, valid exits, pending-fill rechecks and partially filled exit modification. Public-feed boundary tests cover quote identity, currency, finite positive values, UTC timestamps, stale data, upstream failure and disabled/hidden assets. HTTP verification covers admin authorization, invalid settings, concurrent admission with one slot remaining, visibility/chart filtering, cap reductions preserving login, and expanded commodity/BSE/MSE demo round trips. Provider availability is checked separately from deterministic tests.

Market-controls verification before the hierarchy extension: 32 tests in the disposable database workflow, 13 HTTP verification groups including new exchange demos and concurrent capacity admission, frontend production build, targeted ESLint and whitespace validation passed. The activated local app returned fresh source-timestamped quotes for all seven public assets; unauthenticated reference access returned 401. Existing user/password/API-key fingerprints and order/trade counts matched before and after activation. The temporary HTTP verification login was removed; other owner sessions were preserved. Static UI detector returned no findings. The independent finish review returned `recapture` because current browser screenshots could not be produced; it did not approve rendered desktop/mobile layout or accessibility. Public deployment remains outstanding.

## Provider check — 6 November 2026

Gold API's [terms](https://gold-api.com/terms), effective 10 September 2026, section 9 permit commercial website/mobile integration and redistribution on third-party sites. Its [API notes](https://gold-api.com/llms.txt) describe the seven free symbols, default USD prices, UTC source timestamps and 30-second updates. The shared feed spaces requests by 1.1 seconds and waits 30 seconds between passes; app request volume does not create additional upstream calls. Repeated failures log once per asset outage and reset after recovery. Provider availability/accuracy is not guaranteed; no MCX/NSE/BSE exchange feed or executable prices are implied. Test captures kept public references disabled, so live reference rendering remains a separate runtime acceptance check.
