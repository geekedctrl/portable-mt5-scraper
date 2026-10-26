# Data and API reference

## Instruments and intervals

Default live FX subscriptions (20): EURUSD, GBPUSD, USDJPY, USDCHF, USDCAD,
AUDUSD, NZDUSD, EURGBP, EURJPY, GBPJPY, AUDJPY, EURCHF, EURAUD, EURCAD, EURNZD,
GBPCHF, GBPAUD, GBPCAD, GBPNZD, AUDCAD.

Current broker metals (14): XAUUSD, XAUEUR, XAUAUD, XAGUSD, XAGEUR, XPDUSD,
XPTUSD, XAGAUD, XAUCHF, XAUGBP, ALUMINIUM, COPPER, LEAD, NICKEL.

Discovery uses the broker's Forex/Metals instrument paths. Availability can vary
by broker/account and a listing does not guarantee an actively updating market.
`LIVE_SYMBOLS` overrides selection; unsupported names raise an error.

Native candle intervals (21): M1, M2, M3, M4, M5, M6, M10, M12, M15, M20, M30,
H1, H2, H3, H4, H6, H8, H12, D1, W1, MN1.
The canonical map is in `src/xauusd_sqlite.py`; the frontend also has an ordering
list. Keep both consistent when changing interval support.

Historical batch defaults still select the original 7 FX + 3 metals, whereas
live defaults select 34 instruments. Pass an explicit symbol list when backfilling
the full live universe. Historical reset is destructive and is not routine startup.

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

History views use `/api/bars?table=XAUUSD_H1&range=MAX&limit=200`; allowed range
values are `1Y`, `3Y`, `5Y`, `10Y`, and `MAX`. Year ranges use calendar subtraction
from the latest stored candle, including leap-day handling. The service may choose
a different native interval to fit the requested extent. If necessary, it returns
an OHLC overview with first open, highest high, lowest low, last close, summed
volumes, and last spread per bucket. These are display aggregates, not new MT5
intervals. The query deadline is 12 seconds; output remains bounded to 1000 bars.
The bucket-first indexed SQL strategy is important for large databases.

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
verified broker offset from newly stored live ticks and candles; its default is
zero. Existing rows are not rewritten. Verify the broker convention and session
boundaries before enabling it or making latency claims. Also distinguish
current-bar updates from completed candle closes.
