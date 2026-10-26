"""Live collector correctness, bounded catch-up, and candle rollover."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import live_collector as app


def instrument(name,group):
    return NS(name=name,path=group+'\\'+name,description=name,digits=2,point=.01)


def bar(t,close=1.5):
    return dict(time=t,open=1,high=2,low=.5,close=close,tick_volume=4,spread=1,real_volume=0)


class LiveCollectorTests(unittest.TestCase):
    def test_only_chart_backing_timeframes_are_enabled_by_default(self):
        expected={'M1','M5','M15','M30','H1','H4','D1','W1','MN1'}
        self.assertEqual(set(app.FRAMES),expected)
        self.assertEqual(set(app.TIMEFRAMES),expected)

    def test_monthly_catchup_uses_calendar_months(self):
        from datetime import datetime,timezone
        first=datetime(2024,1,1,tzinfo=timezone.utc).timestamp()
        last=datetime(2024,3,1,tzinfo=timezone.utc).timestamp()
        self.assertEqual(app.catchup_count(first,last,'MN1',200,1000),(4,False))

    def test_slow_timeframes_have_bounded_refresh_intervals(self):
        self.assertEqual(app.refresh_interval('M1'),5)
        self.assertEqual(app.refresh_interval('H1'),30)
        self.assertEqual(app.refresh_interval('MN1'),60)

    def test_not_due_candles_do_not_request_mt5_history(self):
        import time
        selected=[(instrument('EURUSD','Forex'),'fx')]
        due={('EURUSD',frame):time.monotonic()+60 for frame in app.FRAMES}
        last={('EURUSD',frame):120 for frame in app.FRAMES}
        with closing(sqlite3.connect(':memory:')) as market, closing(sqlite3.connect(':memory:')) as live, patch.object(app.mt5,'symbol_info_tick',return_value=None), patch.object(app.mt5,'copy_rates_from_pos') as copy:
            app.create_live_schema(live)
            _,errors=app.refresh_candles(market,live,selected,last,200,1000,due)
            self.assertEqual(errors,0)
            copy.assert_not_called()

    def test_seven_default_fx_and_seven_default_metals(self):
        symbols=[instrument(n,'Forex') for n in app.FX_DEFAULTS]+[instrument(n,'Metals') for n in app.METAL_DEFAULTS]
        chosen=app.choose_symbols(symbols)
        self.assertEqual(sum(c=='fx' for _,c in chosen),7)
        self.assertEqual(sum(c=='metal' for _,c in chosen),7)
        self.assertEqual([s.name for s,_ in chosen],app.FX_DEFAULTS+app.METAL_DEFAULTS)

    def test_unknown_subscription_rejected(self):
        with self.assertRaises(ValueError): app.choose_symbols([instrument('EURUSD','Forex')],'NOTREAL')

    def test_new_series_seed_progress_is_persisted_and_completed(self):
        selected=[(instrument('EURUSD','Forex'),'fx')]
        progress={('EURUSD','M1'):2}
        last={('EURUSD','M1'):None}
        with closing(sqlite3.connect(':memory:')) as market, closing(sqlite3.connect(':memory:')) as live, patch.object(app,'FRAMES',['M1']), patch.object(app.mt5,'symbol_info_tick',return_value=None), patch.object(app.mt5,'copy_rates_from_pos',side_effect=[[bar(60),bar(120)],[bar(t*60) for t in range(1,9)]]) as copy, patch.object(app.time,'sleep'):
            app.create_schema(market,'EURUSD_M1')
            app.create_live_schema(live)
            app.refresh_candles(market,live,selected,last,8,1000,bootstrap=progress)
            self.assertEqual(copy.call_args.args[-1],2)
            self.assertEqual(live.execute('SELECT next_count FROM seed_progress').fetchone()[0],8)
            app.refresh_candles(market,live,selected,last,8,1000,bootstrap=progress)
            self.assertEqual(copy.call_args.args[-1],8)
            self.assertEqual(market.execute('SELECT COUNT(*) FROM EURUSD_M1').fetchone()[0],8)
            self.assertFalse(progress)
            self.assertEqual(live.execute('SELECT COUNT(*) FROM seed_progress').fetchone()[0],0)

    def test_spread_and_unchanged_tick_freshness(self):
        tick=NS(bid=1.2,ask=1.2002,time=100,time_msc=100001)
        first=app.quote_values('EURUSD',tick,.00001,None,100)
        self.assertAlmostEqual(first[4],20)
        previous=dict(tick_time_msc=100001,changed_at=100,seen_change=0)
        unchanged=app.quote_values('EURUSD',tick,.00001,previous,150)
        self.assertEqual(unchanged[7:],(100,0))
        tick.time_msc=100002
        changed=app.quote_values('EURUSD',tick,.00001,previous,151)
        self.assertEqual(changed[7:],(151,1))

    def test_quote_upserts_are_batched_and_replace_latest_values(self):
        with closing(sqlite3.connect(':memory:')) as db:
            app.create_live_schema(db)
            first=app.quote_values('EURUSD',NS(bid=1.1,ask=1.2,time=100,time_msc=100001),.01,None,100)
            second=app.quote_values('GBPUSD',NS(bid=1.3,ask=1.4,time=100,time_msc=100001),.01,None,100)
            app.write_quotes(db,[first,second,None])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM latest_quotes').fetchone()[0],2)
            updated=app.quote_values('EURUSD',NS(bid=1.11,ask=1.21,time=101,time_msc=101001),.01,None,101)
            app.write_quotes(db,[updated])
            self.assertEqual(db.execute("SELECT bid FROM latest_quotes WHERE symbol='EURUSD'").fetchone()[0],1.11)

    def test_configured_timestamp_offset_applies_to_quotes_and_bars(self):
        tick=NS(bid=1.2,ask=1.2002,time=3700,time_msc=3700001)
        values=app.quote_values('EURUSD',tick,.00001,None,100,time_offset=3600)
        self.assertEqual(values[5],100001)
        with closing(sqlite3.connect(':memory:')) as db:
            app.create_schema(db,'EURUSD_M1')
            app.write_bars(db,'EURUSD','M1',[bar(7200)],time_offset=3600)
            self.assertEqual(db.execute('SELECT time FROM EURUSD_M1').fetchone()[0],3600)

    def test_gap_coverage_uses_series_index_and_calendar_months(self):
        with closing(sqlite3.connect(':memory:')) as db:
            app.create_schema(db,'EURUSD_M1')
            app.write_bars(db,'EURUSD','M1',[bar(60),bar(120),bar(600)])
            self.assertEqual(app.history_coverage(db,'EURUSD','M1'),(60,600,3,1))
        with closing(sqlite3.connect(':memory:')) as db:
            app.create_schema(db,'EURUSD_MN1')
            from datetime import datetime,timezone
            stamps=[datetime(2024,m,1,tzinfo=timezone.utc).timestamp() for m in (1,2,5)]
            app.write_bars(db,'EURUSD','MN1',[bar(int(t)) for t in stamps])
            self.assertEqual(app.history_coverage(db,'EURUSD','MN1')[3],1)

    def test_worker_backoff_is_bounded(self):
        self.assertEqual([app.backoff_seconds(n) for n in (1,2,3,4,5,20)],[2,4,8,16,30,30])

    def test_worker_watchdog_uses_start_time_when_database_heartbeat_is_old(self):
        self.assertFalse(app.worker_stalled(10,100,200,180))
        self.assertTrue(app.worker_stalled(10,100,281,180))
        self.assertFalse(app.worker_stalled(250,100,300,180))

    def test_candle_progress_refresh_preserves_last_completed_error_count(self):
        with closing(sqlite3.connect(':memory:')) as db:
            app.create_live_schema(db)
            db.execute('INSERT INTO candle_health VALUES (1,50,1)')
            with patch.object(app.time,'time',return_value=100):
                app.record_candle_progress(db)
            self.assertEqual(db.execute('SELECT updated_at,failed_count FROM candle_health').fetchone(),(100,1))

    def test_invalid_quotes_are_not_written(self):
        self.assertIsNone(app.quote_values('EURUSD',None,.01,None,1))
        self.assertIsNone(app.quote_values('EURUSD',NS(bid=2,ask=1),.01,None,1))

    def test_candle_rollover_updates_previous_candle_without_duplicates(self):
        with closing(sqlite3.connect(':memory:')) as db:
            app.create_schema(db,'EURUSD_M1')
            app.write_bars(db,'EURUSD','M1',[bar(60),bar(120)])
            app.write_bars(db,'EURUSD','M1',[bar(120,1.8),bar(180)])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM EURUSD_M1').fetchone()[0],3)
            self.assertEqual(db.execute('SELECT close FROM EURUSD_M1 WHERE time=120').fetchone()[0],1.8)

    def test_catchup_is_bounded(self):
        self.assertEqual(app.catchup_count(None,10000,'M1',200,5000),(200,False))
        count,limited=app.catchup_count(0,1000000,'M1',200,5000)
        self.assertEqual(count,5000); self.assertTrue(limited)

    def test_one_real_database_cycle(self):
        with tempfile.TemporaryDirectory() as directory:
            symbols=[instrument('EURUSD','Forex'),instrument('XAUUSD','Metals')]
            tick=NS(bid=1,ask=1.01,time=100,time_msc=100001)
            env=dict(MARKET_DB=str(Path(directory)/'market.db'),LIVE_DB=str(Path(directory)/'live.db'),LIVE_MAX_BARS='20',LIVE_SEED_BARS='2',LIVE_SYMBOLS='',LIVE_POLL_SECONDS='0.5')
            with patch.dict(os.environ,env), patch.object(app.mt5,'symbols_get',return_value=symbols), patch.object(app.mt5,'symbol_select',return_value=True), patch.object(app.mt5,'terminal_info',return_value=NS(connected=True)), patch.object(app.mt5,'symbol_info_tick',return_value=tick), patch.object(app.mt5,'copy_rates_from_pos',return_value=[bar(60),bar(120)]), patch.object(app.mt5,'shutdown'):
                app.run(max_cycles=1)
            with closing(sqlite3.connect(env['LIVE_DB'])) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM latest_quotes').fetchone()[0],2)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM candle_status').fetchone()[0],18)
                self.assertEqual(db.execute('SELECT connected FROM collector_status').fetchone()[0],0)
                metrics=db.execute('SELECT cycle_duration_ms,mt5_poll_ms,sqlite_write_ms,poll_overruns FROM collector_status').fetchone()
                self.assertTrue(all(value is not None for value in metrics[:3]))
                self.assertGreaterEqual(metrics[3],0)
                self.assertEqual(db.execute('SELECT quote_interval FROM collector_status').fetchone()[0],.5)
