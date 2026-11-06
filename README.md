# DHK Paper

A browser-based paper-trading platform with **Super Admin → Broker → User** account ownership. The web app, management panels and backend record virtual orders, trades, positions, funds and brokerage earnings inside DHK Paper.

**Current status:** implemented and verified locally. Public deployment remains pending. Execution prices are synthetic; no real exchange orders, deposits, withdrawals or payouts are supported.

## Product overview

| Component | What it provides |
| --- | --- |
| User web app | Trading desk, market watch, paper orders, positions, trade history and virtual P&L. |
| Broker panel | Invitations, access management, account activity and executed trades for the broker's own users; separate virtual brokerage earnings. |
| Super Admin panel | Broker creation, user oversight, broker/global capacity limits, market visibility, reference-feed controls and platform settings. |
| Backend | Authentication, permissions, transactional paper execution, brokerage accounting, market data, streaming, scheduled tasks and operational checks. |

The user and management panels are role-specific screens in the same React web app. The FastAPI backend serves their data and enforces permissions independently of the interface.

## Accounts and onboarding

1. The operator creates the first **Super Admin** using the private setup token.
2. Super Admin creates a **broker invitation** and shares its link privately.
3. The broker activates the account, chooses a password and signs in.
4. The broker creates **user invitations** under that broker account.
5. Each user activates their invitation, chooses a password and signs in normally thereafter.

There is no public signup. New users are created through brokers, and their broker ownership is permanent. Super Admin cannot bypass the hierarchy to create new users directly.

Invitations expire after **48 hours**, can be accepted once, and can be replaced while awaiting activation. Sharing is manual: the platform displays a link to copy; it does not automatically send email or messages. Localhost links work only on the machine running the app; external sharing requires the public deployment and its configured address.

Pre-existing unassigned users keep their accounts. Super Admin can assign them to an active broker once; the platform does not choose a broker automatically. Broker assignment is required before they trade.

Sign-in rules:

- Usernames are 3–80 lowercase letters, digits or underscores; they are stored in lowercase, so `Alice` and `alice` are the same account. Emails are also compared without case.
- Passwords are 8–128 characters.
- Browser sessions expire at **03:00 IST** each day; sign in again afterwards.
- Login attempts are limited to 5 per minute and 25 per hour for each username and address, and 60 per minute per address.
- Each invitation action (create a broker, create a user, replace a link) is limited to 20 per hour per client address.

## Features for users

### Trading desk and market watch

- Browse enabled sample instruments by market category.
- View synthetic prices and price changes, with approximately two-second market-watch updates.
- Select an instrument to view two hours of synthetic price history.
- Open Buy and Sell order tickets from market watch. Offline or stale updates display a paused-price notice and disable order submission until fresh data returns.
- See available virtual funds, margin in use, open P&L, net realized P&L and brokerage paid since the last reset.
- View a separate optional public-reference panel when enabled and data is available.

### Paper orders and positions

- Place **Market, Limit, Stop-Loss Limit and Stop-Loss Market** orders.
- Enter quantity with lot-size guidance and use tick-based price controls, including four-decimal currency ticks.
- View order status, pending/filled quantities and rejection reasons.
- Modify eligible pending orders, cancel individual orders or cancel all open orders.
- View open positions, average prices, current prices and P&L.
- Partially reduce a position, close one position or submit close-all instructions.
- Review the quantity to close and the quantity that will remain before confirming a partial exit.
- Export orders, positions and executed trades to CSV.

Trading remains subject to backend validation for funds, fees, quantity, lot size, ticks, contract expiry, market visibility, supported products and MIS cutoffs. Market orders fill immediately at the synthetic price. Pending orders fill when their conditions are met against the synthetic feed. There are no exchange trading hours or holidays; the only time-based rules are the MIS cutoffs below. An insufficient-funds rejection states the required margin, the estimated 4% brokerage and the available cash.

### Books and account access

- Each user has a separate virtual balance and trading book.
- Default starting capital is **₹1 crore**, subject to Super Admin's sandbox configuration.
- The tradebook shows fills and brokerage for the current trading session.
- Daily P&L history is available once scheduled snapshots exist.
- Position P&L is shown separately from account net realized P&L, which includes brokerage.
- Users cannot create accounts, access manager data, change platform settings or reset their own history/funds.

## Features for brokers

### Own-user management

- Create user invitations under the signed-in broker account.
- View own users and their activation/access status.
- Replace unused invitation links.
- Enable or disable access for own users without deleting their books.
- See current user count and the user limit set by Super Admin.

### Activity and earnings

- View own users' available virtual funds, used margin, realized/open P&L and activity counts.
- Monitor open-position counts, pending-order counts and fill counts.
- Review executed user trades across sessions, filter by user and page through history.
- See user identity, instrument, side, quantity, fill price, trade value, brokerage and recipient credits.
- View the broker's separate lifetime virtual brokerage earnings.

Brokers cannot create brokers, change their own capacity limit, change global policy or access another broker's users, trades or earnings. The activity overview summarizes positions; it is not an interface for placing trades on behalf of users.

## Features for Super Admin

### Broker and user oversight

- Create broker invitations and view broker activation/access status.
- Replace unused broker or user invitations within the management scope.
- Enable or disable broker and user access.
- View users across all brokers and assign eligible legacy users once.
- View account balances, P&L and activity summaries across the platform.
- Review all users' executed trades, with user filtering and history pagination.
- View Super Admin's separate lifetime virtual brokerage earnings.

Disabling a broker blocks access for the broker and its users. Disabling access preserves records; it does not cancel pending orders or close positions, and those pending orders can still fill and incur brokerage. Re-enabled accounts require fresh browser login because prior sessions remain revoked; their existing API keys work again. Existing quote-only sockets are not actively disconnected.

### Capacity controls

- Set the maximum number of user accounts across the platform.
- Set a separate maximum number of users for each broker.
- Pending invitations and disabled users count toward these limits.
- Super Admin and broker accounts do not consume user-account capacity.
- Blank means unlimited; **0 pauses new user creation**.
- Lowering a cap preserves existing accounts and their access.
- The limits apply to registered user accounts, not simultaneous online sessions.

### Market and platform controls

- Enable or disable complete market groups or individual sample instruments.
- Disabled instruments disappear from market watch and reject new exposure through the backend.
- Existing positions can still be reduced or closed.
- Pending opening orders are checked again at execution; they are not automatically cancelled when a switch changes.
- Enable or disable the public-reference panel and individual reference assets. The panel is **on by default** in a new installation. The provider's commercial-use terms were checked on 6 November 2026; availability is not guaranteed. See [data coverage and provider limits](docs/market-data.md).
- Edit supported sandbox parameters, including starting-capital defaults, leverage, session and square-off settings.
- Save platform controls with revision checking: a stale admin tab receives a conflict and must load the latest policy before saving. Unsaved edits prompt before navigation/sign-out; reload refreshes the current account count too.

Sandbox parameters are global simulation settings. Changing a starting-capital default does not provide an immediate per-user credit/top-up feature. Automatic weekly book resets are disabled by default; users have no self-reset control.

Super Admin can reset its own practice book from `/sandbox`. A separate API-only action, `POST /web/sandbox/wipe-all`, resets **every** account's orders, trades, positions and daily P&L to the starting capital. It is destructive and has no confirmation screen. Fee records and manager earnings are kept, so lifetime earnings can afterwards exceed what the remaining trade history shows.

## Permissions at a glance

| Capability | User | Broker | Super Admin |
| --- | --- | --- | --- |
| Trade in own paper book | Yes, with broker assignment | Yes, own practice book | Yes, own practice book |
| Create user invitations | No | Own users | New users must come through brokers |
| Create broker invitations | No | No | Yes |
| Manage user access | No | Own users | All users |
| Manage broker access | No | No | Yes |
| View executed user trades | Own trades | Own users | All users |
| View manager earnings | No | Own broker earnings | Own admin earnings |
| Set broker/global user limits | No | No | Yes |
| Change market/feed settings | No | No | Yes |
| Transfer an assigned user to another broker | No | No | No |

## Brokerage and virtual earnings

Every executed **user buy and user sell** charges **4% of the full executed trade value**:

| Executed trade value | Deducted from user | Broker earnings | Super Admin earnings |
| --- | --- | --- | --- |
| ₹1 | ₹0.04 | ₹0.03 | ₹0.01 |
| ₹100 | ₹4 | ₹3 | ₹1 |
| One Gold sample lot at ₹80,993 (₹80,99,300) | ₹3,23,972 | ₹2,42,979 | ₹80,993 |

- Opening and closing are separate executions; both incur brokerage.
- Futures fees use full executed notional, rather than just the margin blocked. With the default 10× futures margin, each execution's fee equals 40% of the margin blocked.
- Fees are checked when an order is placed or modified but are not reserved while it is pending. If competing orders use the cash first, the fill is rejected without a charge.
- Only filled quantity is charged. Unfilled, cancelled and rejected quantities earn no brokerage.
- Each partial fill is charged separately.
- Fees reduce user virtual cash and account net realized P&L.
- Manager earnings are separate virtual balances, not additions to their practice-trading capital.
- Personal broker/Super Admin practice trades have the documented fee exemption.
- No historical trades are charged retroactively.
- Valid reducing exits may leave virtual cash negative after losses and fees.

The ledger records integer paise. It rounds the total fee half up, allocates 75% of that rounded fee to the broker with half-up rounding, and gives the remainder to Super Admin. Tiny fills can therefore differ from an exact 3%/1% split by a paisa. Lifetime manager earnings survive authorized paper-book resets; the user's current-book fee counter resets with that book.

There are no real-money payout or withdrawal routes. See [brokerage accounting](docs/brokerage.md) for calculation details.

## Markets and data coverage

### Synthetic execution instruments

The current catalogue has **17 illustrative instruments**:

| Market group | Samples |
| --- | --- |
| NSE Futures | NIFTY and BANK NIFTY futures |
| NSE Options | NIFTY 25000 Call and Put |
| NSE Equity | Reliance sample equity |
| MCX | Crude Oil, Gold, Silver, Natural Gas, Copper, Zinc, Aluminium and Lead futures |
| BSE Futures | SENSEX futures |
| MSE | USD/INR futures |
| GIFT NIFTY | GIFT NIFTY sample |
| Global | US 500 sample |

These are continuously generated demonstration prices, not connected live exchange quotes. Prices, lots, expiry metadata and margin rules are illustrative. All paper books use virtual INR, including global/GIFT samples; there is no FX conversion.

### Product availability

- Equity entries use **MIS**.
- Derivative samples support **NRML**; MIS is available only where the backend has a configured square-off lifecycle and the applicable cutoff permits it.
- New MIS exposure on **MSE, GIFT and Global** is rejected; use NRML. Existing MIS positions there can only be reduced or closed.
- New **CNC delivery exposure and T+1 settlement are disabled**. Existing CNC positions are exit-only: increases, reversals and sells larger than the position are rejected, including pending and simultaneous exits. A complete holdings lifecycle is not available.
- MIS square-off runs at **15:15 IST** (NSE, NFO, BSE, BFO), **16:45 IST** (CDS/BCD currency) and **23:30 IST** (MCX). From the cutoff until 09:00 IST, MIS orders can only reduce an existing position; an exit cannot reverse it.
- Default leverage is 5× for equity MIS and 10× for futures, so margin is 20% and 10% of trade value; option buyers pay the full premium. Super Admin can change these in `/sandbox`.

### Public reference prices

The optional Gold API integration can display seven USD reference assets: Gold, Silver, Platinum, Palladium, Copper, Bitcoin and Ethereum. It requires no provider API key and polls approximately every 30 seconds, subject to availability.

Reference prices show provider timestamps and freshness state. Missing, failed or stale data is marked unavailable/stale; synthetic prices do not replace it. These references never enter the execution-price cache or price a paper fill. This free public API is separate from an open-source exchange-data service. See [market-data notes](docs/market-data.md).

## Backend capabilities

| Area | Implemented capability |
| --- | --- |
| Accounts and authentication | Password hashing, browser sessions, invitation activation, per-account API keys, session revocation and login/API admission limits. |
| Authorization | Server-enforced roles, permanent broker ownership, cross-broker isolation and enabled/activated-account checks. |
| Trading ledger | Account-locked transactions for order, fill, position, virtual cash and brokerage changes; duplicate-fill/replay protection and rollback on failure. |
| Order validation | Finite prices, positive quantity, lot/tick rules, expiry, available margin/fees, supported products and disabled-market checks. |
| Financial records | Virtual balances, margin, gross/net realized P&L, fee breakdown and recipient-specific earnings records. |
| Market data | Shared synthetic feed/cache, separate public-reference polling and stale execution-feed protection. |
| Streaming | Authenticated synthetic LTP/Quote updates; production WSS through `/stream`. Depth is explicitly unsupported. |
| Scheduled work | Configured MIS square-off, catch-up processing, expiry handling and daily P&L snapshots. |
| Operations | Dependency/feed readiness, explicit production migration checks, private backup creation and scratch-database restore verification. |

The stack uses **React + Vite**, **FastAPI**, **SQLAlchemy/PostgreSQL**, and **Redis**. PostgreSQL owns durable account/trading records; Redis supports shared admission limits and caching. Caddy serves the production frontend and proxies HTTPS/WSS.

### API and streaming access

- Each account has a paper API key. The OpenAlgo-style REST endpoints under `/api/v1/` take the key in the JSON body and apply the same validation, market policy and brokerage as the web app. Order endpoints are limited to 10 requests per second per account.
- Split orders are not available in this paper build.
- Streaming is at `ws://127.0.0.1:8783` locally and `wss://<your domain>/stream` in production. Authenticate with the API key, then subscribe in LTP or Quote mode; depth subscriptions are rejected. Updates are labelled `synthetic_demo`.
- The web app has no page for viewing or rotating API keys. Signed-in sessions can use `GET /web/apikey` and `POST /web/apikey`; rotation takes effect immediately.
- The [API reference](docs/api/README.md) is inherited from OpenBull and still describes upstream behaviour such as CNC; where it differs, the rules in this README apply.

## Pages and local addresses

| Screen/service | Address | Access |
| --- | --- | --- |
| First Super Admin setup | http://127.0.0.1:5183/setup | Operator setup token; refused once an account exists |
| Invitation activation | `/invite#token=…` (from the shared link) | Public; the link is the credential |
| Login | http://127.0.0.1:5183/login | Activated accounts |
| Trading desk | http://127.0.0.1:5183/dashboard | Signed-in accounts |
| Orders / positions / trades | `/orderbook`, `/positions`, `/tradebook` | Own paper book |
| P&L history | `/sandbox/mypnl` | Own history |
| Management overview | http://127.0.0.1:5183/admin | Broker or Super Admin |
| User management | http://127.0.0.1:5183/customers | Broker or Super Admin, scoped by role |
| Paper settings | `/sandbox` | Super Admin |
| Backend readiness | http://127.0.0.1:8083/health | Health check |
| Local API documentation | http://127.0.0.1:8083/docs | Development only; disabled in production |
| Market-data streaming | ws://127.0.0.1:8783 | API key; `wss://<your domain>/stream` in production |
| Source archive | `/source.tar.gz` | Public in production (footer link) |

Users land on the trading desk after login. Brokers and Super Admin land on their management overview. The platform does not expose inherited upstream pages merely because their source files remain in the repository.

## Run locally

Use the pinned toolchain: **Node.js 24.19.0**, **npm 11.17.0**, and **Python 3.12.14**, with uv and Docker Compose available. Versions are recorded in `.nvmrc`, `.python-version` and `frontend/package.json`; dependency locks are committed.

From the project directory:

```sh
python3 scripts/init_local.py
docker compose -p dhk-paper -f compose.paper.yml up -d --wait
uv sync --frozen
cd frontend
npm ci
cd ..
.venv/bin/python scripts/migrate_database.py --local
.venv/bin/python scripts/dev.py
```

Configuration generation preserves an existing `.env`. Migration first creates and restore-verifies a private backup. On an existing installation, stop its backend before running an upgrade migration.

For a new database, open http://127.0.0.1:5183/setup and use the operator setup token from the private configuration to create Super Admin. Setup refuses further creation once an account exists. Never put tokens or passwords into this README.

On the prepared Mac, **Start DHK Paper.command** starts the local database and web services. Keep its Terminal window open; Ctrl+C stops the web services. The project-owned PostgreSQL volume persists when containers stop. No external broker credentials are needed for paper trading.

## Verification and deployment status

Last verified locally on **6 November 2026**:

- **51 backend tests** plus real HTTP checks passed using disposable databases/accounts.
- **4 frontend regression tests** passed.
- Desktop/mobile browser checks passed for invitations, three-role login, logout/login, partial exits, modal keyboard focus, price ticks, market failures, contrast assertions and page width.
- Frontend production build passed. Lint has **0 errors and 10 warnings**; a bundle-size warning remains.
- Rebuilt production images passed disposable, certificate-verified HTTPS/WSS checks, including authentication, streamed ticks, private service ports and the source archive.
- Private backup restoration was tested. Existing owner account, credential, balance and trading-book fingerprints were preserved across local activation.

An independent review on the same day (16:25–22:17 IST) re-ran these checks on an isolated copy of the working tree, using its own disposable PostgreSQL/Redis containers:

- The suite passed: 51 backend tests, 18 HTTP check groups and the browser workflow. `npm test` gave 4/4, lint gave 0 errors and 10 warnings, and the build passed.
- Its own HTTP, ledger and browser probes reproduced the permission, capacity, invitation, CNC/MIS, settings-conflict, four-decimal and brokerage rules above, at 1440×900 and 390×844.
- Production startup refused a database without the migration stamp and created no tables.
- The local production images match the current source. The deployment check passed against freshly built images.
- Gold API terms could not be checked against the provider's official pages in that review.

CI configuration is included in [paper-checks.yml](.github/workflows/paper-checks.yml); its presence does not establish that a GitHub run has completed. See [launch repairs](docs/launch-repairs.md) for evidence and limits.

For backend/API/browser verification, use `.venv/bin/python scripts/test_isolated.py --browser` after installing frontend dependencies, building the frontend and installing Playwright Chromium. Do not run the standalone QA helpers against the owner's database. Frontend checks are `npm test`, `npm run lint` and `npm run build` from `frontend/`.

Production packaging includes private PostgreSQL/Redis/backend services, Caddy HTTPS/WSS, secure cookies, a corresponding-source archive and a backup-first migration command. Follow [deployment instructions](docs/deployment.md) for host setup and image/restore checks. Production startup verifies its migration stamp instead of applying schema changes automatically. The migration and startup preflight refuse to activate while delivery holdings exist or unassigned legacy users hold positions or pending orders. They do not change those records.

## Current limitations and remaining work

- Public hosting, DNS and domain HTTPS acceptance are not configured.
- Off-host encrypted backup storage, retention and delivered alerts require operator configuration; local backup/timer templates are supplied.
- Target-host load/capacity validation and broader assistive-technology testing remain.
- Live exchange execution feeds and real brokerage execution are not connected.
- CNC delivery/holdings, market depth, native mobile apps and password recovery are not implemented in the shipped flow.
- Invitations require manual sharing; automatic email/SMS delivery is not implemented.
- Provider availability and redistribution terms must be checked before enabling references publicly.
- This work is not yet committed, so the CI workflow has not run.

Known issues from the 6 November review (none affect accounting or permissions):

- If the browser goes offline, the trading desk keeps showing the last prices and "Updates every 2 seconds" with no warning. Orders then fail with a generic "Network Error". It recovers on reconnection.
- Subscribing to an unknown symbol on the stream is acknowledged as successful but sends no data. Quote updates do not include bid/ask.
- Platform controls discard unsaved edits without a warning when you leave the page.
- The deployment check runs the in-container migration with its own backup, rather than the host-side `scripts/migrate_database.py` command. Backup verification compares table counts only.
- `scripts/test_isolated.py` leaves its shared symbol-cache keys in Redis DB 15.

These are local implementation and verification results, not certification of public production capacity or exchange-accurate trading.

## Source and license

Built on [marketcalls/OpenBull](https://github.com/marketcalls/openbull) at commit `e06f1591a519fc58a26aebadda682c71bb624ac9`. Original attribution and the [AGPL-3.0 license](License.md) are retained. The production footer supplies the fork's corresponding-source archive, excluding private configuration, credentials and backups.

## Load and release evidence

The local production HTTPS stack passed 100 authenticated read requests/second (3,000 requests, p95 8.57 ms). A 100-orders/second guarantee is not established: the final raised-admission test accepted 93.94/second with p95 2.32 seconds. Default API admission remains 50/second per IP and 10 orders/second per user. See [capacity evidence and required changes](docs/capacity.md), [launch repairs](docs/launch-repairs.md), and [GitHub checks](https://github.com/nitianbit/Trading_platform/actions). Owner credentials and saved books were preserved; load accounts were disposable.
