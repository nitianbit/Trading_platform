# Virtual brokerage accounting

User-confirmed rule: **4% of executed trade value on every user buy and every user sell**, split **3% to the user's broker and 1% to Super Admin**. All balances and credits remain virtual.

A ₹1 execution charges ₹0.04, credits ₹0.03 to the broker and ₹0.01 to Super Admin. A ₹100 execution charges ₹4 and credits ₹3/₹1. Closing a position is a second execution and incurs its own fee. Pending, cancelled and rejected quantities generate no charge or earnings.

## Calculation and ownership

The single calculator in `backend/sandbox/brokerage.py` uses Decimal arithmetic and records integer paise. Total fee is 4% of actual quantity × actual fill price, rounded half up to one paise per fill. The broker receives 75% of that rounded fee, rounded half up; Super Admin receives the remainder. This preserves exact debit/credit conservation when fractional paise prevent an exact 3%/1% allocation. There is no minimum fee. Partial executions are charged separately on the quantity actually filled.

`SandboxBrokerage` owns notional, fee and beneficiary facts. Each row has a unique trade identity, user, broker and Super Admin recipient. The broker is the user's permanent owner at execution; the Super Admin recipient is the first operator account. Personal Super Admin/broker practice trades are outside this user-brokerage rule. Users without a broker must be assigned before new trades, including legacy demo users. Existing executions are not back-charged.

Fill price is normalized to the stored four-decimal price before financial calculations. Monetary inputs beyond the accounting columns' signed BIGINT-paise range are rejected.

## Atomic settlement

The existing account transaction lock serializes fills. Order transition, position change, user cash debit, realized P&L adjustment, fee counter and the earnings record commit together. Duplicate/replayed fills see the completed order and cannot create another credit. Failure while recording the fee rolls the entire fill back. Different users append independent records; managers' balances are the sums of their own recipient credits, avoiding shared-wallet updates and lost increments.

User available funds and realized P&L are reduced by brokerage. `m2mrealized` is net of fees; `gross_realized_pnl` and `brokerage_paid` provide the breakdown. Position P&L remains gross. The user Tradebook, manager trade history and CSV show recorded brokerage and recipient credits.

Placement/modification checks current margin plus estimated execution fees for new exposure. Pending orders reserve margin, with fees assessed at execution. Because unfilled fees are not reserved, competing pending orders can make an opening unfunded by fill time; the ledger rechecks and rejects it without charging. Position-reducing exits remain possible even when losses and fees cause negative virtual cash, following existing loss handling.

## Earnings and resets

Broker and Super Admin dashboards display **separate virtual brokerage earnings**, rather than adding credits to their practice-trading capital. `/web/paper/earnings` is manager-only and returns only the caller's credited share. Ordinary users cannot read manager balances; brokers cannot select another recipient. There are no payout or withdrawal routes.

Fee records survive authorized resets of paper orders/trades/positions. Such a reset replenishes virtual user capital and clears its current-book fee counter, while lifetime recipient earnings remain. Disabling users or brokers does not delete their records or cancel pending orders. A previously accepted pending fill still follows the same accounting rules.

## Verification

44 tests and 18 HTTP check groups passed, including exact ₹1/₹100 splits, fractional rounding conservation, partial-fill/cancellation behavior, duplicate races, concurrent users crediting the same recipients, insufficient fees at placement/fill, full rollback after a credit failure, valid negative-cash exits, retained earnings after a paper reset, legacy broker requirements, account isolation and net P&L. Production frontend build, changed-file ESLint, whitespace and static UI checks passed.

A private backup was created and restored into an isolated scratch database before local activation. Original local account/credential/balance/history fingerprints are checked across activation. Current browser capture is unavailable due to the existing browser-control error, so rendered desktop/mobile layout and visual accessibility remain unverified. Public deployment and refreshed production images remain outstanding.

Local activation completed successfully: existing user/password/API-key, balance and order/trade fingerprints matched before and after migration. No historical fee records were created and both existing accounts still sign in. Super Admin's new virtual earnings endpoint returned a zero starting balance; ordinary-user access was denied. The existing unassigned demo user is rejected by the brokerage-context check until Super Admin assigns a broker. Only the temporary verification sessions were removed. The independent UI finish review returned `recapture` because current browser images could not be produced; it did not issue visual approval.

Latest verification and launch limitations: [6 November repairs](launch-repairs.md). The fee rule and rounding above remain unchanged.
