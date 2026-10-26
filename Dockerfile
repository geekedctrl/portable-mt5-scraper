FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends wine wine64 xvfb x11vnc novnc websockify openbox curl unzip python3 ca-certificates && rm -rf /var/lib/apt/lists/*
# MetaQuotes' Linux installer uses WineHQ staging rather than Ubuntu Wine 9.
RUN dpkg --add-architecture i386 && apt-get update && apt-get install -y --no-install-recommends gnupg && mkdir -p /etc/apt/keyrings && curl -fsSL https://dl.winehq.org/wine-builds/winehq.key | gpg --dearmor -o /etc/apt/keyrings/winehq-archive.key
RUN curl -fsSL https://dl.winehq.org/wine-builds/ubuntu/dists/noble/winehq-noble.sources -o /etc/apt/sources.list.d/winehq-noble.sources && apt-get update && apt-get install -y --install-recommends winehq-staging && rm -rf /var/lib/apt/lists/*
ARG PYTHON_VERSION=3.12.10
RUN mkdir -p /opt/winpython && curl -fsSL https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}-embed-amd64.zip -o /tmp/python.zip && unzip -q /tmp/python.zip -d /opt/winpython && rm /tmp/python.zip && printf '%s\n' 'python312.zip' '.' 'Z:\app' 'Lib\site-packages' 'import site' > /opt/winpython/python312._pth
RUN curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /opt/winpython/get-pip.py
RUN useradd --create-home --uid 1001 mt5 && mkdir -p /state /data && chown mt5:mt5 /state /data
COPY docker/entrypoint.sh /usr/local/bin/entrypoint
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint && chmod +x /usr/local/bin/entrypoint
COPY src/scrape_all.py src/xauusd_sqlite.py src/live_collector.py /app/
COPY docker/container_runner.py docker/configure_terminal.py /app/
COPY .image/terminal64.exe /opt/mt5/terminal64.exe
USER mt5
ENV WINEPREFIX=/state/wine WINEARCH=win64 WINEDEBUG=-all WINEDLLOVERRIDES="mscoree,mshtml=d" DISPLAY=:99 PYTHONUNBUFFERED=1
EXPOSE 6080
ENTRYPOINT ["/usr/local/bin/entrypoint"]
