"""Container startup checks without starting a real terminal or scrape."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import MetaTrader5 as mt5

SOURCE = (Path(__file__).resolve().parents[1] / 'docker/container_runner.py').read_text()


class ContainerStartupTests(unittest.TestCase):
    def test_live_mode_runs_collector_instead_of_history_job(self):
        with patch.dict(os.environ, {'MT5_MODE': 'live'}), patch.object(mt5, 'initialize', return_value=True), patch.object(mt5, 'terminal_info', return_value=SimpleNamespace(connected=True, maxbars=5000)), patch.object(mt5, 'shutdown'), patch('runpy.run_path') as run:
            with self.assertRaises(SystemExit) as result:
                exec(compile(SOURCE, 'container_runner.py', 'exec'), {})
            self.assertEqual(result.exception.code, 0)
            run.assert_called_once_with(r'Z:\app\live_collector.py', run_name='__main__')

    def test_check_connects_without_scraping(self):
        with patch.dict(os.environ, {'MT5_MODE': 'check'}), patch.object(mt5, 'initialize', return_value=True) as initialize, patch.object(mt5, 'terminal_info', return_value=SimpleNamespace(connected=True, maxbars=100000000)), patch.object(mt5, 'shutdown'), patch('runpy.run_path') as run:
            with self.assertRaises(SystemExit) as result:
                exec(compile(SOURCE, 'container_runner.py', 'exec'), {})
            self.assertEqual(result.exception.code, 0)
            initialize.assert_called_once_with(r'Z:\state\terminal\terminal64.exe', portable=True, timeout=10000)
            run.assert_not_called()

    def test_scrape_uses_persistent_database_and_explicit_reset(self):
        original = sys.argv
        try:
            sys.argv = ['container_runner.py', '--reset']
            with patch.dict(os.environ, {'MT5_MODE': 'scrape'}), patch.object(mt5, 'initialize', return_value=True), patch.object(mt5, 'terminal_info', return_value=SimpleNamespace(connected=True, maxbars=100000000)), patch.object(mt5, 'shutdown'), patch('runpy.run_path') as run:
                exec(compile(SOURCE, 'container_runner.py', 'exec'), {})
                self.assertEqual(sys.argv, ['scrape_all.py', '--db', r'Z:\data\market.db', '--reset'])
                run.assert_called_once()
        finally:
            sys.argv = original

    def test_credentials_are_passed_to_mt5(self):
        with patch.dict(os.environ, {'MT5_MODE': 'check', 'MT5_LOGIN': '12345', 'MT5_PASSWORD': 'test-only-$#', 'MT5_SERVER': 'Test-Demo'}), patch.object(mt5, 'initialize', return_value=True) as initialize, patch.object(mt5, 'terminal_info', return_value=SimpleNamespace(connected=True, maxbars=100000000)), patch.object(mt5, 'shutdown'):
            with self.assertRaises(SystemExit) as result:
                exec(compile(SOURCE, 'container_runner.py', 'exec'), {})
            self.assertEqual(result.exception.code, 0)
            self.assertEqual(initialize.call_args.kwargs['login'], 12345)
            self.assertEqual(initialize.call_args.kwargs['password'], 'test-only-$#')
            self.assertEqual(initialize.call_args.kwargs['server'], 'Test-Demo')

    def test_partial_credentials_fail_before_connecting(self):
        with patch.dict(os.environ, {'MT5_MODE': 'check', 'MT5_LOGIN': '12345', 'MT5_PASSWORD': '', 'MT5_SERVER': ''}), patch.object(mt5, 'initialize') as initialize:
            with self.assertRaisesRegex(SystemExit, 'together'):
                exec(compile(SOURCE, 'container_runner.py', 'exec'), {})
            initialize.assert_not_called()

    def test_timeout_does_not_scrape(self):
        with patch.dict(os.environ, {'MT5_MODE': 'scrape', 'MT5_WAIT_SECONDS': '0'}), patch('runpy.run_path') as run:
            with self.assertRaisesRegex(SystemExit, 'timed out'):
                exec(compile(SOURCE, 'container_runner.py', 'exec'), {})
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
