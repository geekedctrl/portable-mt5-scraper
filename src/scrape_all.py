"""Download all MT5 chart history for the configured default symbols."""
import argparse
import json
import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import MetaTrader5 as mt5
from xauusd_sqlite import TIMEFRAMES, create_schema, table_name

SYMBOLS = ['EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'USDCAD', 'AUDUSD', 'NZDUSD',
           'XAUUSD', 'XAUEUR', 'XAUAUD', 'XAGUSD', 'XAGEUR', 'XPDUSD', 'XPTUSD']
FRAMES = list(TIMEFRAMES)


def fetch(symbol, frame, cursor, count):
    for attempt in range(3):
        rates = mt5.copy_rates_from(symbol, TIMEFRAMES[frame], cursor, count)
        error = mt5.last_error()
        if rates is not None and len(rates):
            # A newly synchronized series can briefly return a stale page.
            # Retry forward pages before checking for MT5's boundary sentinel.
            if all(int(rate['time']) <= int(cursor.timestamp()) for rate in rates) or attempt == 2:
                return rates
            time.sleep(0.2)
            continue
        if attempt < 2:
            time.sleep(1)
    if rates is None and error[0] not in (1, -4):
        raise RuntimeError(f'{symbol}_{frame}: MT5 error {error}')
    return []


def history_start_confirmed(symbol, frame, first_timestamp):
    """Confirm MT5's first-candle sentinel instead of accepting arbitrary repeats.

    Some terminal builds clamp an earlier request to the first available candle.
    Only accept the exact known boundary, with a live connection, three times.
    """
    for attempt in range(3):
        info = mt5.terminal_info()
        if info is None or not info.connected:
            raise RuntimeError(f'{symbol}_{frame}: MT5 disconnected at history boundary')
        probe = mt5.copy_rates_from(symbol, TIMEFRAMES[frame], first_timestamp - 1, 1)
        error = mt5.last_error()
        if probe is None:
            if error[0] not in (1, -4):
                raise RuntimeError(f'{symbol}_{frame}: boundary probe failed: {error}')
        elif len(probe) and not (len(probe) == 1 and int(probe[0]['time']) == first_timestamp):
            return False
        if attempt < 2:
            time.sleep(0.2)
    return True


def download(connection, symbol, frame, batch_size, max_bars=0):
    table = table_name(symbol, frame)
    create_schema(connection, table)
    cursor = datetime.now(timezone.utc)
    fetched = 0
    previous_oldest = None
    stop_reason = 'bar_limit'
    while not max_bars or fetched < max_bars:
        count = min(batch_size, max_bars - fetched) if max_bars else batch_size
        rates = fetch(symbol, frame, cursor, count)
        if len(rates) == 0:
            stop_reason = 'no_more_bars'
            break
        oldest = min(int(r['time']) for r in rates)
        if oldest > int(cursor.timestamp()):
            if (len(rates) == 1 and previous_oldest == oldest
                    and history_start_confirmed(symbol, frame, oldest)):
                stop_reason = 'confirmed_first_candle'
                print(f'{table}: reached confirmed start of available MT5 history', flush=True)
                break
            raise RuntimeError(f'{table}: history cursor did not move backwards')
        if any(int(rate['time']) > int(cursor.timestamp()) for rate in rates):
            raise RuntimeError(f'{table}: MT5 returned bars after the requested cursor')
        fetched += len(rates)
        rows = [(symbol, frame, int(r['time']), float(r['open']), float(r['high']),
                 float(r['low']), float(r['close']), int(r['tick_volume']),
                 int(r['spread']), int(r['real_volume'])) for r in rates]
        with connection:
            connection.executemany(f'INSERT OR REPLACE INTO "{table}" VALUES (?,?,?,?,?,?,?,?,?,?)', rows)
        cursor = datetime.fromtimestamp(oldest - 1, timezone.utc)
        previous_oldest = oldest
        print(f'{table}: downloaded through {datetime.fromtimestamp(oldest, timezone.utc).isoformat()}', flush=True)
    count, first, last = connection.execute(
        f'SELECT COUNT(*), MIN(time), MAX(time) FROM "{table}"').fetchone()
    if not count:
        raise RuntimeError(f'{table}: no history returned')
    invalid = connection.execute(f'''SELECT COUNT(*) FROM "{table}" WHERE
        high < low OR high < open OR high < close OR low > open OR low > close
        OR tick_volume < 0 OR real_volume < 0 OR spread < 0
        OR symbol != ? OR timeframe != ?''', (symbol, frame)).fetchone()[0]
    if invalid:
        raise RuntimeError(f'{table}: {invalid} invalid bars')
    return dict(table=table, rows=count, stop_reason=stop_reason,
                first_utc=datetime.fromtimestamp(first, timezone.utc).isoformat(),
                last_utc=datetime.fromtimestamp(last, timezone.utc).isoformat())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=Path(__file__).resolve().parent.parent / 'data' / 'xauusd.db')
    parser.add_argument('--reset', action='store_true', help='Clear all tables in the selected database before scraping')
    parser.add_argument('--symbols', nargs='+', default=SYMBOLS)
    parser.add_argument('--timeframes', nargs='+', choices=TIMEFRAMES, default=FRAMES)
    parser.add_argument('--batch-size', type=int, default=50000)
    parser.add_argument('--max-bars-per-table', type=int, default=0,
                        help='Limit bars per table for a smoke test (0: all available history)')
    args = parser.parse_args()
    if args.max_bars_per_table < 0:
        parser.error('--max-bars-per-table cannot be negative')
    if args.batch_size < 1:
        parser.error('--batch-size must be positive')
    for symbol in args.symbols:
        for frame in args.timeframes:
            table_name(symbol, frame)
    terminal_path = os.environ.get('MT5_TERMINAL_PATH')
    # The container runner has already authenticated in this Python process.
    # Keep its connection rather than disconnecting/reopening the terminal.
    current = mt5.terminal_info()
    connected = current is not None and current.connected
    for attempt in range(5):
        if connected:
            break
        options = {'timeout': 10000}
        if os.environ.get('MT5_LOGIN'):
            options.update(login=int(os.environ['MT5_LOGIN']),
                           password=os.environ['MT5_PASSWORD'],
                           server=os.environ['MT5_SERVER'])
        connected = (mt5.initialize(terminal_path, portable=True, **options)
                     if terminal_path else mt5.initialize(**options))
        if not connected:
            mt5.shutdown()
            if attempt < 4:
                print('Retrying MT5 connection...', flush=True)
                time.sleep(2)
    if not connected:
        raise RuntimeError(f'MT5 initialization failed: {mt5.last_error()}')
    report = []
    failures = []
    try:
        terminal = mt5.terminal_info()
        if terminal is None or not terminal.connected:
            raise RuntimeError('MT5 must be connected to the broker')
        for symbol in args.symbols:
            if not mt5.symbol_select(symbol, True):
                raise RuntimeError(f'Unavailable symbol: {symbol}')
        args.db.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(args.db)) as connection:
            if args.reset:
                tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
                with connection:
                    for (name,) in tables:
                        connection.execute('DROP TABLE "' + name.replace('"', '""') + '"')
                connection.execute('VACUUM')
                print(f'Cleared {args.db}', flush=True)
            for symbol in args.symbols:
                for frame in args.timeframes:
                    try:
                        result = download(connection, symbol, frame, args.batch_size, args.max_bars_per_table)
                        report.append(result)
                        print(json.dumps(result), flush=True)
                    except Exception as exc:
                        failures.append(str(exc))
                        print(f'FAILED: {exc}', flush=True)
            integrity = connection.execute('PRAGMA integrity_check').fetchone()[0]
        summary = dict(max_bars_per_table=args.max_bars_per_table,
                       history_scope="bounded test" if args.max_bars_per_table else "all available",
                       database=str(args.db.resolve()), maxbars=terminal.maxbars,
                       integrity_check=integrity, tables=report, failures=failures)
        args.db.with_suffix('.report.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
        print(f'Finished: {len(report)} tables, {sum(r["rows"] for r in report):,} bars, {len(failures)} failures; integrity={integrity}', flush=True)
        if failures or integrity != 'ok':
            raise SystemExit(1)
    finally:
        mt5.shutdown()


if __name__ == '__main__':
    main()
