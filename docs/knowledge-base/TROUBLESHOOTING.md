# Troubleshooting and regression notes

## Missing data or containers

There are two services: core MT5/Python/SQLite and dashboard. SQLite is a file
library, so no separate SQLite container is expected. Python runs inside the core.
The portable configuration uses named volumes; root Compose uses a local bind
directory. Check the selected Compose file, project name, and mounts before
concluding that a database disappeared. Do not initialize or reset it as a fix.

Use `/api/live` to check MT5 rather than relying on `/health`. Quote updates and
candle updates can fail independently. Cold history requests can delay MT5 IPC
even with a separate candle process. A stopped candle worker may need a core
restart after its underlying error has been diagnosed; automatic worker restart
is not implemented.

## Historical paging repeats the oldest candle

MT5 may return the first available candle again when asked for earlier history,
including date-range requests. The scraper retries and confirms the exact singleton
sentinel using three connected one-bar probes before reporting
`confirmed_first_candle`. Other repeated/forward pages still fail. Preserve this
distinction; swallowing every paging error can silently truncate a download.

## Wine / Python failures

Wine 9 failed MT5 debugger checks. The tested image uses WineHQ staging (11.20 at
the snapshot). NumPy 2.2.6 produced a missing `ucrtbase.dll.crealf` error in earlier
Wine testing; runtime dependencies are pinned to NumPy 1.26.4 and MetaTrader5
5.0.6231. The Windows embedded Python version is 3.12.10. First-run installation
requires network access. Existing state can retain older files; inspect before
changing it, and preserve account/database state.

The startup runner keeps its initialized SDK session when launching collection.
Earlier shutdown/reinitialize behavior caused IPC receive errors. Do not restore
that pattern without a broker-connected regression test. Chart history limits are
written into terminal configuration before startup; the runner waits for both a
connected terminal and the requested limit.

## Resource pressure

Core caps are 4 CPU/4 GiB; dashboard caps are 0.25 CPU/256 MiB. Earlier uncapped
usage exceeded 10 GiB. Inspect applied limits and Docker memory/OOM status before
raising them. An OOM event can terminate a child while leaving the parent online.
Live cache is 1000 bars; seeding grows progressively toward 200 per table. Initial
population of 126 default tables takes time. Catch-up is bounded and does not fill every
historical gap automatically.

## Slow dashboard / range queries

The market database can be several GB. Use the composite primary key by filtering
symbol and timeframe. Do not add an exact row count to every refresh. Range
aggregation uses bucket-first `CROSS JOIN` planning followed by indexed first/last
lookups; a conventional join previously timed out even on much smaller samples.
Preserve the regression tests and query deadlines. Avoid `immutable=1` on a database
that is actively changing.

## Deployment and security limits

Dashboard Basic authentication is optional through `DASHBOARD_USER` and
`DASHBOARD_PASSWORD`; credentials travel over cleartext unless the connection uses
HTTPS. Keep loopback bindings or put an authenticated TLS proxy in front. Both
images travel in the export archive, but data/state require separate backups.
Actual Linux server deployment and shutdown under every failure mode remain
unverified. The timestamp offset still needs broker-specific verification, and
live catch-up does not perform historical backfills. See [HANDOFF.md](HANDOFF.md)
for remaining priorities.

Never solve a project issue by globally pruning Docker: other applications are
running on this machine. Never print credentials while diagnosing Compose config.
