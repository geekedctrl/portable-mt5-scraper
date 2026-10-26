import sqlite3
from contextlib import closing
from types import SimpleNamespace
from datetime import datetime, timezone
import unittest
from unittest.mock import patch
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import scrape_all as app


def bar(timestamp):
    return dict(time=timestamp, open=2, high=3, low=1, close=2,
                tick_volume=4, spread=0, real_volume=0)


class HistoryTests(unittest.TestCase):
    def test_transient_forward_page_is_retried(self):
        with patch.object(app.mt5, 'copy_rates_from', side_effect=[[bar(180)], [bar(60)]]), patch.object(app.mt5, 'last_error', return_value=(1, 'Success')), patch.object(app.time, 'sleep'):
            rates = app.fetch('XAUUSD', 'M1', datetime.fromtimestamp(119, timezone.utc), 2)
            self.assertEqual(int(rates[0]['time']), 60)

    def test_repeated_first_candle_is_confirmed_as_history_boundary(self):
        with closing(sqlite3.connect(':memory:')) as db, patch.object(app, 'fetch', side_effect=[[bar(120), bar(180)], [bar(60)], [bar(60)]]), patch.object(app.mt5, 'terminal_info', return_value=SimpleNamespace(connected=True)), patch.object(app.mt5, 'copy_rates_from', return_value=[bar(60)]) as probe, patch.object(app.mt5, 'last_error', return_value=(1, 'Success')), patch.object(app.time, 'sleep'):
            result = app.download(db, 'XAUUSD', 'M1', 2)
            self.assertEqual(result['rows'], 3)
            self.assertEqual(result['stop_reason'], 'confirmed_first_candle')
            self.assertEqual(probe.call_count, 3)
            self.assertEqual(probe.call_args.args[2:], (59, 1))

    def test_arbitrary_repeated_page_is_still_an_error(self):
        with closing(sqlite3.connect(':memory:')) as db, patch.object(app, 'fetch', side_effect=[[bar(120), bar(180)], [bar(120), bar(180)]]):
            with self.assertRaisesRegex(RuntimeError, 'did not move backwards'):
                app.download(db, 'XAUUSD', 'M1', 2)

    def test_disconnection_at_boundary_is_not_success(self):
        with patch.object(app.mt5, 'terminal_info', return_value=SimpleNamespace(connected=False)):
            with self.assertRaisesRegex(RuntimeError, 'disconnected'):
                app.history_start_confirmed('XAUUSD', 'M1', 60)

    def test_earlier_data_in_probe_is_not_treated_as_boundary(self):
        with patch.object(app.mt5, 'terminal_info', return_value=SimpleNamespace(connected=True)), patch.object(app.mt5, 'copy_rates_from', return_value=[bar(30)]), patch.object(app.mt5, 'last_error', return_value=(1, 'Success')):
            self.assertFalse(app.history_start_confirmed('XAUUSD', 'M1', 60))

    def test_paging_and_idempotent_storage(self):
        with closing(sqlite3.connect(':memory:')) as db:
            for _ in range(2):
                with patch.object(app, 'fetch', side_effect=[[bar(120), bar(180)], [bar(60)], []]) as fetch:
                    result = app.download(db, 'XAUUSD', 'M1', 2)
                    self.assertEqual(result['rows'], 3)
                    self.assertEqual(int(fetch.call_args_list[1].args[2].timestamp()), 119)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM XAUUSD_M1').fetchone()[0], 3)

    def test_smoke_limit_stops_without_requesting_older_history(self):
        with closing(sqlite3.connect(':memory:')) as db, patch.object(app, 'fetch', return_value=[bar(120), bar(180)]) as fetch:
            result = app.download(db, 'XAUUSD', 'M1', 50000, max_bars=2)
            self.assertEqual(result['rows'], 2)
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(fetch.call_args.args[3], 2)

    def test_errors_are_not_end_of_history(self):
        with patch.object(app.mt5, 'copy_rates_from', return_value=None), patch.object(app.mt5, 'last_error', return_value=(-10004, 'Disconnected')), patch.object(app.time, 'sleep'):
            with self.assertRaises(RuntimeError):
                app.fetch('XAUUSD', 'M1', None, 2)

    def test_empty_table_fails(self):
        with closing(sqlite3.connect(':memory:')) as db, patch.object(app, 'fetch', return_value=[]):
            with self.assertRaises(RuntimeError):
                app.download(db, 'XAUUSD', 'M1', 2)

    def test_invalid_table_name(self):
        with self.assertRaises(ValueError):
            app.table_name('XAUUSD;DROP', 'M1')


if __name__ == '__main__':
    unittest.main()
