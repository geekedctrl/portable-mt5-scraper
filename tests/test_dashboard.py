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
                db.execute('INSERT INTO collector_status VALUES (1,?,?,?,?,?,?,?,0)',(now,1,2,5,1,None,now))
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
