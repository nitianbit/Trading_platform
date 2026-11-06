Latest status: see [6 November launch repairs](launch-repairs.md). The report below records the earlier 4 November pass.

# Audit follow-up — 4 November 2026

Scope: implement the supplied audit's launch-blocking code fixes and prepare a reviewable web-app deployment. Public deployment has not occurred. Existing local accounts and saved books are preserved.

## Implemented

| Audit finding | Change and evidence |
| --- | --- |
| F1 | Reconciliation includes pending reservations, release credits only the amount actually reserved, and the endpoint is admin-only. PostgreSQL tests reproduce and prevent the reconcile/cancel cash-creation cycle. |
| F2 | Modify merges only supplied fields at the HTTP adapter and validates inside the locked ledger transaction. Quantity, ticks, finite prices, expiry and additional margin are checked. Both database and real HTTP cases cover omitted price, invalid changes and insufficient funds. |
| F3 | A fill sizes fresh exposure against the current position and actual execution price. It releases surplus reservations or rejects an unfunded fill atomically. Tests cover previously opening/reducing orders whose position changed before fill, partial fills and rollback. |
| F4 | Account mutations serialize through PostgreSQL transaction locks; the locked order is rechecked before committing its trade, position and funds together. Tests run duplicate-fill and cancel/fill races plus ten simultaneous placements and verify book conservation. Validation and margin lookups reuse the transaction connection; a single-connection-pool regression prevents nested-checkout stalls. This is boundary-level concurrency evidence, not a capacity benchmark. |
| F5 | Demo expiry metadata refreshes at startup and daily. Placement, modify and fill reject expired contracts. Continuous synthetic demo series are excluded from the exchange expiry sweep, and positions reads no longer settle accounts. The simulated expired-metadata regression passes. |
| F6 | Random API keys use an indexed HMAC-SHA256 verifier; legacy encrypted key values are preserved by an idempotent migration. API and order admission limits use async Redis operations. A real HTTP invalid-key flood gets 429 responses; rotation immediately invalidates the old key. Password Argon2 work and the core synchronous trading/snapshot operations run off the event loop. |
| F7 | Login limits are keyed by normalized username plus trusted client IP, with a broader IP guard. HTTP tests confirm independent account limits; the TLS gateway test confirms spoofed forwarding headers cannot bypass a limit. |
| F8 | Initial setup requires a private operator token of at least 32 characters and takes a database lock. Concurrent HTTP claims result in one success and one rejection. |
| F9, F16 | Customer reset and global summary access are denied. Administrative reset now uses the same transaction boundary as trading. Customer self-reset is deliberately disabled to preserve their history. |
| F11 | Updated runtime lock and replaced python-jose with PyJWT. The current installed Python runtime audit reports no known vulnerabilities. Build-tool advisories are a separate unresolved scope. |
| F12, F13 | Fresh ticks are required for pricing, readiness checks actual dependencies/feed heartbeat, and one database runtime owns the feed/scheduler. A second-runtime lease test rejects duplicate startup. |
| F17 | Production docs/schema disabled, secure cookies/HTTPS enforced, TLS/HSTS and a strict script policy supplied. Missing weekly-reset configuration now defaults to Never, with a regression against accidental wipes. |
| Deployment gaps | Backend/static-web images, private Compose services, Caddy TLS proxy, backup/restore verification and host timer templates are supplied. A disposable loopback TLS stack has been exercised. |

Scheduled square-off cancellation and MTM now use the shared account boundary. Catch-up MIS settlement commits position and cash together. Unknown or non-finite numeric input is rejected without poisoning the order history.

## Verification and practical limits

Executed: PostgreSQL/unit regressions through `scripts/test_isolated.py`; expanded real HTTP authentication/trading checks; frontend build and lint on the touched UI files; both container builds; local TLS deployment smoke test; a real backup restored into a new scratch database; Python runtime dependency audit. The final source/database gate passed 25 tests plus 12 real HTTP check groups. Browser rendering was not re-tested in this hardening pass; the supplied audit's UI evidence remains separate.

Synthetic contract sizes, prices, margin and INR remain illustrative. No real broker execution was added. The local TLS test does not verify public certificate issuance, public DNS or real market data.

Outstanding work from the audit includes account disabling/admin key revocation and password recovery (F10), unused live/strategy surfaces (F14), unsupported orderstatus/openposition/split/multi-leg routes (F15), accessibility/mobile refinements and impossible-account flags (F18), legacy lint/build-tool advisories and Decimal/competition design questions (F19). Customer API keys are independent of login sessions; owners can rotate their own key, but a full admin lifecycle is not implemented. No broad-user production readiness or exhaustive security/load review is claimed.

Before public use, choose a host/domain, install the supplied backup/readiness timers, connect alert delivery and encrypted off-host backups, and run acceptance checks on that host. For wider use, complete the remaining lifecycle work and measured load/concurrency validation. No production host, scheduler or alert destination was modified during this task.
