# Capacity evidence

The local HTTPS test sustains **100 authenticated read requests/second**. A blanket 100-order/second production claim is not established. The API intentionally admits only 50 requests/second per client IP by default; orders additionally have a 10/second per-user limit.

## Measured baseline and repair

6 November 2026, local Docker, production Caddy HTTPS, one backend worker, dedicated PostgreSQL 17 and Redis 7, 64 activated users, one load-generator IP. Open-loop scheduling includes client queue delay in latency. Accounts, keys and books were disposable.

| Run | Offered traffic | Accepted/sec | p95 | Result |
| --- | --- | ---: | ---: | --- |
| Baseline, 30 s | Mixed reads, 100/sec | 100.02 | 9.47 ms | 3,000 HTTP 200; no network errors or drops |
| Baseline, 15 s | Orders, default 50/IP/sec | 50.02 | 179.99 ms | 750 HTTP 200, 750 HTTP 429 |
| Baseline, 30 s | Orders, test 250/IP/sec | 84.68 | 3,286.88 ms | 2,774 HTTP 200, 1 network error, 225 backlog drops |
| Transaction repair, 10 s | Orders, test 250/IP/sec | 96.44 | 670.57 ms | 1,000 HTTP 200; no network errors or drops; target still missed |
| Final repair, 30 s | Mixed reads, 100/sec | 100.02 | 8.57 ms | 3,000 HTTP 200; no errors or drops |
| Final repair, 15 s | Orders, default 50/IP/sec | 50.02 | 125.12 ms | 750 HTTP 200, 750 HTTP 429; expected throttling passed |
| Final repair, 30 s | Orders, test 250/IP/sec | 93.94 | 2,322.83 ms | 3,000 HTTP 200; no errors or drops; 100-RPS budget failed |

The first high-order run also exposed a three-paise weighted-close cash/P&L drift. A minimal regression reproduced it independently of concurrency; preserving internal weighted cost and posting the change in rounded cumulative realized P&L repaired it. The repaired concurrent run reported zero cash, fee-split or fee-counter discrepancies. The transaction repair shares one connection from admission through immediate fill, retains fill-time validation and account locking, and rolls back admission if settlement fails. The short run also had one HTTP 502 in its separate default-throttle profile. That did not recur in the final run, which recorded no gateway errors. The final run still fails the 100-order/second throughput and latency budgets; the load command correctly exits nonzero and preserves its report. No 100-order/second capacity guarantee is made.

The final run started at 17:35:36 UTC (23:05:36 IST). Docker was allocated 10 aarch64 CPUs and 8,321,515,520 bytes of memory. Over the order profile the backend used 40.645 CPU seconds, PostgreSQL 7.046, Redis 0.429 and Caddy 1.974; client CPU was 6.260 seconds. Lifetime container memory peaks were backend 161,615,872 bytes, PostgreSQL 243,765,248, Redis 8,093,696 and Caddy 41,676,800. Peaks are independent, not a simultaneous total. All final cash, fee-split and fee-counter violation counts were zero. The report is `.local/load-final-30s.json`; it contains no user credentials and remains an ignored local artifact.

## Reproduce and interpret

Build the current source with `scripts/build_images.py`, then run `scripts/check_deployment.py --load --seconds 30`. Reports live privately in `.local/`; the script saves failed runs too. Default-throttle behavior accepts only HTTP 200/429. Capacity budgets require all 200 responses, no network errors/backlog drops, accepted throughput at least 99/sec, p95 at most 500 ms for reads and 1,000 ms for orders. The client offers exactly 100/sec; the small throughput allowance accounts for the final response draining after the offered window.

The direct sequential order profile is setup work, outside timed traffic. Report CPU values are cgroup deltas and include account-path warmup and metrics probes. Memory is each container's lifetime cgroup peak, not simultaneous process-family RSS. Reports include host/Docker resources. These are warm runs; cold startup, login/password hashing, public provider fetches, large historical books, many WebSockets, soak behavior and target-host contention were not measured. No model/API token cost applies to the generator; agent task-token usage is unavailable.

## What 100 RPS requires

1. Choose a production traffic mix and repeat this test on the actual host. 100 read RPS and 100 completed orders/sec are different workloads. Include expected account/history sizes and a soak period before setting a customer capacity promise.
2. For 100 API requests/sec from one shared/NAT address, configure `API_RATE_LIMIT="250 per second"` in the private production environment after reviewing the abuse budget. Keep `ORDER_RATE_LIMIT="10 per second"` per user and authentication/revocation checks. This changes admission, not server capacity. Browser read routes use separate admission behavior.
3. If the order profile still fails, reduce the profiled duplicate symbol/policy/position queries within the locked order transaction, then measure again. Do not cache authorization or remove financial locks to raise throughput.
4. If one Python runtime remains CPU-bound, separate the singleton feed/execution/scheduler from HTTP workers, share quotes through Redis, and preserve database-enforced per-account serialization/idempotent fill claims before allowing multiple HTTP workers. Simply adding Uvicorn workers currently fails the runtime lease and is unsupported.
5. Keep PostgreSQL and Redis close to the backend, size database pools across all workers against available connections, and add host metrics/alerts for latency, 429/5xx, CPU, connections and quote freshness. Redis failure remains fail-closed for admission.

A public customer launch still requires the chosen host/domain, public DNS/HTTPS/WSS acceptance, encrypted off-host backups with retention and restore verification, alert delivery, target-host load and assistive-technology acceptance.
