# Operations

Run commands from the project root. The active portable project uses
`docker/compose.server.yaml`; root `compose.yaml` is a different local configuration.

## Start, inspect, stop

```powershell
docker compose --project-directory . -p mt5scraper-portable -f docker/compose.server.yaml up -d
docker compose --project-directory . -p mt5scraper-portable -f docker/compose.server.yaml ps
docker compose --project-directory . -p mt5scraper-portable -f docker/compose.server.yaml logs --tail 100 mt5 dashboard
docker compose --project-directory . -p mt5scraper-portable -f docker/compose.server.yaml stop
```

Logs can contain operational details; redact before sharing. Use `config --quiet`
to validate Compose without printing resolved environment values.

Dashboard: http://127.0.0.1:8080/. MT5 desktop:
http://127.0.0.1:6080/vnc.html. Neither has application authentication. On a remote
server, keep loopback bindings and forward ports over SSH, for example
`ssh -L 8080:127.0.0.1:8080 -L 6080:127.0.0.1:6080 user@server`.
Optional dashboard Basic authentication uses `DASHBOARD_USER` and
`DASHBOARD_PASSWORD` in the private `.env`; set both. Use HTTPS or SSH remotely.

## Connect the local Slate stack

The optional provider API is served by the dashboard at
`http://mt5-market-provider:8080/provider/v1` from containers attached to the
same Docker network. Slate's current local network is `slate-local_internal`;
set `SLATE_DOCKER_NETWORK` in `.env` if its name differs. Apply the overlay to
the dashboard service only:

```powershell
docker compose --project-directory . -p mt5scraper-portable -f docker/compose.server.yaml -f docker/compose.slate-local.yaml up -d --no-deps dashboard
```

This preserves the core collector and volumes. To exercise DNS and the HTTP
contract from Slate's Node runtime without changing Slate files or containers:

```powershell
./scripts/test-slate-provider.ps1
```

The script starts a temporary Node container on the Slate network and removes it
when the request checks finish. The API remains read-only and uses the dashboard's
optional Basic authentication. Network attachment alone does not configure
Slate's application to consume the provider.

## Build and apply changes

```powershell
docker compose build dashboard
docker compose --project-directory . -p mt5scraper-portable -f docker/compose.server.yaml up -d --no-deps dashboard
```

Use `mt5` in place of `dashboard` to build/recreate the core. A build alone does
not replace a running container. Recheck broker connection and candle progress
after recreating the core. Do not recreate it for dashboard-only edits.

If the MT5 build asset is absent, Windows preparation is:
`./scripts/prepare-image.ps1 -MT5InstallDir 'C:/Program Files/MetaTrader 5'`.
This copies the terminal executable into `.image` for the build. The resulting
Linux image contains MT5 and Wine; the deployment host needs no Windows MT5 install.
Existing `/state/terminal` contents take precedence over the image seed and can
contain a terminal updated by MT5 itself.

## Configuration

### Backfill the default 14 instruments

Copy `scripts/run-history-and-restore.sh` to `/opt/mt5scraper-deploy` and run it
from the VM. It uses one terminal and the primary market database, keeps the
read-only dashboard online, monitors the 15 GiB disk floor, and recreates the
core in live mode after successful completion, failure, or a disk-floor stop.
The current defaults are seven FX pairs and seven metals across all nine stored
intervals. The historical scraper applies `MT5_TIME_OFFSET_SECONDS` to stored
candle timestamps, matching the live collector.

Copy `.env.example` to `.env` privately and set all three authentication variables:
`MT5_LOGIN`, `MT5_PASSWORD`, and exact broker `MT5_SERVER`. Do not print `.env`.
Use the template for the complete current configuration and defaults.

| Setting | Purpose / current default |
| --- | --- |
| `MT5_MODE` | `live`; other modes are desktop, check, stack, scrape |
| `MT5_WAIT_SECONDS` | Startup connection wait, 600 seconds |
| `LIVE_POLL_SECONDS` | Quote polling interval; default 1 second, minimum 0.5 second |
| `LIVE_CANDLE_SECONDS` | Candle scheduling base, 5 seconds |
| `LIVE_WORKER_STALL_SECONDS` | Restart the candle worker after this much time without progress; default 180 seconds |
| `LIVE_MAX_BARS` | Terminal live cache/catch-up bound, 1000 |
| `LIVE_SEED_BARS` | Progressive initial seed target, 200 |
| `LIVE_SYMBOLS` | Optional comma-separated subscription override |
| `MT5_TIME_OFFSET_SECONDS` | Seconds subtracted from new live broker timestamps; default 0 |
| `MT5_MAX_BARS` | Historical terminal limit, 100000000 |
| `MT5_CPU_LIMIT`, `MT5_MEMORY_LIMIT`, `MT5_PIDS_LIMIT` | Core: 4 CPU, 4g, 512 |
| `DASHBOARD_CPU_LIMIT`, `DASHBOARD_MEMORY_LIMIT`, `DASHBOARD_PIDS_LIMIT` | Dashboard: 0.25 CPU, 256m, 64 |

Memory plus swap is capped at the same value as memory. Keep these limits unless
the user deliberately chooses a different budget. Check `.env.example` for exact
variable spelling before editing; configuration can evolve.

Slate's API container must be attached to the `slate-dev_internal` Docker
network and configured with
`MT5_GATEWAY_URL=http://mt5-market-provider:8080/provider/v1`. The Gateway
dashboard publishes the `mt5-market-provider` network alias. Without the URL
setting, Slate's `/api/fx-metals` endpoint returns HTTP 503 even when Gateway
quotes are healthy. This setting belongs to Slate's API deployment.

For lower collection work, `LIVE_SYMBOLS` can be set to a fixed comma-separated
subset. This changes both quote and candle subscriptions and is applied at core
startup; it is not a runtime-priority list. Compare the collector's
`cycle_duration_ms`, `mt5_poll_ms`, `sqlite_write_ms`, and `poll_overruns` fields
from `/api/live?symbol=EURUSD` before and after changing the polling interval.
Quote API responses report `quoteAgeAtApiMs` since local receipt and
`brokerTimestampSkewMs` separately because broker timestamps have previously
appeared offset from the gateway clock.

On the Slate VM, the observed tick offset was approximately +7,200 seconds on
26 October 2026, so its private `.env` uses `MT5_TIME_OFFSET_SECONDS=7200`.
This is a deployment-specific observed setting, not a portable default. It
applies to newly collected ticks and candles; existing database rows are left
unchanged. Recheck the offset when the broker changes its seasonal server time.

`stack` runs historical collection then retains the terminal; `scrape` exits after
history; `check` authenticates then exits; `desktop` runs the desktop. The helper
`scripts/start-stack.ps1` uses the local Compose plus scrape override and selects
historical mode even if `.env` says live. It is not the normal portable-live launcher.
Its smoke-test option uses a separate database and a small bar limit.

## Persistence and backup

Portable volumes are `mt5scraper-portable_mt5-data` (`/data`) and
`mt5scraper-portable_mt5-state` (`/state`). The dashboard mounts data read-only.
Root local Compose instead bind-mounts `./data`. Changing project names can select
different volumes; empty local files do not mean the portable database was lost.
Explicit container names and ports prevent both configurations running together.

Image export does not include volumes. Back up both separately. Prefer SQLite's
backup API for a live database, or stop writers before copying database files.
Persisted terminal state may contain account information and must be protected.
Do not copy an actively changing database file and assume a consistent snapshot.

## Export and Linux deployment

`./scripts/export-stack.ps1` saves both images to `release/mt5scraper-image.tar`
and copies server Compose as `compose.yaml`, the optional Slate network overlay,
`.env.example`, the root README, DietPi deployment steps, and an SHA-256 checksum.
It does not export credentials or database/state volumes. The remaining knowledge
base is not copied into the release folder.

On Linux/amd64, load the image archive with `docker load -i mt5scraper-image.tar`,
create the private `.env`, then start the exported Compose with project name
`mt5scraper-portable`. Keep image tags consistent with export-script arguments and
environment overrides. Fresh state still downloads Python packages and needs
internet access to the package index and broker. The DietPi Linux VM deployment
has been exercised. A source-only handoff ZIP lacks `.image/terminal64.exe` and cannot
build the core until that build asset or a prebuilt image is supplied.
