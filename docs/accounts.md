# Account hierarchy and invitation access

Implemented and verified locally on 6 November 2026.

## Roles and scope

- **Super Admin:** first operator-token setup account. Creates brokers, views all users and broker activity, controls global markets/capacity and enables/disables broker or user access.
- **Broker:** activates through the Super Admin invitation. Creates users only under itself, views only its users/activity, regenerates unaccepted invitations and enables/disables its own users. Cannot create brokers or access global settings.
- **User:** activates through a broker-created invitation, chooses a password and then signs in normally. Has an isolated paper book. Cannot create accounts or access manager data.

`users.role` owns authorization. The `is_admin` Python/HTTP compatibility value is derived from `role == super_admin`; an old database's stored `is_admin` column is not an authorization source after migration. New users require a valid broker at insert time. A database trigger prevents changing roles, changing an assigned broker, or removing an assigned broker. A foreign key prevents deleting a broker while it owns users. There is no transfer API.

Pre-existing users without brokers retain their credentials and access. Only Super Admin can assign such a legacy user once to an activated, enabled broker. No broker is automatically chosen for them. Once assigned, the same permanent-ownership rule applies.

## Invitation workflow

1. Super Admin opens `/admin`, creates a broker invitation, and privately shares the generated link.
2. Broker opens `/invite#token=...`, sets its password, then signs in at `/login`.
3. Broker opens `/customers`, creates a user invitation, and privately shares that link.
4. User activates its account, sees its permanent broker identity, and signs in normally thereafter.

There is no public user signup and no direct Super Admin user-creation route. Identity request schemas reject client-supplied ownership, role and password fields. Assignment is chosen by the server from the authenticated broker.

Links contain random 256-bit tokens and expire after 48 hours. Only a domain-separated HMAC verifier is stored. The token travels in the URL fragment and POST body, not a query string. Authentication/invitation bodies are excluded from trade logging. Acceptance serializes against other invitation/account mutations, locks and rechecks the invitation, hashes the recipient's password, creates its API key and consumes the token in one transaction. Expired, replaced, accepted and disabled-account/broker links cannot be accepted. Regenerating an unused invitation invalidates the old link. Password recovery for already activated accounts remains outside this feature.

Links are shown for manual copying/sharing. No email or messaging integration sends them automatically. `FRONTEND_URL` owns their origin; links configured for localhost cannot be used from other machines. Public HTTPS deployment is required for external sharing.

## Access and capacity

The maximum-customer setting counts role `user`, including pending invitations, across all brokers. Broker and Super Admin accounts do not consume that cap. Creation and cap edits share a PostgreSQL transaction lock. Expiration does not delete a reserved account; the broker can regenerate its invitation.

Session and API-key authentication read enabled/activated status and the user's current parent-broker status from the database. WebSocket authentication uses the same account check. Disabling a broker blocks new authenticated requests from the broker and children and removes their browser sessions; re-enabling does not revive those sessions. API keys remain stored and become usable again after access is restored. Existing quotes-only sockets are not actively disconnected by this feature. Pending paper orders and existing positions are preserved; disabling access is not an order-cancellation or liquidation action.

Only Super Admin can manage arbitrary brokers/users. Broker mutations return 404 for foreign accounts and recheck the acting manager after acquiring the mutation lock. No manager endpoint returns user passwords or API keys. Accounts and books are not deleted by enable/disable actions.

## Migration and verification

The migration is additive and idempotent: old admins become Super Admin, existing ordinary accounts become legacy unassigned users, and passwords/API keys/history are preserved. Development startup applies it idempotently. Production uses the explicit, restore-verified backup-first migration command in deployment.md; startup verifies the schema stamp. A private local backup was created and restore-tested before activation. Existing local account, password/API-key fingerprints and order/trade counts matched after activation; both original logins worked. Only newly created verification login sessions were removed.

Executed validation: 35 disposable-database/unit tests; 15 HTTP check groups; frontend production build; changed-file ESLint; whitespace checks; static UI detector. Regressions cover permanent ownership, forbidden orphan creation, legacy migration/one-time assignment, expiration, used/replaced tokens, concurrent invitation acceptance, cached broker-state rechecks, cross-broker isolation, capacity races, broker disablement and revoked-session persistence after re-enable. Existing trading-ledger checks remain passing.

Browser discovery succeeded but Tab operations failed with an internal timeout-options error, preventing current desktop/mobile captures. Independent finish review returned `recapture`; rendered layout, responsive behavior and visual accessibility remain unverified. Production images were not rebuilt or deployed in this change.

## Broker limits and user trade history

Super Admin sets each broker's maximum user accounts in the Brokers table. Blank is unlimited; 0 blocks new invitations. Pending invitations and disabled users consume the broker's capacity. Lowering the cap preserves existing accounts/access. Both the global customer cap and the broker cap must allow a new user. Invitation creation, broker-cap edits and legacy-user assignment share the account-policy transaction lock; assigning a legacy user also checks the destination broker's capacity. Brokers can view their own quota and cannot edit it.

Admin → User trades shows executed user fills across earlier sessions with user/broker identity, instrument, side, quantity, fill price and notional trade value. Super Admin sees all user trades. A broker sees only trades belonging to users under its own permanent broker ID; selecting a foreign user returns 404. Ordinary users cannot access this manager endpoint. The view filters by user and pages backwards through at most 50 fills at a time; the endpoint accepts a maximum of 100. It is a read-only history view and cannot place or modify orders.

Current verification: 35 tests and 17 HTTP check groups passed, including concurrent broker quota admission, invalid/zero/unlimited limits, two-broker trade isolation, user filtering, pagination and ordinary-user denial. Production frontend build, changed-file lint, whitespace and static UI checks passed. A restore-tested private backup was taken before the quota migration. Browser visual verification and public deployment remain pending.

Brokerage is now confirmed and implemented at 4% of each executed user buy and sell value, split 3% to the permanent broker and 1% to Super Admin. See [brokerage accounting](brokerage.md) for rounding, transaction guarantees and verification.
