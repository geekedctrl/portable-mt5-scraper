"""Wait for the isolated MT5 terminal, then run the batch scraper."""
import os
import runpy
import sys
import time
import MetaTrader5 as mt5

terminal = r'Z:\state\terminal\terminal64.exe'
mode = os.environ.get('MT5_MODE', 'desktop')
if mode not in ('scrape', 'check', 'stack', 'live'):
    raise SystemExit('MT5_MODE must be desktop, check, scrape, stack, or live')
credentials = {name: os.environ.get('MT5_' + name.upper(), '')
               for name in ('login', 'password', 'server')}
auth = {}
if any(credentials.values()):
    if not all(credentials.values()):
        raise SystemExit('Set MT5_LOGIN, MT5_PASSWORD, and MT5_SERVER together.')
    try:
        auth['login'] = int(credentials['login'])
        if auth['login'] <= 0:
            raise ValueError
    except ValueError:
        raise SystemExit('MT5_LOGIN must be a positive account number.')
    auth.update(password=credentials['password'], server=credentials['server'])

deadline = time.monotonic() + int(os.environ.get('MT5_WAIT_SECONDS', '600'))
while time.monotonic() < deadline:
    if mt5.initialize(terminal, portable=True, timeout=10000, **auth):
        info = mt5.terminal_info()
        if info and info.connected:
            requested_limit = int(os.environ.get('MT5_MAX_BARS', '0'))
            if info.maxbars < requested_limit:
                mt5.shutdown()
                raise SystemExit('MT5 chart limit is below MT5_MAX_BARS; history download stopped.')
            print(f'MT5 connected; maxbars={info.maxbars}', flush=True)
            break
    mt5.shutdown()
    print('Waiting for MT5 login/connection...', flush=True)
    time.sleep(5)
else:
    raise SystemExit('MT5 connection timed out. Open the browser desktop and log in.')
if mode == 'check':
    mt5.shutdown()
    raise SystemExit(0)
os.environ['MT5_TERMINAL_PATH'] = terminal
if mode == 'live':
    runpy.run_path(r'Z:\app\live_collector.py', run_name='__main__')
    raise SystemExit(0)
sys.argv = ['scrape_all.py', '--db', r'Z:\data\market.db', *sys.argv[1:]]
runpy.run_path(r'Z:\app\scrape_all.py', run_name='__main__')
