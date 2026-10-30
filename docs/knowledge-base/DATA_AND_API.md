# Data and API reference

## Instruments and intervals

Default live FX subscriptions (7): EURUSD, GBPUSD, USDJPY, USDCHF, USDCAD,
AUDUSD, NZDUSD.

Default live metals (7): XAUUSD, XAUEUR, XAUAUD, XAGUSD, XAGEUR, XPDUSD,
XPTUSD. Other broker-listed instruments can be added through `LIVE_SYMBOLS` as
the supported universe grows.

Discovery uses the broker's Forex/Metals instrument paths. Availability can vary
by broker/account and a listing does not guarantee an actively updating market.
`LIVE_SYMBOLS` overrides selection; unsupported names raise an error.

Stored candle intervals (9): M1, M5, M15, M30, H1, H4, D1, W1, MN1. Dashboard
and provider history presets are D5, 1M, 6M, YTD, 1Y, 5Y, and Max; these are
date ranges, not candle intervals. The API backs them with stored intervals;
W1 and MN1 support long-range views.
The canonical map is in `src/xauusd_sqlite.py`; the frontend also has an ordering
list. Keep both consistent when changing interval support.

Historical and live defaults select the same seven FX pairs and seven metals.
Pass an explicit symbol list when backfilling a larger universe. Historical reset
is destructive and is not routine startup.

## Storage

`/data/market.db` contains `SYMBOL_TIMEFRAME` candle tables, such as `XAUUSD_H1`.
Columns are `symbol`, `timeframe`, `time` (integer seconds), `open`, `high`, `low`,
`close`, `tick_volume`, `spread`, `real_volume`. The primary key is
`(symbol, timeframe, time)`. Overlapping updates upsert existing bars.
Constrain both symbol and timeframe in queries to use this index efficiently;
an unqualified sort by time can scan a very large table.

`/data/live.db` holds small operational tables:

| Table | Role |
| --- | --- |
| `instruments` | Current subscription list, asset class, description, precision, availability |
| `latest_quotes` | Latest bid/ask, spread, broker tick milliseconds, receipt/change times |
| `collector_status` | Heartbeat, connection state, scheduling, cycle, latest error |
| `candle_status` | Current bar timestamp, update time, bounded-catch-up flag, first/last stored bar, recent bar count and gap count (last 10,000 bars), and consecutive unavailable refresh count per symbol/interval |
| `candle_health` | Candle-worker health and failure count |
| `seed_progress` | Progressive initial request size per symbol/interval |

The subscription table is replaced at startup; old quote rows can remain after a
subscription is removed. Treat `instruments` as the active universe. There is no
complete tick archive. SQLite WAL is not explicitly enabled. Do not enable WAL
or immutable reads casually across Wine writers and the Linux reader; test
concurrency and visibility first.

`LIVE_SYMBOLS` may select a fixed startup subset to reduce work, but it controls
both quote and candle subscriptions and is not a dynamic per-client priority list.

## Read-only HTTP API

All routes below are GET requests on the dashboard. There is no arbitrary SQL API.

| Route | Contract |
| --- | --- |
| `/health` | HTTP service/database-file presence; not broker connection health |
| `/api/tables` | Table name, symbol, timeframe, first/last timestamps, database size and modification metadata |
| `/api/bars?table=XAUUSD_H1&limit=200` | Chronological bars, paging metadata; limit 1–1000 |
| `/api/count?table=XAUUSD_H1` | Exact count with a bounded query deadline |
| `/api/live?symbol=EURUSD` | Instruments, collector status, selected quote and candle statuses, server time |

Bar queries support `before` (exclusive) and `start`/`end` (inclusive Unix seconds).
Normal browsing avoids full-table counts. Missing `live.db` yields an empty live
response without creating a new database.

## Gateway provider API (v1)

The optional read-only provider contract is intended for another trusted service
on a shared Docker network. It does not store polling ticks; quotes come from the
latest-quote sidecar and history comes from stored MT5 candles. All endpoints use
the dashboard's existing optional Basic authentication.

Interactive Swagger UI is served at `/docs` and the OpenAPI 3.0 document at
`/openapi.json`.

| Route | Contract |
| --- | --- |
| `/provider/v1/status` | Provider readiness, database/collector/candle-worker checks, quote freshness counts, and latest `cycle_duration_ms`, `mt5_poll_ms`, `sqlite_write_ms`, `quote_age_max_ms`, and `poll_overruns` measurements |
| `/provider/v1/instruments?asset_class=fx&search=EUR` | Current subscribed instruments, optionally filtered by `fx`/`metal` and case-insensitive symbol/description search |
| `/provider/v1/quotes?symbols=EURUSD,GBPUSD` | One ordered result for every requested symbol; each is available with nested quote fields or unavailable with a reason |
| `/provider/v1/history/EURUSD?interval=1m&limit=500&before=...` | Stored candles in chronological order, pagination, and stored coverage metadata |

History intervals accept the nine stored MT5 names and consumer aliases such
as `1m`, `5m`, `15m`, `30m`, `1h`, `4h`, and `1d`. A history `range` sets the
date window; when `interval` or `timeframe` is also supplied, that value selects
the stored candle timeframe. Supported windows are `1D`, `5D`, `D5`, `1M`, `3M`,
`6M`, `YTD`, `1Y`, `5Y`, and `MAX`. For compatibility with Slate's current chart
adapter, `interval=1h&range=3M` resolves to native H4 candles. Without an explicit
interval, standard presets such as `D5`, `1M`, `6M`, `YTD`, `1Y`, `5Y`, and
`MAX` select their default native timeframe. These are views of stored data and
do not trigger broker downloads. Quotes are bounded to 100 symbols per request.
Quote results use `status=available|unavailable`; unavailable reasons are
`not_subscribed`, `quote_not_received`, or `live_store_unavailable`. A present
quote has `freshness=live|stale|warming|offline`, `quoteAgeAtApiMs` (time since
local collector receipt), and `brokerTimestampSkewMs` (broker clock relative to
the gateway clock). These separate local delivery age from broker timestamp
interpretation. History coverage reports the
stored start/end, the collector's recent bar count used for gap monitoring,
latest catch-up-limited flag, gap count, and consecutive unavailable refreshes
when candle-worker status is available. It does not scan a potentially huge table
to count every historical row.
These coverage fields describe local collector state; they do not guarantee
complete broker history. Provider readiness is degraded if either database,
collector, or healthy candle-worker check is unavailable/false.

For local Slate integration, `docker/compose.slate-local.yaml` optionally adds
only the dashboard/API container to Slate's dev and production networks, with
Docker DNS name `mt5-market-provider`. It publishes no additional host port.
Set `SLATE_DOCKER_NETWORK` or `SLATE_PROD_DOCKER_NETWORK` if either network name
differs, then include the overlay when applying the dashboard service (see
Operations). Slate's quote worker must also have its provider URL configured.

History views use `/api/bars?table=XAUUSD_H1&range=MAX&limit=200`; allowed range
values are `D5`, `1M`, `6M`, `YTD`, `1Y`, `5Y`, and `MAX`. Date ranges end at the
latest stored candle; year and month subtraction handles calendar boundaries.
The service may choose
a different native interval to fit the requested extent. If necessary, it returns
an OHLC overview with first open, highest high, lowest low, last close, summed
volumes, and last spread per bucket. These are display aggregates, not new MT5
intervals. The query deadline is 12 seconds; output remains bounded to 1000 bars.
The bucket-first indexed SQL strategy is important for large databases.
The dashboard caches candle table names and each table's oldest/newest stored
timestamp in process memory. It reuses that coverage while `market.db`'s file
size and modification time are unchanged, and refreshes it after a detected
change. This keeps repeated range selection from rescanning every table. Since
freshness follows file metadata, changes invisible to both size and modification
time can remain cached until the next detectable database change or dashboard
process restart. Range logs report coverage-selection, range SQL, and complete
response timing without logging query parameters or credentials.

Ranges use stored data only and do not start a history download. Max means the
oldest available stored history, not guaranteed broker inception. The dashboard
labels aggregated overviews and CSV exports contain only the displayed bars.
Selecting an interval or Latest leaves range mode. Range charts are not continually
reaggregated by the normal refresh loop; live quote updates continue separately.

## Freshness and time

Live status combines connection/heartbeat, observed quote changes, and tick age;
unchanged prices can become stale. Candle forming labels require a fresh quote,
matching source bar, and the proper interval boundary. Monthly boundaries use
calendar months. Historical range views suppress forming labels.

Broker timestamps were observed about two hours ahead of collector wall time
when interpreted as Unix time. `MT5_TIME_OFFSET_SECONDS` optionally subtracts a
verified broker offset from newly stored live ticks, live candles, and historical
backfill rows; its default is zero. Existing rows are not rewritten. Verify the
broker convention and session boundaries before enabling it or making latency
claims. Also distinguish current-bar updates from completed candle closes.
