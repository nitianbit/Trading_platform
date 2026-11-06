# Launch repairs — 6 November 2026

The confirmed launch blockers from the supplied audit have been repaired in the local web app. Public deployment has not occurred. This is a paper platform: execution prices remain synthetic, and all balances and earnings are virtual.

## Repairs

| Finding | Result |
| --- | --- |
| Invitation redirect / sign-in bounce | `/invite` remains public. Login and logout preserve the mounted auth query, cancel pending work and remove other private caches. Browser checks cover all three roles, fresh invitation activation and logout/login. |
| Broken delivery inventory and settlement race | New CNC exposure is rejected at the shared server boundary; T+1 settlement is a no-op for every caller. Equity defaults to MIS. Existing CNC positions are exit-only. Production preflight blocks unresolved delivery holdings instead of modifying inventory or cash. A complete holdings lifecycle remains unimplemented. |
| Settings overwrite newer restrictions | Every HTTP replacement requires all policy fields and the loaded revision. Concurrent/stale saves get 409; the editor offers an explicit reload and requires review before saving again. Empty/partial requests get 422. |
| Legacy users and fees | No fee-free exception was introduced. Deployment preflight refuses unassigned legacy users with positions or pending orders; assign their permanent broker before activation. The local legacy demo user has no exposure and remains unassigned for the owner to choose. |
| MIS without square-off | New MIS exposure on MSE/GIFT/Global is rejected; the ticket offers NRML. Existing positions can be reduced. After-cutoff reductions cannot reverse a position. |
| Price precision | Ticket entry/buttons, ledger API responses and user/manager books retain four decimal places. Currency regression verifies average price × quantity agrees with trade value. |
| Ticket and position UX | Inputs have associated labels and price buttons have names. Modal focus wraps synchronously, including rapid Tab presses. Partial exits show selected and remaining quantity. Position actions remain visible on mobile. |
| Market watch and mobile Admin | Watch appears before supporting charts/references; 503 responses display an actionable error. Positioned table containers keep hidden labels/captions inside their scroll area; long broker/user names no longer expand the page. |
| Synthetic streaming | Authenticated LTP/Quote updates fan out from the existing price cache. Depth requests are explicitly rejected. No real broker connection or order execution is enabled. |
| Rejection messages / fee timeframes | Insufficient funds includes margin, estimated 4% brokerage and available cash. Tradebook fees are labeled for the current session; dashboard fees are since reset; manager earnings remain lifetime. |
| Email identity | New invitations compare emails without case sensitivity and store normalized email values. Existing accounts are not merged or renamed. |
| Delivery workflow / CI | Production startup verifies an explicit schema stamp instead of running DDL. The migration command first creates and restore-verifies a backup. CI covers isolated backend/API/browser checks, frontend tests, lint and build. The workflow also builds source-stamped images and exercises the actual operator migration and HTTPS deployment check. Published run results are available in [GitHub Actions](https://github.com/nitianbit/Trading_platform/actions). |

The fee rule is unchanged: each executed user buy and sell deducts 4% of notional, crediting the permanent broker 3% and Super Admin 1%, using the existing paise rounding. Tests cover conservation, partial fills, replay/concurrency and rollback. Manager practice trading retains its documented exemption.

## Verification

- `scripts/test_isolated.py --browser`: **57 backend tests**, expanded real HTTP checks, and desktop/mobile Chromium workflows passed using a disposable PostgreSQL database, isolated Redis keys and temporary accounts. No owner accounts were used for these checks.
- Browser evidence includes three-role sign-in, activation, invalid invitations, logout/login, rapid keyboard focus, 0.0025 ticks, partial exits, market 503 state and page-width checks at 1440×900 and 390×844. Stable editable/result captures and source hashes are retained privately under `.impeccable/review/audit-followup/`.
- `frontend/npm test`: **4 passed**. Production build passed. Full lint has **0 errors and 10 warnings**. Intentional existing form hydration/shared exports have local documented lint exceptions; no project-wide correctness rules were disabled. The bundle-size warning remains.
- Both production images were rebuilt. The isolated local HTTPS deployment check passed secure cookies/login, protected setup, private backend/database/Redis ports, backup/restore before migration, trusted proxy limiting and the source archive checks.
- The owner database was backed up and restored into a scratch database before local activation. Account, credential/API-key, virtual fund, order, trade and holdings fingerprints matched afterwards. No broker was chosen on the owner's behalf.

## Operator work before a public launch

Configure the actual host/domain and complete public HTTPS/DNS acceptance. Configure encrypted off-host backup storage, retention and real alert delivery; the supplied local backup and timer templates do not provide these external services. Establish target-host capacity with representative load and complete assistive-technology testing. Gold API commercial-use terms and request limits were checked on 6 November; see [provider evidence](market-data.md). Public reference HTTPS now has a dedicated outbound network; database and Redis remain internal and unpublished.

Password recovery and a full delivery/holdings lifecycle remain future features. Local browser and container checks do not certify public production capacity or a live exchange feed. Existing MCX/NSE/BSE/MSE/GIFT/global instruments are illustrative paper samples.

## Latest audit follow-up

- Offline/paused or old desk data now shows an explicit warning and blocks new order submission until fresh data returns; browser tests cover reconnect recovery.
- Streaming rejects unknown/malformed subscriptions before acknowledgement and preserves actual bid/ask in Quote updates; missing quote fields are not invented.
- Unsaved platform controls block navigation, refresh and sign-out. Conflict reload refreshes the complete settings snapshot, including current customer count.
- Backup verification compares nonempty row contents/counts in one exported source snapshot. Backup and migration use one explicit target and compare PostgreSQL cluster/database identity before DDL. The deployment check invokes the real operator wrapper and proves a wrong target remains empty.
- Image labels fingerprint current distributable source; stale tags fail the deployment check. Source downloads include `.env.example` and exclude local agent settings. Test cache/limiter keys use owned namespaces and are removed by their runner. Repeated public-feed failures log once per asset outage, with recovery resetting that state.
- Launch preflight flags old unsupported MIS exposure on MSE/GIFT/Global. It reports rather than closing positions or choosing a broker.
- Load testing exposed a weighted-close paise drift. A minimal regression now checks weighted buys and repeated partial closes; internal weighted cost retains precision and cash posts cumulative realized P&L consistently. Immediate admission and fill now share one transaction and roll back together on a settlement failure.
- Final local load: mixed reads **100.02 RPS**, p95 **8.57 ms**; default API orders **50.02 RPS** with expected 429 responses; raised-admission order test **93.94 RPS**, p95 **2,322.83 ms**. No final HTTP/network errors or backlog drops; zero cash/fee discrepancies. The 100-order/second budget failed. See [full evidence and required changes](capacity.md).
- The fresh scoped UI finish review returned `ship`. This covers the repaired desktop/mobile states; live public references and complete assistive-technology behavior remain unverified.

Local checks and source repair do not provide a public host, encrypted off-host storage, alert recipients or a target-host capacity certificate.
