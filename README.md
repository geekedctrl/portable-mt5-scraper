# MT5 Market Gateway

**MT5 Market Gateway** collects live quotes and candle history from MetaTrader 5
into persistent SQLite databases, then serves them through a lightweight,
read-only web dashboard. MT5, Wine, Windows Python, and SQLite run together in a
portable Linux/amd64 Docker container; the dashboard runs in a companion
container.

The short product name is **Gateway**. The source project and Docker image tags
retain their existing `MT5Scraper` names for compatibility.

For coding-agent takeover, start with [AGENTS.md](AGENTS.md) and the
[gateway knowledge base](docs/knowledge-base/README.md).

## Project layout

```text
src/         Python scraper and original MT5 library
dashboard/   Read-only web dashboard and its Dockerfile
scripts/     PowerShell commands to prepare, start, and export images
docker/      Container startup helpers and additional Compose configurations
tests/       Automated tests
examples/    Example notebook
docs/        Changelog and archived reference material
data/        Local databases and archived history; ignored by Git
.image/      Local MT5 binary used during image builds; ignored by Git
```

Root files contain the main Compose configuration, Dockerfile, package setup,
license, and environment settings. `.env` is private and excluded from Git
and image builds. Database volumes used by the portable stack are independent
of the local `data/` directory.

## Credentials

Copy `.env.example` to `.env` if needed and fill in:

```dotenv
MT5_LOGIN=12345678
MT5_PASSWORD='your-password'
MT5_SERVER=YourBroker-Demo
```

Use the account number and exact broker server name. Single quotes preserve
characters such as `$` and `#`; passwords containing quotes need Compose dotenv
escaping. Administrators with Docker access can inspect container credentials.
Avoid sharing resolved Compose configuration or container environment output.

## Web dashboard

Open http://127.0.0.1:8080 to browse the live SQLite data:

- Select an instrument and timeframe, and inspect OHLC candles and tick volume.
- Apply UTC date filters, move through older/newer candles, or return to latest.
- Use 1Y, 3Y, 5Y, 10Y, and Max history-range presets. They end at the latest
  stored candle and automatically choose a suitable stored candle interval.
  Max spans the instrument's oldest available stored history. When necessary,
  a bounded OHLC overview combines first open, highest high, lowest low, last
  close, and summed volumes. The chart labels aggregated data explicitly.
  Range views load on selection or manual refresh; live quotes continue
  independently. Click Latest or an interval button to return to candle paging.
  Missing older history is identified; these controls do not request a backfill.
- Inspect all 50 tables and their first/last available timestamps.
- Calculate exact row counts on demand and export the displayed candles as CSV.
- Live quotes poll every 1 second by default, recent candles about every 5 seconds,
  and table coverage every 30 seconds while the tab is visible.

The dashboard is read-only at both the SQLite connection and Docker volume
levels. It has no broker credentials. Reads may briefly fail while SQLite is
busy; refresh to retry. Its connection badge indicates database access, not
broker connectivity or completion of the history job. UTC labels display the
stored candle timestamps. Counts are limited to five seconds to protect large
databases. CSV export contains only the currently loaded page (up to 1,000 rows).

Build and start only the dashboard without interrupting the scraper:

```powershell
docker compose build dashboard
docker compose --project-directory . -p mt5scraper-portable -f docker/compose.server.yaml up -d --no-deps dashboard
```

`DASHBOARD_PORT` changes the default loopback port 8080. Local sample databases
can be viewed by setting `DASHBOARD_DATABASE_PATH=/data/market-smoke.db` and
using the root Compose configuration. Dashboard and scraper share the same
volume in the portable configuration. The dashboard image uses only Python's
standard library, and needs no external chart services or CDN.

On a remote server, forward the dashboard with
`ssh -L 8080:127.0.0.1:8080 user@server`. The dashboard can enforce HTTP Basic
authentication when both `DASHBOARD_USER` and `DASHBOARD_PASSWORD` are set.
Keep remote access behind SSH or HTTPS; Basic authentication over plain HTTP is
not encrypted.

## Current portable stack

Both Compose configurations enforce resource limits by default:

| Service | CPU cores | Memory | Additional swap | Process/thread limit |
| --- | ---: | ---: | ---: | ---: |
| MT5 + scraper | 4 | 4 GiB | None | 512 |
| Dashboard | 0.25 | 256 MiB | None | 64 |

These are caps, not reserved resources. CPU-heavy work is throttled; exceeding
the memory cap can terminate a container process instead of allowing memory
use to keep growing. Large full-history jobs may need smaller sessions or a
larger limit on a server. Database transactions already committed persist.
Configure `MT5_CPU_LIMIT`, `MT5_MEMORY_LIMIT`, `MT5_PIDS_LIMIT`, and the matching
`DASHBOARD_*` settings in `.env`, then recreate the containers to apply changes.
The same memory value is used for memory-plus-swap, disabling additional swap.
Other containers and Docker Desktop's overall VM limit are separate settings.

From the project root, start or inspect the existing portable stack:

```powershell
docker compose --project-directory . -p mt5scraper-portable -f docker/compose.server.yaml up -d
docker compose --project-directory . -p mt5scraper-portable -f docker/compose.server.yaml logs -f mt5
```

The default `MT5_MODE=live` authenticates MT5 and continuously polls selected
instruments. Bid, ask, price/point spread, and broker tick time are stored as
one latest quote per symbol in `/data/live.db`. A separate candle worker in
the same capped container upserts current and newly completed candles into
`/data/market.db`. Quote polling stays independent of candle loading. Both
files are in the persistent data volume; the dashboard mounts it read-only.

Default FX subscriptions: EURUSD, GBPUSD, USDJPY, USDCHF, USDCAD, AUDUSD,
NZDUSD, EURGBP, EURJPY, GBPJPY, AUDJPY, EURCHF, EURAUD, EURCAD, EURNZD,
GBPCHF, GBPAUD, GBPCAD, GBPNZD, AUDCAD. The collector also selects up to 20
broker-listed metals; this account offers only 14, and all 14 are subscribed.
Industrial metals are included. A listing does not guarantee an active feed.
Set comma-separated `LIVE_SYMBOLS` to override subscriptions, then recreate.
Unavailable subscriptions fail validation rather than substituting prices.

All 21 candle timeframes are enabled, named `SYMBOL_TIMEFRAME`: M1, M2, M3,
M4, M5, M6, M10, M12, M15, M20, M30, H1, H2, H3, H4, H6, H8, H12, D1, W1, MN1.
Across 34 instruments this produces 714 tables. Monthly catch-up uses calendar
months rather than a fixed 30-day approximation.
Existing history is preserved. New tables start with the latest two candles, then gradually seed up to
200 recent bars. Seed progress survives restarts.
Reconnect catch-up is limited to 1,000 bars per table, so long outages may
need a separate historical backfill. A catch-up limit is recorded in
`candle_status`. Live mode also sets MT5's terminal cache to 1,000 bars to
reduce RAM use; this does not trim the SQLite database.

Settings: `LIVE_POLL_SECONDS=1`, `LIVE_CANDLE_SECONDS=5`, `LIVE_MAX_BARS=1000`,
`LIVE_SEED_BARS=200`. Short candles target a 5-second refresh; longer
timeframes use 5–60 second scheduling to reduce work. Quote polling remains
independent. Intervals are targets; initial candle loading or broker
latency may delay a pass. Freshness is explicit: an offline collector, a
stale tick, no quote, and waiting for a new tick are distinct states. Fresh
ticks are detected by changes in tick timestamps, separately from collection
heartbeats. No quote is invented for a closed or unavailable market. Quotes
are latest snapshots, not an archival record of every tick.

MT5 tick and candle timestamps are stored as supplied by the broker by default.
If a broker-specific offset has been verified, set `MT5_TIME_OFFSET_SECONDS` to
the number of seconds to subtract. The default is 0 and existing database rows
are not rewritten. The collector restarts failed candle workers with bounded
backoff. Live status includes stored bar counts, available time bounds, detected
gaps within the most recent 10,000 bars, and whether catch-up reached its
configured cap.

To run the original full-history job instead, set `MT5_MODE=stack` in `.env`
and recreate. It still uses the historical `MT5_MAX_BARS` limit (100,000,000
by default), and reports coverage/integrity in `/data/market.report.json`.
Set `MT5_MODE=live` and recreate to return to continuous updates. Long backfills
may exceed the laptop's 4 GiB cap; run them separately with suitable resources.

The scraper retries temporarily stale pages. When MT5 repeats its earliest
candle, three connected one-bar probes confirm the boundary. Other paging or
connection failures remain errors. Table reports include the stopping reason.

The desktop is available at http://127.0.0.1:6080/vnc.html. Stop the stack with:

```powershell
docker compose --project-directory . -p mt5scraper-portable -f docker/compose.server.yaml down
```

Normal shutdown preserves volumes. Removing volumes deletes their saved data.

## Build and local sample testing

Prepare the installed MT5 binary and build the image:

```powershell
.\scripts\prepare-image.ps1
docker compose build
```

For another installation, pass `-MT5InstallDir 'C:\path\to\MT5'`.
Only `terminal64.exe` is packaged; credentials and downloaded history are not.
The container has no dependency on a Windows host directory after building.

The local helper uses the root Compose configuration and a host `data/` folder:

```powershell
.\scripts\start-stack.ps1 -SmokeTest
```

This downloads at most 100 bars per table into `data/market-smoke.db`.
Omit `-SmokeTest` for an unbounded download into `data/market.db`.
Stop the portable stack first: the two configurations share desktop port 6080
and should not run simultaneously. For desktop-only local mode, run
`docker compose up -d --build`.

## Ship to a server

Export the built image and server configuration:

```powershell
.\scripts\export-stack.ps1
```

The ignored `release/` folder contains the image tar, server `compose.yaml`,
blank `.env.example`, and this README. No credentials or database volumes are
exported. Transfer it to a Linux x86-64 server with Docker Engine and Compose
v2+. ARM and Windows-container targets are untested. The image is several GB.
First launch needs outbound access to PyPI and your broker.
The export includes both `mt5scraper:local` and `mt5scraper-dashboard:local` in
the same tar, so loading it makes both services available on the server.

In the transferred folder on the server:

```sh
docker load --input mt5scraper-image.tar
cp .env.example .env
chmod 600 .env
# Fill in broker credentials in .env.
MT5_MODE=stack SCRAPE_MAX_BARS=100 docker compose up -d
docker compose logs -f mt5
```

After sample validation, start continuous live updates (the default in `.env`):

```sh
docker compose up -d --force-recreate
```

Server data is stored in the `mt5-data` volume, with terminal state in
`mt5-state`. Back up these volumes separately. After scraping finishes, copy
the database and report out with:

```sh
docker compose cp mt5:/data/market.db ./market.db
docker compose cp mt5:/data/market.report.json ./market.report.json
```

Copy only while no scraper is writing; use SQLite's backup API for live backups.
The browser desktop is bound to loopback with no VNC password. For remote
access, use `ssh -L 6080:127.0.0.1:6080 user@server` rather than publishing it
on the internet. `MT5_DESKTOP_PORT` changes the server-side loopback port.

## Tests and direct Python usage

```powershell
python -B -m unittest discover -s tests -v
python src/scrape_all.py --help
python src/xauusd_sqlite.py --help
```

Direct Python commands require Windows, the MetaTrader5 package, and an
installed, authenticated MT5 terminal. Their default local database is
`data/xauusd.db`; the earlier database is preserved in `data/legacy/xauusd.db`.
`setup.py` uses the `src/` layout for the original `mt5_scraper` library.

See [the changelog](docs/CHANGELOG.md), [the example notebook](examples/example.ipynb),
and [the archived project reference](docs/reference.md) for background.

## License

This project is licensed under the [Apache License 2.0](LICENSE).

## Internal market-data API

Gateway serves a read-only v1 provider API for trusted Docker clients at /provider/v1/status, /provider/v1/instruments, /provider/v1/quotes, and /provider/v1/history/{symbol}. To bridge the dashboard/API container onto a local Slate Docker network, see [the Operations guide](docs/knowledge-base/OPERATIONS.md#connect-the-local-slate-stack) and [API contract](docs/knowledge-base/DATA_AND_API.md#gateway-provider-api-v1). Slate needs a provider URL/configuration change before it will consume Gateway data.

Interactive API documentation is available at `http://127.0.0.1:8080/docs` and
the OpenAPI specification at `http://127.0.0.1:8080/openapi.json`.
