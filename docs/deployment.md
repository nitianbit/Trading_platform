# Deploy the web app

This package prepares a controlled paper-trading deployment. Public DNS, a host, off-host backup storage and alert delivery still need operator configuration. The paper execution feed remains synthetic; the optional free public reference feed requires outbound HTTPS to `api.gold-api.com`. Reference-feed failure does not affect demo execution. See [coverage and controls](market-data.md). Do not use Vite's development server publicly.

## Prepare the host

Use a Docker host with Compose and Python 3. Keep this repository at `/opt/dhk-paper` if using the supplied systemd units. Point a domain to the host and permit inbound TCP 80/443 (UDP 443 is optional). Database, Redis and backend ports must remain private.

Generate private configuration once:

```sh
python3 scripts/init_production.py your.actual.domain
```

This creates ignored `deploy/.env.production` with independent random application, encryption, setup, database and Redis secrets. Existing configuration is preserved. Keep an encrypted recovery copy of this configuration alongside off-host database backups; losing the encryption pepper makes stored keys unreadable. Never print resolved Compose configuration into public logs.

Build and start:

```sh
python3 scripts/build_images.py
docker compose --env-file deploy/.env.production -f compose.production.yml up -d --wait db redis
python3 scripts/migrate_database.py
docker compose --env-file deploy/.env.production -f compose.production.yml up -d --wait
```

`build_images.py` labels both images with a SHA-256 fingerprint of the distributable working tree, including dirty source; the deployment check rejects stale tags. Keep the source unchanged during building and verification.

`migrate_database.py` takes and restore-verifies a private backup before running schema changes and recording the schema version. It compares PostgreSQL cluster identity, database OID and database name before any schema write. Backup and migration share the same Compose target; optional `--project-name`, `--compose-file` and `--env-file` select a different owned deployment explicitly. Production startup checks this version; it does not run DDL or replace triggers. On upgrades, first stop the backend to keep fills and scheduler work out of the migration window. Review the migration output before starting the app. The preflight refuses unresolved delivery holdings, unsupported MSE/GIFT/Global MIS exposure, or unassigned legacy users with exposure: reconcile those books or assign their permanent broker before activation; the 4% fee rule has no exception.

Caddy serves the built frontend and obtains the domain's TLS certificate. Caddy also routes same-origin `/stream` WebSockets over WSS to the internal synthetic streaming port. Only Caddy publishes ports. The backend has a separate outbound network for public reference HTTPS; database and Redis stay on the internal network. Backend workers remain one; a database lease rejects a second runtime before it starts its feed or scheduler. Proxy headers are trusted only because the backend has no published ports and Caddy overwrites inbound forwarding headers. Do not publish backend port 8083.

Open `https://your.actual.domain/setup`, use the operator setup token from the private configuration, and create the first administrator. A database lock permits only one first-admin claim. After setup, the endpoint refuses further creation. The local Mac accounts are not automatically copied into this separate production database. Login is at `/login`; Super Admin and brokers land at `/admin`, and users land at `/dashboard`. Super Admin creates brokers; activated brokers create user invitations. Invitations use the configured frontend origin, so public sharing requires the actual HTTPS domain. See [account hierarchy](accounts.md).

Production requires secure cookies, HTTPS origins and debug disabled. Interactive API docs and the schema are disabled. The footer links a source archive of this fork; private configuration, backups and dependencies are excluded.

## Backups and monitoring

Create a backup and verify restoration without overwriting the running database:

```sh
python3 scripts/database_backup.py --verify
```

Backups are private files under `.local/backups/`. Each dump has a JSON receipt with database identity and verification status. Verification holds an exported repeatable-read source snapshot, restores into a uniquely named scratch database, and compares every public table's row count and two row-content checksum aggregates against that same snapshot. These checks detect restore drift; they are not cryptographic authentication of a backup. The script drops only its scratch database. Copy successful backups to encrypted off-host storage and define retention there. The script does not delete previous backup files.

The supplied `deploy/dhk-backup.service` and `.timer` run a backup with restore verification daily at 02:00 UTC. `deploy/dhk-health.service` and `.timer` check readiness every minute. Review host paths, then install the four units into `/etc/systemd/system/`, run `systemctl daemon-reload`, and enable both timers with `systemctl enable --now dhk-backup.timer dhk-health.timer`. This runs through the host's Docker administration account. Connect failed units or an external HTTPS monitor to your chosen alert destination. No alert destination or off-host backup account is configured by this repository.

`/health` returns 503 if database, Redis or the synthetic feed is unhealthy. Freshness checks pause fills when feed ticks are older than 15 seconds. Docker restarts exited processes; a readiness failure alone does not restart a running container.

## Reproduce checks

```sh
.venv/bin/python scripts/test_isolated.py --browser
.venv/bin/python scripts/build_images.py
.venv/bin/python scripts/check_deployment.py
```

Run `npm ci`, `npm run build`, and `npx playwright install chromium` in `frontend/` before the browser-enabled check. Its Chromium contexts and accounts are disposable; no owner browser profile is used.

The first command creates a separate PostgreSQL database, uses Redis DB 15 with isolated cache and limiter keys, starts an API server using an owned ephemeral loopback socket, runs database and HTTP regressions, and removes its database and temporary credentials. It never resets the owner's local accounts. The deployment check uses disposable containers/volumes and a randomly allocated loopback-only TLS port, exercises the actual backup-before-migration operator command, proves a mismatched migration target receives no schema writes, verifies restored nonempty rows and Caddy's local certificate, then removes its own stack. This validates local container behavior; it does not establish public DNS/ACME operation, target-host architecture compatibility or production capacity.

For local backup verification, use `.venv/bin/python scripts/database_backup.py --local --verify`.

## Capacity check

```sh
.venv/bin/python scripts/check_deployment.py --load --seconds 30
```

This opt-in check offers 100 requests/second through HTTPS for mixed authenticated reads, orders with the default 50/IP/second limit, and orders with a **disposable-test-only** 250/IP/second setting. The 10/order/second per-user limit remains enforced. It creates 64 activated test users, records scheduled-arrival latency, errors, backlog drops, CPU and container memory peaks in `.local/load-results.json`, and verifies cash and fee conservation before removing its stack. A failed acceptance budget still saves the measurements. Do not run it against the owner database or a production customer deployment. See [capacity evidence and required changes](capacity.md).
