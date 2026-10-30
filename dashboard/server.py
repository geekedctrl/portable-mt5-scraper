"""Read-only SQLite market-data dashboard; Python standard library only."""
from contextlib import closing
from datetime import datetime, timezone, timedelta
import base64
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import calendar
import math
import time
import threading
from urllib.parse import parse_qs, urlsplit

DATABASE = Path(os.environ.get('DATABASE_PATH', '/data/market.db'))
STATIC = Path(__file__).with_name('static')
LIVE_DATABASE = Path(os.environ.get('LIVE_DATABASE_PATH', str(DATABASE.with_name('live.db'))))
CANDLE_WORKER_STALE_SECONDS = 180
COLUMNS = ('time', 'open', 'high', 'low', 'close', 'tick_volume', 'spread', 'real_volume')
FRAME_SECONDS = {**{f'M{n}': n*60 for n in (1,5,15,30)},
                 **{f'H{n}': n*3600 for n in (1,4)},
                 'D1':86400, 'W1':604800, 'MN1':2592000}
FRAME_ALIASES = {
    '1m':'M1','5m':'M5','15m':'M15','30m':'M30',
    '1h':'H1','4h':'H4',
    '1d':'D1','1w':'W1','1mo':'MN1',
}
SLATE_RANGE_FRAME = {'D5':'M15','1M':'M30','6M':'D1','YTD':'D1',
                     '1Y':'D1','5Y':'W1','MAX':'MN1'}
SLATE_WINDOW_RANGE_FRAME = {'1D':'M1','5D':'M15','3M':'H4'}
DASHBOARD_USER = os.environ.get('DASHBOARD_USER', '')
DASHBOARD_PASSWORD = os.environ.get('DASHBOARD_PASSWORD', '')
_coverage_cache_lock = threading.Lock()
_coverage_cache = {'signature': None, 'tables': None}
logger = logging.getLogger(__name__)


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
                quote['receipt_age_seconds'] = round(max(0,now-quote['received_at']),3)
                quote['broker_timestamp_skew_seconds'] = round(quote['tick_time_msc']/1000-now,3)
                if not status or not status['online']:
                    quote['status'] = 'offline'
                elif not quote['seen_change']:
                    quote['status'] = 'stale' if now-quote['tick_time_msc']/1000 > 15 else 'warming'
                else:
                    quote['status'] = 'live' if age <= 15 and now-quote['tick_time_msc']/1000 <= 15 else 'stale'
            candles = [dict(r) for r in db.execute('SELECT * FROM candle_status WHERE symbol=?', (symbol,))]
    return dict(instruments=instruments, collector=status, quote=quote, candles=candles, server_time=now)


def provider_status():
    """Small, versioned health payload for trusted internal Docker clients."""
    now=time.time()
    snapshot=live_snapshot()
    collector=snapshot['collector']
    market_available=DATABASE.is_file()
    candle_worker=None
    quote_counts=dict(live=0,stale=0,warming=0,offline=0,missing=0)
    if LIVE_DATABASE.is_file():
        with closing(sqlite3.connect(LIVE_DATABASE.resolve().as_uri()+'?mode=ro',uri=True,timeout=1)) as db:
            db.row_factory=sqlite3.Row
            db.execute('PRAGMA query_only=ON')
            worker=db.execute('SELECT updated_at,failed_count FROM candle_health WHERE id=1').fetchone()
            candle_worker=dict(worker) if worker else None
            if candle_worker:
                progress_age=max(0,now-float(candle_worker['updated_at'] or 0))
                candle_worker['progress_age_seconds']=round(progress_age,1)
                candle_worker['progress_fresh']=progress_age<=CANDLE_WORKER_STALE_SECONDS
            latest={row['symbol']:dict(row) for row in db.execute('SELECT symbol,changed_at,tick_time_msc,seen_change FROM latest_quotes')}
            for instrument in db.execute('SELECT symbol FROM instruments'):
                row=latest.get(instrument['symbol'])
                if not row:
                    quote_counts['missing']+=1
                    continue
                tick_age=now-row['tick_time_msc']/1000
                if not collector or not collector.get('online'):
                    freshness='offline'
                elif not row['seen_change']:
                    freshness='stale' if tick_age>15 else 'warming'
                else:
                    freshness='live' if now-row['changed_at']<=15 and tick_age<=15 else 'stale'
                quote_counts[freshness]+=1
    checks=dict(live_database_available=LIVE_DATABASE.is_file(),market_database_available=market_available,
                collector_online=bool(collector and collector.get('online')),
                candle_worker_available=bool(candle_worker and candle_worker.get('progress_fresh')),
                candle_worker_healthy=bool(candle_worker and candle_worker.get('progress_fresh')
                                           and candle_worker.get('failed_count')==0))
    ready=all(checks.values())
    return dict(provider='mt5-market-gateway',api_version='v1',status='ok' if ready else 'degraded',ready=ready,
                checks=checks,collector=collector,candle_worker=candle_worker,quote_counts=quote_counts,
                instruments=len(snapshot['instruments']),server_time=now)


def provider_instruments(asset_class=None, search=None):
    if search and len(search)>100:
        raise ValueError('search must be at most 100 characters')
    snapshot=live_snapshot()
    instruments=[{**item,'available':bool(item['available'])} for item in snapshot['instruments']]
    if asset_class:
        requested=asset_class.lower()
        if requested not in ('fx','metal'):
            raise ValueError('asset_class must be fx or metal')
        instruments=[item for item in instruments if item['asset_class'].lower()==requested]
    if search:
        term=search.casefold()
        instruments=[item for item in instruments if term in item['symbol'].casefold() or term in item['description'].casefold()]
    return dict(provider='mt5-market-gateway',instruments=instruments,server_time=snapshot['server_time'])


def provider_quotes(symbols):
    symbols=list(dict.fromkeys(symbol.upper() for symbol in symbols))
    if not symbols or len(symbols)>100 or any(not re.fullmatch(r'[A-Z0-9]+',symbol) for symbol in symbols):
        raise ValueError('Provide 1 to 100 alphanumeric symbols')
    now=time.time()
    placeholders=','.join('?' for _ in symbols)
    if not LIVE_DATABASE.is_file():
        return dict(provider='mt5-market-gateway',quotes=[dict(symbol=symbol,status='unavailable',freshness='offline',reason='live_store_unavailable',quote=None) for symbol in symbols],server_time=now)
    with closing(sqlite3.connect(LIVE_DATABASE.resolve().as_uri()+'?mode=ro',uri=True,timeout=1)) as db:
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        instruments={row['symbol']:dict(row) for row in db.execute(
            f'SELECT * FROM instruments WHERE symbol IN ({placeholders})',symbols)}
        rows={row['symbol']:dict(row) for row in db.execute(
            f'SELECT * FROM latest_quotes WHERE symbol IN ({placeholders})',symbols)}
        status_row=db.execute('SELECT * FROM collector_status WHERE id=1').fetchone()
        collector=dict(status_row) if status_row else None
    if collector:
        collector['online']=bool(collector['connected'] and now-collector['heartbeat']<=max(15,collector['quote_interval']*5))
    quotes=[]
    for symbol in symbols:
        row=rows.get(symbol);instrument=instruments.get(symbol)
        if not instrument:
            quotes.append(dict(symbol=symbol,status='unavailable',freshness=None,reason='not_subscribed',quote=None))
            continue
        if not row:
            status='warming' if collector and collector.get('online') else 'offline'
            quotes.append(dict(symbol=symbol,status='unavailable',freshness=status,reason='quote_not_received',quote=None))
            continue
        age=max(0,now-row['changed_at'])
        tick_age=now-row['tick_time_msc']/1000
        if not collector or not collector.get('online'):
            freshness='offline'
        elif not row['seen_change']:
            freshness='stale' if tick_age>15 else 'warming'
        else:
            freshness='live' if age<=15 and tick_age<=15 else 'stale'
        tick_time=row['tick_time_msc']/1000
        quote=dict(
            symbol=symbol,name=instrument['description'] or symbol,
            price=round((row['bid']+row['ask'])/2,instrument['digits']),
            change=None,changePercent=None,open=None,high=None,low=None,previousClose=None,
            bid=row['bid'],ask=row['ask'],spread=row['spread'],spreadPoints=row['spread_points'],
            volume=None,avgVolume=None,marketCap=None,pe=None,eps=None,dividendYield=None,
            week52High=None,week52Low=None,beta=None,sharesOutstanding=None,
            currency=None,exchange='MT5',marketState=None,time=tick_time,
            source='mt5',sourceTimestamp=datetime.fromtimestamp(tick_time,timezone.utc).isoformat(),
            retrievedAt=datetime.fromtimestamp(row['received_at'],timezone.utc).isoformat(),
            quoteAgeAtApiMs=round(max(0,now-row['received_at'])*1000,3),
            brokerTimestampSkewMs=round(tick_time*1000-now*1000,3),
            freshness=freshness,staleFallback=freshness!='live',delayMinutes=round(max(0,now-tick_time)/60,3),
        )
        quotes.append(dict(symbol=symbol,status='available',freshness=freshness,quote=quote))
    return dict(provider='mt5-market-gateway',quotes=quotes,server_time=now)


def provider_history(symbol, query):
    if not re.fullmatch(r'[A-Za-z0-9]+',symbol):
        raise ValueError('Invalid symbol')
    symbol=symbol.upper()
    period=query.get('range',[''])[0].upper()
    interval_values=query.get('timeframe',query.get('interval',[]))
    requested_interval=interval_values[0] if interval_values else None
    if period:
        if period not in SLATE_RANGE_FRAME and period not in SLATE_WINDOW_RANGE_FRAME:
            raise ValueError('Unsupported range')
        if requested_interval:
            frame=FRAME_ALIASES.get(requested_interval.lower(),requested_interval.upper())
            # Slate's current 4h adapter uses its Yahoo-compatible 1h interval
            # with a 3-month window. MT5 has a native H4 series, so resolve that
            # specific request to H4 instead of returning H1 candles.
            if period=='3M' and requested_interval.lower()=='1h':
                frame='H4'
        else:
            frame=(SLATE_RANGE_FRAME[period] if period in SLATE_RANGE_FRAME
                   else SLATE_WINDOW_RANGE_FRAME[period])
    else:
        requested_interval=requested_interval or 'M1'
        frame=FRAME_ALIASES.get(requested_interval.lower(),requested_interval.upper())
    if frame not in FRAME_SECONDS and frame!='MN1':
        raise ValueError('Unsupported timeframe')
    table=f'{symbol}_{frame}'
    with closing(connect()) as db:
        validate_table(db,table)
        forwarded=dict(query)
        # The provider resolves chart presets to a native MT5 timeframe and
        # date bounds above; load_bars' dashboard range presets are separate.
        forwarded.pop('range',None)
        forwarded['table']=[table]
        if period:
            latest=db.execute(f'SELECT MAX(time) FROM "{table}" WHERE symbol=? AND timeframe=?',(symbol,frame)).fetchone()[0]
            if latest is not None and period!='MAX':
                end=datetime.fromtimestamp(latest,timezone.utc)
                if period == 'D5':
                    start=end-timedelta(days=5)
                elif period=='YTD':
                    start=datetime(end.year,1,1,tzinfo=timezone.utc)
                elif period.endswith('D'):
                    start=end-timedelta(days=int(period[:-1]))
                elif period.endswith('Y'):
                    years=int(period[:-1]);year=end.year-years
                    start=end.replace(year=year,day=min(end.day,calendar.monthrange(year,end.month)[1]))
                elif period.endswith('M'):
                    months=int(period[:-1])
                    month_index=end.year*12+end.month-1-months
                    year,month=divmod(month_index,12)
                    month+=1
                    start=end.replace(year=year,month=month,day=min(end.day,calendar.monthrange(year,month)[1]))
                else:
                    months=6
                    month_index=end.year*12+end.month-1-months
                    year,month=divmod(month_index,12)
                    month+=1
                    start=end.replace(year=year,month=month,day=min(end.day,calendar.monthrange(year,month)[1]))
                forwarded['start']=[int(start.timestamp())]
                forwarded['end']=[latest]
        coverage=db.execute(f'''SELECT MIN(time) AS first_time,MAX(time) AS last_time
                                 FROM "{table}" WHERE symbol=? AND timeframe=?''',(symbol,frame)).fetchone()
        result=load_bars(db,forwarded)
        candle_status=None
        if LIVE_DATABASE.is_file():
            try:
                with closing(sqlite3.connect(LIVE_DATABASE.resolve().as_uri()+'?mode=ro',uri=True,timeout=1)) as live_db:
                    live_db.row_factory=sqlite3.Row
                    live_db.execute('PRAGMA query_only=ON')
                    row=live_db.execute('SELECT * FROM candle_status WHERE symbol=? AND timeframe=?',(symbol,frame)).fetchone()
                    candle_status=dict(row) if row else None
            except sqlite3.Error:
                candle_status=None
    bars=[dict(time=row['time'],open=row['open'],high=row['high'],low=row['low'],close=row['close'],
               volume=row['tick_volume'],tickVolume=row['tick_volume'],spread=row['spread'],
               realVolume=row['real_volume'],source='mt5') for row in result['bars']]
    return dict(provider='mt5-market-gateway',symbol=symbol,timeframe=frame,interval=next((k for k,v in FRAME_ALIASES.items() if v==frame),frame),
                range=period or None,bars=bars,hasOlder=result['has_older'],
                nextBefore=bars[0]['time'] if bars and result['has_older'] else None,
                coverage=dict(start=coverage['first_time'],end=coverage['last_time'],
                              recentBarCount=candle_status['bar_count'] if candle_status else None,
                              catchupLimited=bool(candle_status['catchup_limited']) if candle_status else None,
                              gapCount=candle_status['gap_count'] if candle_status else None,
                              unavailableRefreshes=candle_status['unavailable'] if candle_status else None),
                server_time=time.time())


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


def database_signature():
    """Track the database and WAL because committed writes may remain in WAL."""
    signature = []
    for path in (DATABASE, Path(str(DATABASE) + '-wal')):
        try:
            stat = path.stat()
            signature.append((stat.st_mtime_ns, stat.st_size))
        except OSError:
            signature.append(None)
    return tuple(signature)


def cached_table_list(connection):
    """Cache indexed per-table coverage while the market DB file is unchanged."""
    db_path = connection.execute('PRAGMA database_list').fetchone()[2]
    if not db_path or Path(db_path).resolve() != DATABASE.resolve():
        return table_list(connection)
    signature = database_signature()
    with _coverage_cache_lock:
        if _coverage_cache['signature'] == signature and _coverage_cache['tables'] is not None:
            return _coverage_cache['tables']
        tables = table_list(connection)
        after = database_signature()
        # A commit during enumeration could make the snapshot internally stale.
        # Retry once on the same read-only connection before publishing it.
        if after != signature:
            tables = table_list(connection)
            after = database_signature()
        _coverage_cache.update(signature=after, tables=tables)
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
    range_started = time.perf_counter()
    period=period.upper()
    if period not in ('D5','1M','6M','YTD','1Y','5Y','MAX'):
        raise ValueError('Unsupported history range')
    selection_started = time.perf_counter()
    candidates=[t for t in cached_table_list(connection) if t['symbol']==symbol and t['first'] is not None]
    if not candidates:
        return dict(table=f'{symbol}_H1', bars=[], has_older=False, range=period,
                    source_count=0,aggregated=False,range_start=None,range_end=None)
    end=max(t['last'] for t in candidates)
    oldest=min(t['first'] for t in candidates)
    if period=='MAX':
        requested_start=oldest
    else:
        anchor=datetime.fromtimestamp(end,timezone.utc)
        if period=='D5':
            requested_start=int((anchor-timedelta(days=5)).timestamp())
        elif period=='YTD':
            requested_start=int(datetime(anchor.year,1,1,tzinfo=timezone.utc).timestamp())
        elif period in ('1M','6M'):
            months=1 if period=='1M' else 6
            month_index=anchor.year*12+anchor.month-1-months
            year,month=divmod(month_index,12)
            month+=1
            requested_start=int(anchor.replace(year=year,month=month,day=min(anchor.day,calendar.monthrange(year,month)[1])).timestamp())
        else:
            years=1 if period=='1Y' else 5
            year=anchor.year-years
            requested_start=int(anchor.replace(year=year,day=min(anchor.day,calendar.monthrange(year,anchor.month)[1])).timestamp())
    start=max(oldest,requested_start)
    covering=[t for t in candidates if t['first']<=start]
    fitting=[t for t in covering if (end-start)/FRAME_SECONDS.get(t['timeframe'],60)<=limit]
    source=min(fitting,key=lambda t:FRAME_SECONDS.get(t['timeframe'],60)) if fitting else max(covering,key=lambda t:FRAME_SECONDS.get(t['timeframe'],60))
    name=source['name'];frame=source['timeframe']
    selection_ms=(time.perf_counter()-selection_started)*1000
    # Prevent a range overview from monopolizing the dashboard's CPU budget.
    deadline=time.monotonic()+12
    connection.set_progress_handler(lambda:time.monotonic()>deadline,10000)
    where='symbol=? AND timeframe=? AND time>=? AND time<=?'
    params=(symbol,frame,start,end)
    sql_started=time.perf_counter()
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
    sql_ms=(time.perf_counter()-sql_started)*1000
    logger.info('bars range=%s symbol=%s selection_ms=%.2f sql_ms=%.2f total_ms=%.2f',
                period,symbol,selection_ms,sql_ms,(time.perf_counter()-range_started)*1000)
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
                  '/style.css': ('style.css', 'text/css'),
                  '/chart_paging.js': ('chart_paging.js', 'text/javascript')}
        if url.path == '/openapi.json':
            self.send(200,(STATIC/'openapi.json').read_bytes(),'application/vnd.oai.openapi+json')
            return
        swagger_asset=re.fullmatch(r'/vendor/swagger-ui/(swagger-ui\.css|swagger-ui-bundle\.js|swagger-overrides\.css|swagger-init\.js|favicon-32x32\.png)',url.path)
        if swagger_asset:
            filename=swagger_asset.group(1)
            mime='text/css' if filename.endswith('.css') else 'text/javascript' if filename.endswith('.js') else 'image/png'
            self.send(200,(STATIC/'vendor'/'swagger-ui'/filename).read_bytes(),mime)
            return
        if url.path in ('/docs','/docs/'):
            self.send(200,(STATIC/'swagger.html').read_bytes(),'text/html')
            return
        if url.path in assets:
            filename, mime = assets[url.path]
            self.send(200, (STATIC / filename).read_bytes(), mime)
            return
        if url.path == '/health':
            self.send(200, dict(status='ok', database_exists=DATABASE.is_file()))
            return
        provider_paths=('/provider/v1/status','/provider/v1/instruments','/provider/v1/quotes')
        history_match=re.fullmatch(r'/provider/v1/history/([A-Za-z0-9]+)',url.path)
        if url.path in provider_paths or history_match:
            try:
                query=parse_qs(url.query)
                if url.path=='/provider/v1/status':
                    result=provider_status()
                elif url.path=='/provider/v1/instruments':
                    asset_classes=[value.lower() for item in query.get('asset_class',[]) for value in item.split(',') if value]
                    if len(asset_classes)>1 or (asset_classes and asset_classes[0] not in ('fx','metal')):
                        raise ValueError('Invalid asset class filter')
                    result=provider_instruments(asset_classes[0] if asset_classes else None,query.get('search',[''])[0].strip() or None)
                elif url.path=='/provider/v1/quotes':
                    symbols=[item for value in query.get('symbols',[]) for item in value.split(',') if item]
                    result=provider_quotes(symbols)
                else:
                    result=provider_history(history_match.group(1),query)
                self.send(200,result)
            except (ValueError,OverflowError):
                self.send(400,dict(error='Invalid provider query'))
            except (sqlite3.Error,OSError):
                self.send(503,dict(error='Market data is unavailable or busy. Retry shortly.'))
            return
        if url.path not in ('/api/tables', '/api/bars', '/api/count', '/api/live'):
            self.send(404, dict(error='Not found'))
            return
        try:
            if url.path == '/api/live':
                query = parse_qs(url.query)
                self.send(200, live_snapshot(query.get('symbol', [None])[0]))
                return
            request_started = time.perf_counter()
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
            if url.path == '/api/bars' and query.get('range'):
                logger.info('bars response range=%s total_response_ms=%.2f',
                            query['range'][0], (time.perf_counter()-request_started)*1000)
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
