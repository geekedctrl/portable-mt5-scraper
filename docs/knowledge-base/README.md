# Gateway knowledge base

Engineering handoff for the portable MT5 market-data gateway. The user needs an
exportable Linux Docker stack, live prices, persistent SQLite history, and a
browser dashboard that stays within laptop resource limits.

## Reading order

1. [HANDOFF.md](HANDOFF.md): current state, first checks, and remaining work.
2. [ARCHITECTURE.md](ARCHITECTURE.md): processes, data flow, and important decisions.
3. [OPERATIONS.md](OPERATIONS.md): startup, rebuild, deployment, and backup.
4. [DATA_AND_API.md](DATA_AND_API.md): schemas, instruments, timeframes, and APIs.
5. [TROUBLESHOOTING.md](TROUBLESHOOTING.md): previous failures and current limits.

The [root agent entry point](../../AGENTS.md) contains working expectations.
[.env.example](../../.env.example) is the public configuration template. `.env`
contains real credentials and must not be included in handoff documents.
Code/configuration are authoritative if documentation becomes outdated.
[docs/reference.md](../reference.md) is historical material, not the current runbook.

## Verified snapshot

Checked on **26 October 2026**, using the user's Asia/Kuala_Lumpur date:

| Item | Observed state |
| --- | --- |
| Project directory | `C:\Users\pkart\OneDrive\Desktop\Projects\MT5Scraper` |
| Compose project | `mt5scraper-portable` |
| Deployment | DietPi Linux VM at `slate-vm` |
| Core container / service | `mt5-market-scraper` / `mt5` |
| Dashboard container / service | `mt5-data-dashboard` / `dashboard` |
| Subscriptions | Seven FX pairs + seven broker-listed metals |
| Candle coverage | 126 default symbol/timeframe tables initialized in the Gateway database |
| Collector | Live on 7 FX + 7 metals; provider reports 14/14 live quotes and a fresh candle-worker heartbeat |
| Resource caps | Slate VM core 1 CPU / 4 GiB; dashboard 0.25 CPU / 256 MiB |
| Tests | 55 passing |
| Dashboard | Healthy at `http://127.0.0.1:8080/`; published to Slate's internal Docker network |
| MT5 browser desktop | `http://127.0.0.1:6080/vnc.html` |
| Git baseline | `b54dea4`, pushed to `geekedctrl/portable-mt5-scraper` |

This is a dated snapshot, not continuous monitoring. Recheck runtime state before
acting. Linux deployment, image transfer, two-terminal login, bounded batch-size
benchmarking, and a parallel historical collection experiment have been exercised on DietPi.
The experimental worker databases were deleted after stopping the workers; their
MT5 state volumes were retained. The regular live service has since been redeployed.

## Product boundaries

- MT5, Wine, Windows Python, and SQLite writers share one container.
- The read-only dashboard is a second lightweight container in the same stack.
- SQLite is embedded, not a separate database-server container.
- Only the latest quote per symbol is stored; there is no complete tick archive.
- Live mode progressively seeds recent candles and performs bounded catch-up.
  It does not promise complete broker history for all 126 default tables.
- D5/1M/6M/YTD/1Y/5Y/Max are views of stored history, not MT5 candle intervals or
  requests to download missing history.
- Dashboard and desktop bind to loopback. Dashboard Basic authentication is
  optional; remote access should use SSH forwarding or HTTPS through a proxy.

## Ownership map

| Change | Main files |
| --- | --- |
| Live quotes, subscriptions, seeding, scheduling | [src/live_collector.py](../../src/live_collector.py) |
| Historical paging/backfill | [src/scrape_all.py](../../src/scrape_all.py) |
| Timeframe constants and candle schema | [src/xauusd_sqlite.py](../../src/xauusd_sqlite.py) |
| Authentication and process launch | [container_runner.py](../../docker/container_runner.py), [entrypoint.sh](../../docker/entrypoint.sh) |
| Persistent terminal chart limit | [configure_terminal.py](../../docker/configure_terminal.py) |
| Read-only APIs and range aggregation | [dashboard/server.py](../../dashboard/server.py) |
| Browser behavior | [dashboard/static/app.js](../../dashboard/static/app.js), HTML/CSS beside it |
| Portable deployment | [docker/compose.server.yaml](../../docker/compose.server.yaml) |
| Local build and bind-mounted data | [compose.yaml](../../compose.yaml), [Dockerfile](../../Dockerfile) |
| Export both images | [scripts/export-stack.ps1](../../scripts/export-stack.ps1) |
