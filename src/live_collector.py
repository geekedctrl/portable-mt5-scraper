"""Bounded-memory live quotes and candle updates for broker-listed instruments."""
from contextlib import closing
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import sqlite3
import signal
import subprocess
import sys
import time

import MetaTrader5 as mt5
from xauusd_sqlite import TIMEFRAMES, create_schema, table_name

FX_DEFAULTS = ['EURUSD','GBPUSD','USDJPY','USDCHF','USDCAD','AUDUSD','NZDUSD',
               'EURGBP','EURJPY','GBPJPY','AUDJPY','EURCHF','EURAUD','EURCAD',
               'EURNZD','GBPCHF','GBPAUD','GBPCAD','GBPNZD','AUDCAD']
FRAMES = list(TIMEFRAMES)
SECONDS = {**{f'M{n}':n*60 for n in (1,2,3,4,5,6,10,12,15,20,30)},
           **{f'H{n}':n*3600 for n in (1,2,3,4,6,8,12)},'D1':86400,'W1':604800}


def broker_time_offset_seconds():
    """Configured seconds to subtract from broker timestamps when persisting."""
    return int(os.environ.get('MT5_TIME_OFFSET_SECONDS','0'))


def refresh_interval(frame, base=5):
    # Longer candles need fewer snapshots; quote polling stays independent.
    return min(60,max(base,SECONDS.get(frame,2592000)/120))


def choose_symbols(symbols, override=''):
    groups = {'fx': [], 'metal': []}
    for symbol in symbols:
        group = symbol.path.replace('/', '\\').split('\\')[0].lower()
        if group in ('forex','metals') and symbol.name.isalnum():
            groups['fx' if group == 'forex' else 'metal'].append(symbol)
    available = {s.name:s for items in groups.values() for s in items}
    if override:
        names = list(dict.fromkeys(s.strip() for s in override.split(',') if s.strip()))
        missing = [s for s in names if s not in available]
        if missing:
            raise ValueError('Unsupported LIVE_SYMBOLS: ' + ', '.join(missing))
    else:
        fx = [s for s in FX_DEFAULTS if s in {x.name for x in groups['fx']}]
        fx += [s.name for s in sorted(groups['fx'],key=lambda s:s.name) if s.name not in fx]
        names = fx[:20] + [s.name for s in groups['metal'][:20]]
    return [(available[name], 'fx' if available[name] in groups['fx'] else 'metal') for name in names]


def create_live_schema(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS instruments (
            symbol TEXT PRIMARY KEY, asset_class TEXT NOT NULL, description TEXT NOT NULL,
            digits INTEGER NOT NULL, point REAL NOT NULL, available INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS latest_quotes (
            symbol TEXT PRIMARY KEY, bid REAL NOT NULL, ask REAL NOT NULL,
            spread REAL NOT NULL, spread_points REAL NOT NULL, tick_time_msc INTEGER NOT NULL,
            received_at REAL NOT NULL, changed_at REAL NOT NULL, seen_change INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS collector_status (
            id INTEGER PRIMARY KEY CHECK(id=1), heartbeat REAL NOT NULL, connected INTEGER NOT NULL,
            quote_interval REAL NOT NULL, candle_interval REAL NOT NULL, cycle INTEGER NOT NULL,
            last_error TEXT, candle_updated_at REAL, worker_restarts INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS candle_status (
            symbol TEXT NOT NULL, timeframe TEXT NOT NULL, current_open INTEGER NOT NULL,
            updated_at REAL NOT NULL, catchup_limited INTEGER NOT NULL,
            first_time INTEGER, last_time INTEGER, bar_count INTEGER NOT NULL DEFAULT 0,
            gap_count INTEGER, unavailable INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(symbol,timeframe));
    ''')
    db.execute('CREATE TABLE IF NOT EXISTS candle_health (id INTEGER PRIMARY KEY, updated_at REAL, failed_count INTEGER)')
    db.execute('CREATE TABLE IF NOT EXISTS seed_progress (symbol TEXT,timeframe TEXT,next_count INTEGER,PRIMARY KEY(symbol,timeframe))')
    columns={row[1] for row in db.execute('PRAGMA table_info(candle_status)')}
    for name, kind in (('first_time','INTEGER'),('last_time','INTEGER'),('bar_count','INTEGER NOT NULL DEFAULT 0'),('gap_count','INTEGER'),('unavailable','INTEGER NOT NULL DEFAULT 0')):
        if name not in columns:
            db.execute(f'ALTER TABLE candle_status ADD COLUMN {name} {kind}')
    status_columns={row[1] for row in db.execute('PRAGMA table_info(collector_status)')}
    if 'worker_restarts' not in status_columns:
        db.execute('ALTER TABLE collector_status ADD COLUMN worker_restarts INTEGER NOT NULL DEFAULT 0')
    db.commit()


def quote_values(symbol, tick, point, previous, now, time_offset=0):
    if tick is None or not all(math.isfinite(v) and v>0 for v in (tick.bid,tick.ask)) or tick.ask<tick.bid:
        return None
    stamp = int(getattr(tick,'time_msc',0) or tick.time*1000) - int(time_offset)*1000
    if stamp <= 0:
        return None
    changed = previous is not None and previous['tick_time_msc'] != stamp
    changed_at = now if changed or previous is None else previous['changed_at']
    seen_change = int(changed or (previous is not None and previous['seen_change']))
    spread = float(tick.ask-tick.bid)
    return (symbol,float(tick.bid),float(tick.ask),spread,
            round(spread/point,6) if point>0 else 0.0,stamp,now,changed_at,seen_change)


def write_quote(db, values):
    if values is not None:
        db.execute('''INSERT INTO latest_quotes VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol) DO UPDATE SET bid=excluded.bid,ask=excluded.ask,
            spread=excluded.spread,spread_points=excluded.spread_points,
            tick_time_msc=excluded.tick_time_msc,received_at=excluded.received_at,
            changed_at=excluded.changed_at,seen_change=excluded.seen_change''',values)


def write_bars(db, symbol, frame, rates, time_offset=0):
    table = table_name(symbol,frame)
    rows = [(symbol,frame,int(r['time'])-int(time_offset),float(r['open']),float(r['high']),
             float(r['low']),float(r['close']),int(r['tick_volume']),int(r['spread']),
             int(r['real_volume'])) for r in rates]
    if rows:
        db.executemany(f'INSERT OR REPLACE INTO "{table}" VALUES (?,?,?,?,?,?,?,?,?,?)', rows)
    return max((row[2] for row in rows),default=None)


def history_coverage(db, symbol, frame):
    """Return bounds and recent-window gaps without scanning full history."""
    table = table_name(symbol, frame)
    first = db.execute(f'SELECT time FROM "{table}" WHERE symbol=? AND timeframe=? ORDER BY time LIMIT 1',
                       (symbol,frame)).fetchone()
    recent = db.execute(f'''SELECT time FROM "{table}" WHERE symbol=? AND timeframe=?
        ORDER BY time DESC LIMIT 10001''',(symbol,frame)).fetchall()
    if not recent:
        return None,None,0,None
    last=recent[0][0]
    count=len(recent)
    recent.reverse()
    seconds = SECONDS.get(frame)
    gaps = None
    if seconds:
        gaps=sum(1 for previous,current in zip(recent,recent[1:]) if current[0]-previous[0]>seconds*1.5)
    elif frame=='MN1':
        from datetime import datetime,timezone
        previous=None;gaps=0
        for (stamp,) in recent:
            current=datetime.fromtimestamp(stamp,timezone.utc)
            if previous is not None and (current.year-previous.year)*12+current.month-previous.month>1:
                gaps+=1
            previous=current
    return first[0], last, count, gaps


def catchup_count(last, now, frame, seed, cap):
    if last is None:
        requested=seed
    elif frame=='MN1':
        start=datetime.fromtimestamp(last,timezone.utc)
        end=datetime.fromtimestamp(now,timezone.utc)
        requested=max(2,(end.year-start.year)*12+end.month-start.month+2)
    else:
        requested=max(2,math.ceil(max(0,now-last)/SECONDS[frame])+2)
    return min(cap,requested), requested>cap


def reconnect():
    mt5.shutdown()
    options=dict(portable=True,timeout=10000)
    if os.environ.get('MT5_LOGIN'):
        options.update(login=int(os.environ['MT5_LOGIN']),password=os.environ['MT5_PASSWORD'],server=os.environ['MT5_SERVER'])
    return mt5.initialize(os.environ.get('MT5_TERMINAL_PATH',r'Z:\state\terminal\terminal64.exe'),**options)


def refresh_candles(market, live, selected, last_bars, seed, cap, due=None, interval=5, bootstrap=None):
    bar_errors=0
    time_offset=broker_time_offset_seconds()
    for instrument,_ in selected:
        pending=[]
        tick=mt5.symbol_info_tick(instrument.name)
        reference=max(time.time(),(getattr(tick,'time',0)-broker_time_offset_seconds()) if tick else 0)
        for frame in FRAMES:
            key=(instrument.name,frame)
            if due is not None and time.monotonic()<due.get(key,0):
                continue
            count,limited=catchup_count(last_bars[key],reference,frame,seed,cap)
            depth=bootstrap.get(key) if bootstrap is not None else None
            if depth is not None:
                count=min(cap,seed,depth)
                limited=False
            rates=mt5.copy_rates_from_pos(instrument.name,TIMEFRAMES[frame],0,count)
            # Yield between history requests so MT5 can service live quote IPC
            # while hundreds of newly enabled series are being synchronized.
            time.sleep(.05)
            if rates is None or not len(rates):
                bar_errors+=1
                continue
            pending.append((frame,rates,limited,depth))
        # Batch each symbol's writes; never hold a write lock while waiting for MT5.
        statuses=[]
        with market:
            for frame,rates,limited,depth in pending:
                latest=write_bars(market,instrument.name,frame,rates,time_offset)
                first,last,count,gaps=history_coverage(market,instrument.name,frame)
                statuses.append((instrument.name,frame,latest,time.time(),int(limited),first,last,count,gaps))
        for name,frame,latest,_,_,_,_,_,_ in statuses:
            last_bars[(name,frame)]=latest
            if due is not None:
                due[(name,frame)]=time.monotonic()+refresh_interval(frame,interval)
        with live:
            live.executemany('''INSERT INTO candle_status(
                symbol,timeframe,current_open,updated_at,catchup_limited,first_time,last_time,bar_count,gap_count,unavailable
            ) VALUES (?,?,?,?,?,?,?,?,?,0)
                ON CONFLICT(symbol,timeframe) DO UPDATE SET
                current_open=excluded.current_open, updated_at=excluded.updated_at,
                catchup_limited=excluded.catchup_limited,first_time=excluded.first_time,
                last_time=excluded.last_time,bar_count=excluded.bar_count,gap_count=excluded.gap_count,unavailable=0''',statuses)
            failed=[(instrument.name,frame) for frame in FRAMES
                    if (due is None or due.get((instrument.name,frame),0)<=time.monotonic())
                    and not any(item[0]==frame for item in pending)]
            live.executemany('UPDATE candle_status SET unavailable=unavailable+1 WHERE symbol=? AND timeframe=?',failed)
            for frame,rates,_,depth in pending:
                if depth is None:
                    continue
                key=(instrument.name,frame)
                if depth>=min(cap,seed) or len(rates)<min(depth,cap,seed):
                    bootstrap.pop(key,None)
                    live.execute('DELETE FROM seed_progress WHERE symbol=? AND timeframe=?',key)
                else:
                    next_count=min(cap,seed,depth*4)
                    bootstrap[key]=next_count
                    live.execute('INSERT OR REPLACE INTO seed_progress VALUES (?,?,?)',(*key,next_count))
    updated=time.time()
    with live:
        live.execute('INSERT OR REPLACE INTO candle_health VALUES (1,?,?)',(updated,bar_errors))
        live.execute('UPDATE collector_status SET candle_updated_at=? WHERE id=1',(updated,))
    return updated,bar_errors


def run_candle_worker():
    if not reconnect():
        raise RuntimeError('Candle worker could not connect to MT5')
    selected=choose_symbols(mt5.symbols_get() or [],os.environ.get('LIVE_SYMBOLS',''))
    cap=max(2,int(os.environ.get('LIVE_MAX_BARS','1000')))
    seed=min(cap,max(2,int(os.environ.get('LIVE_SEED_BARS','200'))))
    interval=max(2,float(os.environ.get('LIVE_CANDLE_SECONDS','5')))
    with closing(sqlite3.connect(os.environ.get('LIVE_DB',r'Z:\data\live.db'),timeout=5)) as live, closing(sqlite3.connect(os.environ.get('MARKET_DB',r'Z:\data\market.db'),timeout=5)) as market:
        last_bars={}
        for instrument,_ in selected:
            mt5.symbol_select(instrument.name,True)
            for frame in FRAMES:
                table=table_name(instrument.name,frame)
                row=market.execute(f'SELECT time FROM "{table}" WHERE symbol=? AND timeframe=? ORDER BY time DESC LIMIT 1',(instrument.name,frame)).fetchone()
                last_bars[(instrument.name,frame)]=row[0] if row else None
                first,last,count,gaps=history_coverage(market,instrument.name,frame)
                if count:
                    with live:
                        live.execute('''INSERT INTO candle_status(
                            symbol,timeframe,current_open,updated_at,catchup_limited,first_time,last_time,bar_count,gap_count,unavailable
                        ) VALUES (?,?,?,?,0,?,?,?, ?,0)
                        ON CONFLICT(symbol,timeframe) DO UPDATE SET
                            first_time=excluded.first_time,last_time=excluded.last_time,
                            bar_count=excluded.bar_count,gap_count=excluded.gap_count''',
                                     (instrument.name,frame,last,time.time(),first,last,count,gaps))
        bootstrap={(r[0],r[1]):r[2] for r in live.execute('SELECT symbol,timeframe,next_count FROM seed_progress')}
        passes=0;due={}
        while True:
            info=mt5.terminal_info()
            if not info or not info.connected:
                if not reconnect():
                    time.sleep(2);continue
            started=time.monotonic()
            _,errors=refresh_candles(market,live,selected,last_bars,seed,cap,due,interval,bootstrap)
            passes+=1
            if passes==1 or passes%12==0:
                print(f'Live candles pass {passes}: scheduled refresh; {errors} unavailable feeds',flush=True)
            time.sleep(max(.1,interval-(time.monotonic()-started)))


def stop_process(process, timeout=10):
    """Ask a worker to exit, escalating only if it ignores termination."""
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def backoff_seconds(restarts):
    return min(30, 2 ** min(max(1, int(restarts)), 5))


def run(max_cycles=None):
    quote_interval=max(.5,float(os.environ.get('LIVE_POLL_SECONDS','2')))
    candle_interval=max(2,float(os.environ.get('LIVE_CANDLE_SECONDS','5')))
    cap=max(2,int(os.environ.get('LIVE_MAX_BARS','1000')))
    seed=min(cap,max(2,int(os.environ.get('LIVE_SEED_BARS','200'))))
    market_path=Path(os.environ.get('MARKET_DB',r'Z:\data\market.db'))
    live_path=Path(os.environ.get('LIVE_DB',r'Z:\data\live.db'))
    market_path.parent.mkdir(parents=True,exist_ok=True)
    symbols=mt5.symbols_get()
    if symbols is None:
        raise RuntimeError('Cannot discover broker symbols')
    selected=choose_symbols(symbols,os.environ.get('LIVE_SYMBOLS',''))
    if not selected:
        raise RuntimeError('No supported instruments available')
    with closing(sqlite3.connect(live_path,timeout=5)) as live, closing(sqlite3.connect(market_path,timeout=5)) as market:
        live.row_factory=sqlite3.Row
        create_live_schema(live)
        worker_restarts=live.execute('SELECT COALESCE(MAX(worker_restarts),0) FROM collector_status').fetchone()[0]
        last_bars={}
        with live:
            # Preserve quote history across restarts only for configured instruments.
            live.execute('DELETE FROM instruments')
            for info,category in selected:
                enabled=mt5.symbol_select(info.name,True)
                live.execute('INSERT INTO instruments VALUES (?,?,?,?,?,?)',
                             (info.name,category,info.description,info.digits,info.point,int(enabled)))
                for frame in FRAMES:
                    table=table_name(info.name,frame)
                    create_schema(market,table)
                    row=market.execute(f'SELECT time FROM "{table}" WHERE symbol=? AND timeframe=? ORDER BY time DESC LIMIT 1',(info.name,frame)).fetchone()
                    last_bars[(info.name,frame)]=row[0] if row else None
                    if row is None:
                        live.execute('INSERT OR IGNORE INTO seed_progress VALUES (?,?,2)',(info.name,frame))
        previous={r['symbol']:dict(r) for r in live.execute('SELECT * FROM latest_quotes')}
        fx=sum(category=='fx' for _,category in selected)
        print(f'Live collector: {fx} FX + {len(selected)-fx} metals; quotes every {quote_interval:g}s, candles every {candle_interval:g}s; terminal cap {cap} bars.',flush=True)
        cycle=0; last_candles=0; candle_updated=None
        worker=None
        stopping=False
        def request_stop(_signum, _frame):
            nonlocal stopping
            stopping=True
        old_handlers={sig:signal.signal(sig,request_stop) for sig in (signal.SIGTERM,signal.SIGINT)}
        if max_cycles is None:
            worker=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--candle-worker'])
        try:
            while not stopping:
                started=time.monotonic(); now=time.time(); cycle+=1
                info=mt5.terminal_info()
                connected=bool(info and info.connected)
                if not connected:
                    reconnect()
                    info=mt5.terminal_info(); connected=bool(info and info.connected)
                last_error=None
                ticks={}
                if connected:
                    with live:
                        for instrument,_ in selected:
                            tick=mt5.symbol_info_tick(instrument.name)
                            ticks[instrument.name]=tick
                            values=quote_values(instrument.name,tick,instrument.point,previous.get(instrument.name),time.time(),broker_time_offset_seconds())
                            if values is not None:
                                write_quote(live,values)
                                previous[instrument.name]=dict(symbol=values[0],tick_time_msc=values[5],changed_at=values[7],seen_change=values[8])
                else:
                    last_error='MT5 disconnected; reconnecting'
                with live:
                    live.execute('''INSERT INTO collector_status(
                        id,heartbeat,connected,quote_interval,candle_interval,cycle,last_error,candle_updated_at
                    ) VALUES (1,?,?,?,?,?,?,?)
                        ON CONFLICT(id) DO UPDATE SET heartbeat=excluded.heartbeat,connected=excluded.connected,
                        quote_interval=excluded.quote_interval,candle_interval=excluded.candle_interval,cycle=excluded.cycle,
                        last_error=excluded.last_error''',
                                 (time.time(),int(connected),quote_interval,candle_interval,cycle,last_error,candle_updated))
                if max_cycles is not None and connected:
                    candle_updated,_=refresh_candles(market,live,selected,last_bars,seed,cap)
                if worker is not None and worker.poll() is not None:
                    exit_code=worker.returncode
                    worker_restarts+=1
                    error=f'Candle worker exited ({exit_code}); restarting ({worker_restarts})'
                    print(error,flush=True)
                    with live:
                        live.execute('UPDATE collector_status SET last_error=?,worker_restarts=? WHERE id=1',(error,worker_restarts))
                    time.sleep(backoff_seconds(worker_restarts))
                    if not stopping:
                        worker=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--candle-worker'])
                if cycle==1 or cycle%30==0:
                    print(f'Live collector cycle {cycle}: connected={connected}, quoted={len(previous)}, instruments={len(selected)}',flush=True)
                if max_cycles is not None and cycle >= max_cycles:
                    break
                time.sleep(max(.1,quote_interval-(time.monotonic()-started)))
        except KeyboardInterrupt:
            pass
        finally:
            stop_process(worker)
            with live:
                live.execute('UPDATE collector_status SET connected=0,heartbeat=?,last_error=? WHERE id=1',(time.time(),'Collector stopped'))
            mt5.shutdown()
            for sig,handler in old_handlers.items():
                signal.signal(sig,handler)


if __name__=='__main__':
    if '--candle-worker' in sys.argv:
        run_candle_worker()
    else:
        run()
