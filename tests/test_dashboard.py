"""Dashboard pagination, filtering, and database access protections."""
from contextlib import closing
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('dashboard_server',Path(__file__).resolve().parents[1]/'dashboard/server.py')
app=importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


def populate(db):
    db.execute('CREATE TABLE EURUSD_M1 (symbol TEXT,timeframe TEXT,time INTEGER,open REAL,high REAL,low REAL,close REAL,tick_volume INTEGER,spread INTEGER,real_volume INTEGER,PRIMARY KEY(symbol,timeframe,time))')
    db.executemany('INSERT INTO EURUSD_M1 VALUES (?,?,?,?,?,?,?,?,?,?)', [('EURUSD','M1',t,1,2,.5,1.5,5,1,0) for t in [100,200,300,400]])
    db.commit()


class DashboardTests(unittest.TestCase):
    def test_max_range_preserves_full_span_and_ohlc(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.row_factory=sqlite3.Row; populate(db)
            db.execute('UPDATE EURUSD_M1 SET open=10,high=15,low=5,close=12,tick_volume=4 WHERE time=100')
            db.execute('UPDATE EURUSD_M1 SET open=12,high=20,low=8,close=18,tick_volume=6 WHERE time=200')
            db.execute('UPDATE EURUSD_M1 SET open=18,high=25,low=16,close=22,tick_volume=8 WHERE time=300')
            db.execute('UPDATE EURUSD_M1 SET open=22,high=24,low=14,close=16,tick_volume=10 WHERE time=400')
            result=app.load_bars(db,{'table':['EURUSD_M1'],'range':['MAX'],'limit':['2']})
            self.assertTrue(result['aggregated'])
            self.assertEqual(result['source_count'],4)
            self.assertEqual(result['range_start'],100)
            self.assertEqual(result['range_end'],400)
            self.assertEqual(len(result['bars']),2)
            first=result['bars'][0]
            self.assertEqual((first['open'],first['high'],first['low'],first['close'],first['tick_volume']),(10,20,5,18,10))
            self.assertEqual(result['bars'][-1]['close'],16)

    def test_range_rejects_unknown_presets(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.row_factory=sqlite3.Row; populate(db)
            with self.assertRaises(ValueError): app.load_bars(db,{'table':['EURUSD_M1'],'range':['100Y']})
            with self.assertRaises(ValueError): app.load_range(db,'EURUSD','3Y',200)

    def test_slate_range_presets_are_supported(self):
        self.assertEqual(set(app.SLATE_RANGE_FRAME),{'D5','1M','6M','YTD','1Y','5Y','MAX'})
        self.assertEqual(app.SLATE_RANGE_FRAME['D5'],'M15')

    def test_year_range_handles_leap_day(self):
        from datetime import datetime,timezone
        with closing(sqlite3.connect(':memory:')) as db:
            db.row_factory=sqlite3.Row; populate(db)
            stamp=int(datetime(2024,2,29,tzinfo=timezone.utc).timestamp())
            db.execute('UPDATE EURUSD_M1 SET time=? WHERE time=400',(stamp,))
            result=app.load_range(db,'EURUSD','1Y',200)
            self.assertEqual(result['requested_start'],int(datetime(2023,2,28,tzinfo=timezone.utc).timestamp()))

    def test_pagination_has_no_overlap(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.row_factory=sqlite3.Row; populate(db)
            recent=app.load_bars(db,{'table':['EURUSD_M1'],'limit':['2']})
            older=app.load_bars(db,{'table':['EURUSD_M1'],'limit':['2'],'before':['300']})
            self.assertEqual([b['time'] for b in recent['bars']],[300,400])
            self.assertEqual([b['time'] for b in older['bars']],[100,200])
            self.assertTrue(recent['has_older']); self.assertFalse(older['has_older'])

    def test_dates_are_inclusive(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.row_factory=sqlite3.Row; populate(db)
            result=app.load_bars(db,{'table':['EURUSD_M1'],'start':['200'],'end':['300']})
            self.assertEqual([b['time'] for b in result['bars']],[200,300])

    def test_table_injection_and_large_limits_rejected(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.row_factory=sqlite3.Row; populate(db)
            for query in [{'table':['EURUSD_M1;DROP TABLE EURUSD_M1']},{'table':['EURUSD_M1'],'limit':['1001']}]:
                with self.assertRaises(ValueError): app.load_bars(db,query)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM EURUSD_M1').fetchone()[0],4)

    def test_coverage_excludes_non_market_tables(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.row_factory=sqlite3.Row; populate(db)
            db.execute('CREATE TABLE notes (value TEXT)')
            self.assertEqual(app.table_list(db),[dict(name='EURUSD_M1',symbol='EURUSD',timeframe='M1',first=100,last=400)])

    def test_range_coverage_cache_reuses_tables_until_database_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'market.db'
            with closing(sqlite3.connect(path)) as writer: populate(writer)
            with patch.object(app,'DATABASE',path):
                app._coverage_cache.update(signature=None,tables=None)
                with closing(sqlite3.connect(path)) as db:
                    db.row_factory=sqlite3.Row
                    with patch.object(app,'table_list',wraps=app.table_list) as scan:
                        first=app.cached_table_list(db)
                        again=app.cached_table_list(db)
                        self.assertEqual(first,again)
                        self.assertEqual(scan.call_count,1)
                        db.execute('INSERT INTO EURUSD_M1 VALUES (?,?,?,?,?,?,?,?,?,?)',
                                   ('EURUSD','M1',500,1,2,.5,1.5,5,1,0))
                        db.commit()
                        refreshed=app.cached_table_list(db)
                        self.assertEqual(scan.call_count,2)
                        self.assertEqual(refreshed[0]['last'],500)

    def test_connection_cannot_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'market.db'
            with closing(sqlite3.connect(path)) as db: populate(db)
            with patch.object(app,'DATABASE',path), closing(app.connect()) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM EURUSD_M1').fetchone()[0],4)
                with self.assertRaises(sqlite3.OperationalError): db.execute('DELETE FROM EURUSD_M1')

    def test_missing_database_is_not_created(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'missing.db'
            with patch.object(app,'DATABASE',path), self.assertRaises(sqlite3.OperationalError): app.connect()
            self.assertFalse(path.exists())


class LiveDashboardTests(unittest.TestCase):
    def test_fresh_stale_and_offline_are_distinct(self):
        import sys,time
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
        import live_collector
        now=time.time()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'live.db'
            with closing(sqlite3.connect(path)) as db:
                live_collector.create_live_schema(db)
                db.execute("INSERT INTO instruments VALUES ('EURUSD','fx','Euro',5,.00001,1)")
                db.execute("INSERT INTO latest_quotes VALUES ('EURUSD',1,1.1,.1,10000,?,?,?,?)",(int(now*1000),now,now-60,1))
                db.execute('INSERT INTO collector_status(id,heartbeat,connected,quote_interval,candle_interval,cycle,last_error,candle_updated_at,worker_restarts) VALUES (1,?,?,?,?,?,?,?,0)',(now,1,2,5,1,None,now))
                db.commit()
                with patch.object(app,'LIVE_DATABASE',path):
                    self.assertEqual(app.live_snapshot('EURUSD')['quote']['status'],'stale')
                    db.execute('UPDATE latest_quotes SET changed_at=?',(now,));db.commit()
                    self.assertEqual(app.live_snapshot('EURUSD')['quote']['status'],'live')
                    db.execute('UPDATE latest_quotes SET tick_time_msc=?',(int((now-3600)*1000),));db.commit()
                    self.assertEqual(app.live_snapshot('EURUSD')['quote']['status'],'stale')
                    db.execute('UPDATE collector_status SET connected=0');db.commit()
                    self.assertEqual(app.live_snapshot('EURUSD')['quote']['status'],'offline')

    def test_missing_live_store_is_reported_without_creating_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'missing.db'
            with patch.object(app,'LIVE_DATABASE',path):
                self.assertIsNone(app.live_snapshot('EURUSD')['quote'])
            self.assertFalse(path.exists())


class ProviderApiTests(unittest.TestCase):
    def make_databases(self, directory):
        market=Path(directory)/'market.db'
        live=Path(directory)/'live.db'
        with closing(sqlite3.connect(market)) as db: populate(db)
        now=app.time.time()
        with closing(sqlite3.connect(live)) as db:
            db.executescript('''
                CREATE TABLE instruments(symbol TEXT,asset_class TEXT,description TEXT,digits INTEGER,point REAL,available INTEGER);
                CREATE TABLE latest_quotes(symbol TEXT,bid REAL,ask REAL,spread REAL,spread_points REAL,tick_time_msc INTEGER,received_at REAL,changed_at REAL,seen_change INTEGER);
                CREATE TABLE collector_status(id INTEGER,heartbeat REAL,connected INTEGER,quote_interval REAL,candle_interval REAL,cycle INTEGER,last_error TEXT,candle_updated_at REAL,worker_restarts INTEGER,cycle_duration_ms REAL,mt5_poll_ms REAL,sqlite_write_ms REAL,quote_age_max_ms REAL,poll_overruns INTEGER);
                CREATE TABLE candle_status(symbol TEXT,timeframe TEXT,current_open INTEGER,updated_at REAL,catchup_limited INTEGER,first_time INTEGER,last_time INTEGER,bar_count INTEGER,gap_count INTEGER,unavailable INTEGER,PRIMARY KEY(symbol,timeframe));
                CREATE TABLE candle_health(id INTEGER,updated_at REAL,failed_count INTEGER);
            ''')
            db.execute("INSERT INTO instruments VALUES ('EURUSD','fx','Euro / US Dollar',5,.00001,1)")
            db.execute("INSERT INTO instruments VALUES ('GBPUSD','fx','Pound Sterling / US Dollar',5,.00001,1)")
            db.execute("INSERT INTO instruments VALUES ('XAUUSD','metal','Gold / US Dollar',2,.01,1)")
            db.execute('INSERT INTO latest_quotes VALUES (?,?,?,?,?,?,?,?,?)',
                       ('EURUSD',1.1,1.1002,.0002,20,int(now*1000),now,now,1))
            db.execute('INSERT INTO collector_status VALUES (1,?,1,1,5,12,NULL,?,0,40,12,20,30,0)',(now,now))
            db.execute("INSERT INTO candle_status VALUES ('EURUSD','M1',400,?,1,100,400,4,2,0)",(now,))
            db.execute('INSERT INTO candle_health VALUES (1,?,0)',(now,))
            db.commit()
        return market,live

    def test_provider_quote_matches_normalized_consumer_shape_and_freshness(self):
        with tempfile.TemporaryDirectory() as directory:
            market,live=self.make_databases(directory)
            with patch.object(app,'DATABASE',market),patch.object(app,'LIVE_DATABASE',live):
                result=app.provider_quotes(['eurusd'])
            self.assertEqual(result['provider'],'mt5-market-gateway')
            entry=result['quotes'][0]
            self.assertEqual(entry['status'],'available')
            quote=entry['quote']
            self.assertEqual(quote['symbol'],'EURUSD')
            self.assertAlmostEqual(quote['price'],1.1001)
            self.assertEqual((quote['bid'],quote['ask'],quote['source'],quote['freshness']),
                             (1.1,1.1002,'mt5','live'))
            self.assertIn('sourceTimestamp',quote)
            self.assertGreaterEqual(quote['quoteAgeAtApiMs'],0)
            self.assertIn('brokerTimestampSkewMs',quote)

    def test_provider_status_reports_readiness_and_quote_health_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            market,live=self.make_databases(directory)
            with patch.object(app,'DATABASE',market),patch.object(app,'LIVE_DATABASE',live):
                status=app.provider_status()
            self.assertTrue(status['ready'])
            self.assertEqual(status['status'],'ok')
            self.assertTrue(status['checks']['collector_online'])
            self.assertEqual(status['quote_counts']['live'],1)
            self.assertEqual(status['quote_counts']['missing'],2)
            self.assertEqual(status['collector']['mt5_poll_ms'],12)

    def test_provider_status_marks_stale_candle_progress_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            market,live=self.make_databases(directory)
            with closing(sqlite3.connect(live)) as db:
                db.execute('UPDATE candle_health SET updated_at=?,failed_count=0 WHERE id=1',
                           (app.time.time()-app.CANDLE_WORKER_STALE_SECONDS-1,))
                db.commit()
            with patch.object(app,'DATABASE',market),patch.object(app,'LIVE_DATABASE',live):
                status=app.provider_status()
            self.assertFalse(status['checks']['candle_worker_available'])
            self.assertFalse(status['checks']['candle_worker_healthy'])
            self.assertFalse(status['candle_worker']['progress_fresh'])
            self.assertGreater(status['candle_worker']['progress_age_seconds'],
                               app.CANDLE_WORKER_STALE_SECONDS)

    def test_provider_quotes_include_explicit_results_for_missing_symbols(self):
        with tempfile.TemporaryDirectory() as directory:
            market,live=self.make_databases(directory)
            with patch.object(app,'DATABASE',market),patch.object(app,'LIVE_DATABASE',live):
                result=app.provider_quotes(['EURUSD','GBPUSD','UNKNOWN'])
            self.assertEqual([item['symbol'] for item in result['quotes']],['EURUSD','GBPUSD','UNKNOWN'])
            self.assertEqual([item['status'] for item in result['quotes']],['available','unavailable','unavailable'])
            self.assertEqual(result['quotes'][1]['reason'],'quote_not_received')
            self.assertEqual(result['quotes'][2]['reason'],'not_subscribed')

    def test_provider_instruments_can_filter_asset_class_and_search(self):
        with tempfile.TemporaryDirectory() as directory:
            _,live=self.make_databases(directory)
            with patch.object(app,'LIVE_DATABASE',live):
                fx=app.provider_instruments(asset_class='fx')
                metal=app.provider_instruments(asset_class='metal',search='gold')
                with self.assertRaises(ValueError):
                    app.provider_instruments(asset_class='crypto')
                with self.assertRaises(ValueError):
                    app.provider_instruments(search='x'*101)
            self.assertEqual([row['symbol'] for row in fx['instruments']],['EURUSD','GBPUSD'])
            self.assertIs(fx['instruments'][0]['available'],True)
            self.assertEqual([row['symbol'] for row in metal['instruments']],['XAUUSD'])

    def test_provider_history_supports_slate_intervals_and_paging(self):
        with tempfile.TemporaryDirectory() as directory:
            market,live=self.make_databases(directory)
            with patch.object(app,'DATABASE',market),patch.object(app,'LIVE_DATABASE',live):
                result=app.provider_history('EURUSD',{'interval':['1m'],'limit':['2']})
            self.assertEqual(result['timeframe'],'M1')
            self.assertEqual([bar['time'] for bar in result['bars']],[300,400])
            self.assertTrue(result['hasOlder'])
            self.assertEqual(result['nextBefore'],300)
            self.assertEqual(result['bars'][0]['volume'],5)
            self.assertEqual(result['coverage'],dict(start=100,end=400,recentBarCount=4,catchupLimited=True,gapCount=2,unavailableRefreshes=0))

    def test_provider_history_uses_interval_with_intraday_date_windows(self):
        with tempfile.TemporaryDirectory() as directory:
            market,live=self.make_databases(directory)
            with closing(sqlite3.connect(market)) as db:
                for frame in ('M5','M15','M30','H1','H4'):
                    db.execute(f'''CREATE TABLE EURUSD_{frame} (
                        symbol TEXT,timeframe TEXT,time INTEGER,open REAL,high REAL,
                        low REAL,close REAL,tick_volume INTEGER,spread INTEGER,
                        real_volume INTEGER,PRIMARY KEY(symbol,timeframe,time))''')
                    db.executemany(f'INSERT INTO EURUSD_{frame} VALUES (?,?,?,?,?,?,?,?,?,?)',
                                   [('EURUSD',frame,t,1,2,.5,1.5,5,1,0)
                                    for t in [100,200,300,400]])
                db.commit()
            requests=[
                ({'interval':['1m'],'range':['1D']},'M1'),
                ({'interval':['5m'],'range':['5D']},'M5'),
                ({'interval':['15m'],'range':['5D']},'M15'),
                ({'interval':['30m'],'range':['1M']},'M30'),
                ({'interval':['1h'],'range':['1M']},'H1'),
                ({'interval':['1h'],'range':['3M']},'H4'),
            ]
            with patch.object(app,'DATABASE',market),patch.object(app,'LIVE_DATABASE',live):
                for query,expected_frame in requests:
                    result=app.provider_history('EURUSD',query)
                    self.assertEqual(result['timeframe'],expected_frame)
                    self.assertTrue(result['bars'])

    def test_provider_range_uses_native_bars_and_rejects_invalid_queries(self):
        with tempfile.TemporaryDirectory() as directory:
            market,live=self.make_databases(directory)
            with closing(sqlite3.connect(market)) as db:
                db.execute('CREATE TABLE EURUSD_M15 (symbol TEXT,timeframe TEXT,time INTEGER,open REAL,high REAL,low REAL,close REAL,tick_volume INTEGER,spread INTEGER,real_volume INTEGER,PRIMARY KEY(symbol,timeframe,time))')
                db.executemany('INSERT INTO EURUSD_M15 VALUES (?,?,?,?,?,?,?,?,?,?)', [('EURUSD','M15',t,1,2,.5,1.5,5,1,0) for t in [100,200,300,400]])
                db.commit()
            with patch.object(app,'DATABASE',market),patch.object(app,'LIVE_DATABASE',live):
                result=app.provider_history('EURUSD',{'range':['D5'],'limit':['10']})
                with self.assertRaises(ValueError):
                    app.provider_history('EURUSD',{'interval':['2y'],'limit':['10']})
                with self.assertRaises(ValueError):
                    app.provider_history('EURUSD',{'range':['3Y'],'limit':['10']})
            self.assertEqual(result['timeframe'],'M15')
            self.assertEqual(len(result['bars']),4)

    def test_only_supported_native_intervals_are_accepted(self):
        expected={'M1','M5','M15','M30','H1','H4','D1','W1','MN1'}
        self.assertEqual(set(app.FRAME_SECONDS)|{'MN1'},expected)
        self.assertNotIn('2m',app.FRAME_ALIASES)


class DashboardAuthTests(unittest.TestCase):
    def test_basic_auth_rejects_and_accepts_credentials(self):
        import base64
        from io import BytesIO
        from unittest.mock import patch
        def handler(auth):
            request=app.Handler.__new__(app.Handler)
            request.path='/health'
            request.headers={'Authorization':auth} if auth else {}
            request.wfile=BytesIO()
            request.request_version='HTTP/1.1'
            request.command='GET'
            request.responses=[]
            request.send_response=lambda status,*args:request.responses.append(status)
            request.send_header=lambda *args:None
            request.end_headers=lambda:None
            request.log_request=lambda *args:None
            return request
        expected='Basic '+base64.b64encode(b'user:pass').decode()
        with patch.object(app,'DASHBOARD_USER','user'),patch.object(app,'DASHBOARD_PASSWORD','pass'),patch.object(app.Path,'is_file',return_value=False):
            denied=handler('')
            denied.do_GET()
            self.assertEqual(denied.responses,[401])
            allowed=handler(expected)
            allowed.do_GET()
            self.assertEqual(allowed.responses,[200])
