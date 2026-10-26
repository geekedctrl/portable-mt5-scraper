#!/bin/bash
set -euo pipefail
cleanup() {
    status=$?
    trap - EXIT TERM INT
    children="$(jobs -pr)"
    if [ -n "$children" ]; then
        kill -TERM $children 2>/dev/null || true
        for pid in $children; do
            for _ in $(seq 1 100); do
                kill -0 "$pid" 2>/dev/null || break
                sleep 0.1
            done
            kill -0 "$pid" 2>/dev/null && kill -KILL "$pid" 2>/dev/null || true
        done
        wait $children 2>/dev/null || true
    fi
    timeout 20s wineserver -w || { wineserver -k || true; }
    exit "$status"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
Xvfb :99 -screen 0 1440x900x24 -nolisten tcp &
for i in $(seq 1 50); do [ -S /tmp/.X11-unix/X99 ] && break; sleep 0.1; done
openbox >/tmp/openbox.log 2>&1 &
x11vnc -display :99 -forever -shared -localhost -nopw -rfbport 5900 >/tmp/vnc.log 2>&1 &
websockify --web=/usr/share/novnc/ 6080 localhost:5900 >/tmp/novnc.log 2>&1 &
mkdir -p "$WINEPREFIX" /state/terminal /state/python
if [ ! -f /state/terminal/terminal64.exe ]; then
    cp /opt/mt5/terminal64.exe /state/terminal/
fi
if [ ! -f /state/python/.ready-5.0.6231-1.26.4 ]; then
    cp -a /opt/winpython/. /state/python/
    wineboot -u
    wineserver -w
    wine /state/python/python.exe /state/python/get-pip.py --disable-pip-version-check
    wine /state/python/python.exe -m pip install --disable-pip-version-check MetaTrader5==5.0.6231 numpy==1.26.4
    touch /state/python/.ready-5.0.6231-1.26.4
fi
if [ "${MT5_MODE:-desktop}" = live ]; then
    export MT5_MAX_BARS="${LIVE_MAX_BARS:-1000}"
fi
python3 /app/configure_terminal.py
winecfg -v win11
max_bars="${MT5_MAX_BARS:-100000000}"
[[ "$max_bars" =~ ^[1-9][0-9]*$ ]] || { echo 'MT5_MAX_BARS must be a positive integer'; exit 1; }
printf '[Charts]\r\nMaxBars=%s\r\n' "$max_bars" > /state/bootstrap.ini
wine /state/terminal/terminal64.exe /portable /config:Z:\\state\\bootstrap.ini >/tmp/terminal.log 2>&1 &
echo 'MT5 desktop: http://localhost:6080/vnc.html (connect, then log into MT5)'
if [ "${MT5_MODE:-desktop}" = desktop ]; then
    if [ -n "${MT5_LOGIN:-}${MT5_PASSWORD:-}${MT5_SERVER:-}" ]; then
        MT5_MODE=check wine /state/python/python.exe Z:\\app\\container_runner.py
    fi
    wait -n
else
    wine /state/python/python.exe Z:\\app\\container_runner.py "$@" &
    runner_pid=$!
    wait "$runner_pid"
    if [ "${MT5_MODE:-desktop}" = stack ]; then
        echo 'Scrape complete. SQLite and the coverage report are in the data folder. MT5 remains running.'
        wait -n || true
    fi
fi
