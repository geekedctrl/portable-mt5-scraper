"""Read-only SQLite market-data dashboard; Python standard library only."""
from contextlib import closing
from datetime import datetime, timezone
import base64
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sqlite3
import calendar
import math
import time
from urllib.parse import parse_qs, urlsplit

DATABASE = Path(os.environ.get('DATABASE_PATH', '/data/market.db'))
STATIC = Path(__file__).with_name('static')
LIVE_DATABASE = Path(os.environ.get('LIVE_DATABASE_PATH', str(DATABASE.with_name('live.db'))))
COLUMNS = ('time', 'open', 'high', 'low', 'close', 'tick_volume', 'spread', 'real_volume')
FRAME_SECONDS = {**{f'M{n}': n*60 for n in (1,2,3,4,5,6,10,12,15,20,30)},
                 **{f'H{n}': n*3600 for n in (1,2,3,4,6,8,12)},
                 'D1':86400, 'W1':604800, 'MN1':2592000}
DASHBOARD_USER = os.environ.get('DASHBOARD_USER', '')
DASHBOARD_PASSWORD = os.environ.get('DASHBOARD_PASSWORD', '')


def connect():
    connection = sqlite3.connect(DATABASE.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA query_only=ON')
    return connection


def live_snapshot(symbol=None):
    """Read the collector sidecar; heartbeat and price-change freshness differ."""
    import time
    now = time.time()
    if not LIVE_DATABASE.is_file():
        return dict(instruments=[], collector=None, quote=None, candles=[], server_time=now)
    with closing(sqlite3.connect(LIVE_DATABASE.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        instruments = [dict(r) for r in db.execute('SELECT * FROM instruments ORDER BY asset_class,symbol')]
        status = db.execute('SELECT * FROM collector_status WHERE id=1').fetchone()
        status = dict(status) if status else None
        if status:
            status['online'] = bool(status['connected'] and now-status['heartbeat'] <= max(15, status['quote_interval']*5))
        quote = None
        candles = []
        if symbol:
            row = db.execute('SELECT * FROM latest_quotes WHERE symbol=?', (symbol,)).fetchone()
            if row:
                quote = dict(row)
                age = max(0, now-quote['changed_at'])
                quote['unchanged_seconds'] = round(age, 1)
                if not status or not status['online']:
                    quote['status'] = 'offline'
                elif not quote['seen_change']:
                    quote['status'] = 'stale' if now-quote['tick_time_msc']/1000 > 15 else 'warming'
                else:
                    quote['status'] = 'live' if age <= 15 and now-quote['tick_time_msc']/1000 <= 15 else 'stale'
            candles = [dict(r) for r in db.execute('SELECT * FROM candle_status WHERE symbol=?', (symbol,))]
    return dict(instruments=instruments, collector=status, quote=quote, candles=candles, server_time=now)


def validate_table(connection, name):
    if not re.fullmatch(r'[A-Za-z0-9]+_[A-Za-z0-9]+', name):
        raise ValueError('Invalid table name')
    exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    if not exists:
        raise ValueError('Table not found')
    fields = {r['name'] for r in connection.execute(f'PRAGMA table_info("{name}")')}
    if not set(COLUMNS + ('symbol', 'timeframe')).issubset(fields):
        raise ValueError('Not a market-data table')
    return name.rsplit('_', 1)


def table_list(connection):
    tables = []
    names = connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    for row in names:
        name = row['name']
        try:
            symbol, frame = validate_table(connection, name)
        except ValueError:
            continue
        params = (symbol, frame)
        query = f'SELECT time FROM "{name}" WHERE symbol=? AND timeframe=? ORDER BY time '
        first = connection.execute(query + 'ASC LIMIT 1', params).fetchone()
        last = connection.execute(query + 'DESC LIMIT 1', params).fetchone()
        tables.append(dict(name=name, symbol=symbol, timeframe=frame,
                           first=first['time'] if first else None,
                           last=last['time'] if last else None))
    return tables


def load_bars(connection, query):
    name = query.get('table', [''])[0]
    symbol, frame = validate_table(connection, name)
    limit = int(query.get('limit', ['200'])[0])
    if not 1 <= limit <= 1000:
        raise ValueError('Limit must be between 1 and 1000')
    if query.get('range'):
        return load_range(connection, symbol, query['range'][0], limit)
    clauses, params = ['symbol=?', 'timeframe=?'], [symbol, frame]
    for key, operator in [('before', '<'), ('start', '>='), ('end', '<=')]:
        if query.get(key, [''])[0]:
            clauses.append('time' + operator + '?')
            params.append(int(query[key][0]))
    sql = f'SELECT {", ".join(COLUMNS)} FROM "{name}" WHERE ' + ' AND '.join(clauses)
    rows = connection.execute(sql + ' ORDER BY time DESC LIMIT ?', [*params, limit + 1]).fetchall()
    has_older = len(rows) > limit
    return dict(table=name, bars=[dict(r) for r in reversed(rows[:limit])], has_older=has_older)


def load_range(connection, symbol, period, limit):
    """Cover the requested span using stored candles and bounded OHLC summaries."""
    if period not in ('1Y','3Y','5Y','10Y','MAX'):
        raise ValueError('Unsupported history range')
    candidates=[t for t in table_list(connection) if t['symbol']==symbol and t['first'] is not None]
    if not candidates:
        return dict(table=f'{symbol}_H1', bars=[], has_older=False, range=period,
                    source_count=0,aggregated=False,range_start=None,range_end=None)
    end=max(t['last'] for t in candidates)
    oldest=min(t['first'] for t in candidates)
    if period=='MAX':
        requested_start=oldest
    else:
        anchor=datetime.fromtimestamp(end,timezone.utc)
        year=anchor.year-int(period[:-1])
        requested_start=int(anchor.replace(year=year,day=min(anchor.day,calendar.monthrange(year,anchor.month)[1])).timestamp())
    start=max(oldest,requested_start)
    covering=[t for t in candidates if t['first']<=start]
    fitting=[t for t in covering if (end-start)/FRAME_SECONDS.get(t['timeframe'],60)<=limit]
    source=min(fitting,key=lambda t:FRAME_SECONDS.get(t['timeframe'],60)) if fitting else max(covering,key=lambda t:FRAME_SECONDS.get(t['timeframe'],60))
    name=source['name'];frame=source['timeframe']
    # Prevent a range overview from monopolizing the dashboard's CPU budget.
    deadline=time.monotonic()+12
    connection.set_progress_handler(lambda:time.monotonic()>deadline,10000)
    where='symbol=? AND timeframe=? AND time>=? AND time<=?'
    params=(symbol,frame,start,end)
    count=connection.execute(f'SELECT COUNT(*) FROM "{name}" WHERE {where}',params).fetchone()[0]
    aggregated=count>limit
    if not aggregated:
        rows=connection.execute(f'SELECT {", ".join(COLUMNS)} FROM "{name}" WHERE {where} ORDER BY time',params).fetchall()
    else:
        width=max(1,math.ceil((end-start+1)/limit))
        rows=connection.execute(f'''WITH buckets AS (
            SELECT CAST((time-?)/? AS INTEGER) AS bucket,
                   MIN(time) AS first_time,MAX(time) AS last_time,
                   MAX(high) AS high,MIN(low) AS low,
                   SUM(tick_volume) AS tick_volume,SUM(real_volume) AS real_volume
            FROM "{name}" WHERE {where} GROUP BY bucket
        ) SELECT f.time,f.open,b.high,b.low,l.close,b.tick_volume,l.spread,b.real_volume
          FROM buckets b
          CROSS JOIN "{name}" f
          CROSS JOIN "{name}" l
          WHERE f.symbol=? AND f.timeframe=? AND f.time=b.first_time
            AND l.symbol=? AND l.timeframe=? AND l.time=b.last_time
          ORDER BY f.time''',(start,width,*params,symbol,frame,symbol,frame)).fetchall()
    return dict(table=name,bars=[dict(r) for r in rows],has_older=False,range=period,
                range_start=start,range_end=end,requested_start=requested_start,
                available_start=oldest,source_count=count,aggregated=aggregated)


class Handler(BaseHTTPRequestHandler):
    def send(self, status, body, mime='application/json'):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header('Content-Type', mime + '; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlsplit(self.path)
        if bool(DASHBOARD_USER) != bool(DASHBOARD_PASSWORD):
            self.send(503, dict(error='Dashboard authentication is misconfigured'))
            return
        if DASHBOARD_USER:
            supplied = self.headers.get('Authorization', '')
            expected = 'Basic ' + base64.b64encode(
                f'{DASHBOARD_USER}:{DASHBOARD_PASSWORD}'.encode()).decode()
            if not hmac.compare_digest(supplied, expected):
                self.send_response(401)
                self.send_header('WWW-Authenticate', 'Basic realm="Gateway", charset="UTF-8"')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
        assets = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
                  '/style.css': ('style.css', 'text/css')}
        if url.path in assets:
            filename, mime = assets[url.path]
            self.send(200, (STATIC / filename).read_bytes(), mime)
            return
        if url.path == '/health':
            self.send(200, dict(status='ok', database_exists=DATABASE.is_file()))
            return
        if url.path not in ('/api/tables', '/api/bars', '/api/count', '/api/live'):
            self.send(404, dict(error='Not found'))
            return
        try:
            if url.path == '/api/live':
                query = parse_qs(url.query)
                self.send(200, live_snapshot(query.get('symbol', [None])[0]))
                return
            with closing(connect()) as connection:
                query = parse_qs(url.query)
                if url.path == '/api/tables':
                    stat = DATABASE.stat()
                    result = dict(tables=table_list(connection), database_bytes=stat.st_size,
                                  modified=stat.st_mtime, fetched_at=datetime.now(timezone.utc).isoformat())
                elif url.path == '/api/bars':
                    result = load_bars(connection, query)
                else:
                    name = query.get('table', [''])[0]
                    symbol, frame = validate_table(connection, name)
                    # Bound expensive counts on very large history databases.
                    import time
                    deadline = time.monotonic() + 5
                    connection.set_progress_handler(lambda: time.monotonic() > deadline, 10000)
                    count = connection.execute(f'SELECT COUNT(*) FROM "{name}" WHERE symbol=? AND timeframe=?', (symbol, frame)).fetchone()[0]
                    result = dict(table=name, count=count)
            self.send(200, result)
        except (ValueError, OverflowError):
            self.send(400, dict(error='Invalid table, limit, or date filter'))
        except (sqlite3.Error, OSError):
            self.send(503, dict(error='Database is unavailable, busy, or the query took too long. Retry shortly.'))

    def log_message(self, format, *args):
        # No credentials or request parameters in logs.
        pass


if __name__ == '__main__':
    print('Read-only dashboard listening on 0.0.0.0:8080', flush=True)
    ThreadingHTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
