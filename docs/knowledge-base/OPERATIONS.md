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

Copy `.env.example` to `.env` privately and set all three authentication variables:
`MT5_LOGIN`, `MT5_PASSWORD`, and exact broker `MT5_SERVER`. Do not print `.env`.
Use the template for the complete current configuration and defaults.

| Setting | Purpose / current default |
| --- | --- |
| `MT5_MODE` | `live`; other modes are desktop, check, stack, scrape |
| `MT5_WAIT_SECONDS` | Startup connection wait, 600 seconds |
| `LIVE_POLL_SECONDS` | Quote polling, 1 second |
| `LIVE_CANDLE_SECONDS` | Candle scheduling base, 5 seconds |
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
and copies server Compose as `compose.yaml`, `.env.example`, and the root README.
It does not export credentials or database/state volumes. The export helper does
not currently copy this knowledge base, so send the handoff bundle separately.

On Linux/amd64, load the image archive with `docker load -i mt5scraper-image.tar`,
create the private `.env`, then start the exported Compose with project name
`mt5scraper-portable`. Keep image tags consistent with export-script arguments and
environment overrides. Fresh state still downloads Python packages and needs
internet access to the package index and broker. Actual server deployment remains
unverified. A source-only handoff ZIP lacks `.image/terminal64.exe` and cannot
build the core until that build asset or a prebuilt image is supplied.
