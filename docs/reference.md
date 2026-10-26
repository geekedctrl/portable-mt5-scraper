> Archived project reference and development notes. For current paths and commands, see ../README.md.

<a name="readme-top"></a>

<div align="center">

[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![MIT License][license-shield]][license-url]
[![LinkedIn][linkedin-shield]][linkedin-url]

<h3 align="center">MT5Scraper V0.9.5</h3>

  <p align="center">
    Scraper to easily extract historical forex, stock, ect. prices from MetaTrader5 with Python
    <br />
    <a href="https://github.com/XO30/MT5Scraper"><strong>Explore the docs »</strong></a>
    <br />
    <br />
    <a href="https://github.com/XO30/MT5Scraper/blob/main/example.ipynb">View Demo</a>
    ·
    <a href="https://github.com/XO30/MT5Scraper/issues">Report Bug</a>
    ·
    <a href="https://github.com/XO30/MT5Scraper/issues">Request Feature</a>
  </p>
</div>



<!-- ABOUT THE PROJECT -->
## About The Project

MT5Scraper is designed to help obtaining historical price data from MetaTrader5 and simplify the process. It is possible to list all available symbols as a tree with the MT5Scraper class. So it is very easy to retrieve and save data for the desired symbols.

<p align="right">(<a href="#readme-top">back to top</a>)</p>




<!-- GETTING STARTED -->
## Getting Started

To use the module some requirements must be met and some simple steps must be taken.


### Prerequisites

In order to work with the MT5Scraper class, it is necessary that MetaTrader 5 is already installed on the system. In addition, an account must be set up so that the queries can be made.


### Installation



MetaTrader5 provides a lot of binary wheels but only for w32 and w64. No Linux, no MacOS and no source code. Accordingly, as MT5Scraper requires MetaTrader5, the installation is only possible under Windows.

Install the module with pip
   ```sh
   pip3 install git+https://github.com/XO30/MT5Scraper
   ```


<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- USAGE EXAMPLES -->
## Usage

### Import Module
Import the class MT5Scraper from the library mt5_scraper
```py
from mt5_scraper import MT5Scraper
```


### Initialize Class
Make an instance of the class

In total, the following 3 parameters must be passed:
* login: login to your MT5 account
* server: server name of the account
* password: password to the account
```py
scraper = MT5Scraper(1234, 'SERVERNAME', 'PASSWORD')
print(scraper)
```


### Get the total number of symbols
With the method get_symbol_count you get the number of symbols the account has in total.
```py
scraper.get_symbol_count()
```


### Get all symbols
With the method get_symbols you get a list of all symbols. Additionally the whole structure is displayed as a tree.
```py
all_symbols = scraper.get_symbols()
```


### Get specific symbols
It is possible to pass the following parameters to the method get_symbols:
* symbol_path: path, to the desired symbols
* visualize: should the tree structure be output
```py
stocks_switzerland = scraper.get_symbols('Stocks/Switzerland/Software & IT Services', visualize=True)
```


# Get historical data
with the method get_historical_data you can download the historical prices of the desired symbols. The method has the following parameters:
* symbol_list: list containing the desired symbols
* timeframe: desired timeframe (D1, H1, etc.)
* start_date: prices from (Y, M, D, h, m, s)
* end_date: prices until (Y, M, D, h, m, s)
* save: True if dataframe should be saved else False
* save_path: folder Path to save the csv

In total there are 21 timeframes to choose: M1, M2, M3, M4, M5, M6, M10, M12, M15, M20, M30, H1, H2, H3, H4, H6, H8, H12, D1, W1, MN1
```py
data = scraper.get_historical_data(stocks_switzerland,
                                   'H1',
                                   (2022, 1, 1),
                                   (2023, 1, 11, 13, 0),
                                   save=True,
                                   save_path='stocks_switzerland_D1')
```
```py
data['TEMN.S']
```

### Store XAUUSD data in SQLite

With MetaTrader 5 running and logged in, scrape the last 30 days of hourly
XAUUSD bars into `xauusd.db`:

```sh
python xauusd_sqlite.py
```

The script is safe to rerun: bars are uniquely identified by symbol,
timeframe, and UTC timestamp. You can change the timeframe and date range:

```sh
python xauusd_sqlite.py --timeframe M15 \
  --start 2026-01-01T00:00:00+00:00 \
  --end 2026-02-01T00:00:00+00:00
```

Each symbol/timeframe combination gets its own table. For example, M1 and M5
data are stored in `XAUUSD_M1` and `XAUUSD_M5`, respectively. Each table
contains OHLC, tick volume, spread, and real volume columns.


<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- LICENSE -->
## License

Distributed under the Apache-2.0 license. See `LICENSE.txt` for more information.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- CONTACT -->
## Contact

Stefan Siegler: dev@siegler.one

Project Link: [https://github.com/XO30/MT5Scraper](https://github.com/XO30/MT5Scraper)

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- MARKDOWN LINKS & IMAGES -->
<!-- https://www.markdownguide.org/basic-syntax/#reference-style-links -->
[contributors-shield]: https://img.shields.io/github/contributors/XO30/MT5Scraper.svg?style=for-the-badge
[contributors-url]: https://github.com/XO30/MT5Scraper/graphs/contributors
[forks-shield]: https://img.shields.io/github/forks/XO30/MT5Scraper.svg?style=for-the-badge
[forks-url]: https://github.com/XO30/MT5Scraper/network/members
[stars-shield]: https://img.shields.io/github/stars/XO30/MT5Scraper.svg?style=for-the-badge
[stars-url]: https://github.com/XO30/MT5Scraper/stargazers
[issues-shield]: https://img.shields.io/github/issues/XO30/MT5Scraper.svg?style=for-the-badge
[issues-url]: https://github.com/XO30/MT5Scraper/issues
[license-shield]: https://img.shields.io/github/license/XO30/MT5Scraper.svg?style=for-the-badge
[license-url]: https://github.com/XO30/MT5Scraper/blob/master/LICENSE.txt
[linkedin-shield]: https://img.shields.io/badge/-LinkedIn-black.svg?style=for-the-badge&logo=linkedin&colorB=555
[linkedin-url]: https://linkedin.com/in/stefan-siegler-04b116205
## Download all available history into one database

Keep MetaTrader 5 open, connected, and logged in. From this project folder run:

```powershell
python -u scrape_all.py --reset
```

This clears **all tables** in `xauusd.db`, then downloads EURUSD, GBPUSD,
USDJPY, USDCHF, AUDUSD, USDCAD, NZDUSD, XAUUSD (gold), XAGUSD (silver),
and XPTUSD (platinum), each at M1, M5, H1, M15, and H4: 50 tables named
`SYMBOL_TIMEFRAME`. Omit `--reset` to retain existing data and upsert history.

The script pages backward automatically; no start date is needed. Available
history depends on the broker and MT5's **Max. bars in chart** setting. It cannot
retrieve history the terminal/broker does not supply. The latest bar can still
be forming. Times are UTC Unix seconds.

Progress prints during the run. `xauusd.report.json` records row counts and UTC
date coverage per table, failures, and SQLite integrity. A failed or empty table
causes a nonzero exit status. A reset is destructive; use it only for a fresh run.

Optional overrides: `--db other.db --symbols EURUSD XAUUSD --timeframes M1 H1`.
Run automated checks with `python -m unittest discover -s tests -v`.

Tests live in `tests/`; Docker helpers live in `docker/`. The earlier local
database is archived in `data/legacy/xauusd.db`. The active server stack uses
the Docker `mt5-data` volume, independently of this archive.

## Run MT5 and Python together in Docker

Requires Docker Desktop in Linux-container mode (x86-64). Before building from
source, run `./prepare-image.ps1` to package your installed MT5 terminal binary.
For another installation, pass `-MT5InstallDir 'C:\path\to\MT5'`.
The resulting image includes MT5 and has no Windows host-folder dependency.

```powershell
docker compose up -d --build
```

The first start prepares Wine and Windows Python and installs the pinned Python
packages; this needs internet access and can take several minutes. Open
http://127.0.0.1:6080/vnc.html, click Connect, and log into your broker's MT5
account. The container sets Max. bars in chart to 100,000,000 automatically.
Override this with `MT5_MAX_BARS` in `.env` if needed.
The browser desktop is published only on localhost and has no password; do not
publish it to other interfaces without adding authentication.

The default `desktop` mode leaves MT5 running without starting a scrape. MT5's
login and chart settings persist in the `mt5-state` Docker volume. This is a
separate terminal from the Windows installation: only `terminal64.exe` is packaged
in the image and copied into terminal state on first start. Your Windows account
credentials and existing database are not copied into the image.

After logging in, stop the desktop container, then run both MT5 and the scraper
with one command:

```powershell
docker compose down
docker compose run --rm --service-ports -e MT5_MODE=scrape mt5
```

The scrape downloads the ten default symbols and five timeframes into
`data/market.db`, with coverage/integrity results in `data/market.report.json`.
Use the browser desktop while it waits for login if necessary (default timeout:
600 seconds). The command exits when scraping completes and preserves data.
For an explicitly fresh database, append `--reset`:

```powershell
docker compose run --rm --service-ports -e MT5_MODE=scrape mt5 --reset
```

Do not run two containers against the same MT5 state/database simultaneously.
Stop the current command with Ctrl+C. To test just the MT5 connection:

```powershell
docker compose run --rm --service-ports -e MT5_MODE=check mt5
```

For logs and stopping desktop mode:

```powershell
docker compose logs -f
docker compose down
```

`docker compose down` keeps the terminal state. `docker compose down -v` deletes
that state (including the saved login); the bind-mounted `data` folder remains.
Wine compatibility depends on the MT5 build. The image uses Ubuntu 24.04, WineHQ staging (tested with 11.20), Python
3.12.10, MetaTrader5 5.0.6231, and NumPy 1.26.4. Python packages are installed into
the persistent state on first start; recreating that volume reruns installation.

### Authenticate from .env

Fill in the project-local `.env` file:

```dotenv
MT5_LOGIN=12345678
MT5_PASSWORD='your-password'
MT5_SERVER=YourBroker-Demo
```

Use the account number and exact broker server name. Single quotes preserve
characters such as `$` and `#` in passwords (unless the password itself contains
a single quote; use Compose dotenv escaping in that case). The `.env` file is
ignored by Git and excluded from the image build. Credentials are passed as
container environment variables, so anyone with Docker access can inspect them.
Do not paste resolved `docker compose config` output into shared logs.

Recreate the running desktop to apply credentials:

```powershell
docker compose up -d --build --force-recreate
```

Desktop mode now authenticates automatically when credentials are provided.
Check and scrape modes also use those credentials. All three fields must be set
together; leaving all three blank retains manual login. A failed login prevents
scraping. Once authenticated, use the scrape commands above.

## Integrated stack: one-command download

With your credentials already in `.env`, run this from PowerShell:

```powershell
.\start-stack.ps1
```

This builds/recreates the same single container, starts MT5, authenticates,
and runs the Python batch scraper automatically. SQLite runs in the Python
process, with no separate database server. The container keeps MT5 and the
browser desktop open after the job finishes. It exits with failure if scraping
fails, rather than reporting a successful job.

- Database: `data/market.db` (persistent host folder).
- Coverage and integrity report: `data/market.report.json`.
- Tables: all ten configured symbols, each at M1, M5, H1, M15, H4.
- History: all bars available through the broker/terminal; default MT5 chart
  limit is 100,000,000 bars. Broker history can still be shorter.
- Existing bars are updated by timestamp. Starting the stack preserves data.
  It does not clear the database automatically.
- Progress: `docker compose logs -f mt5`.
- Stop: `docker compose down`.

The equivalent Docker-only command is:

```powershell
docker compose -f compose.yaml -f compose.scrape.yaml up -d --build
```

For a small integration check across all 50 tables:

```powershell
.\start-stack.ps1 -SmokeTest
```

This requests at most 100 bars per table and writes a separate
`data/market-smoke.db` and `data/market-smoke.report.json`. Its report explicitly
marks the history scope as a bounded test. It is not a full-history download.
Do not use `docker compose restart` to switch modes: use the startup script or
`docker compose up` with the desired files so the configuration is recreated.

## Deploy the portable stack to a server

The deployment unit is one Linux/amd64 image containing MT5, Wine, Windows
Python, the scraper, and SQLite. SQLite runs inside Python rather than as a
separate database server. The image has no Windows installation mount. Server
Compose uses named volumes for terminal state and the SQLite database.

Build and export from this computer:

```powershell
.\prepare-image.ps1
docker compose build
.\export-stack.ps1
```

The Git-ignored `release` folder contains an image tar, server `compose.yaml`,
blank `.env.example`, and this README. Credentials, downloaded data, and saved
login state are excluded. Transfer the folder to your Linux x86-64 server with
Docker Engine and Compose v2+. ARM and Windows-container targets are untested.
The image tar can be several GB. First launch needs outbound access to PyPI
for pinned Python packages and to your broker for MT5 authentication/history.

On the server, from the transferred directory:

```sh
docker load --input mt5scraper-image.tar
cp .env.example .env
chmod 600 .env
# Edit .env with your account number, password, and exact broker server name.
SCRAPE_MAX_BARS=100 docker compose up -d
docker compose logs -f mt5
```

The first run above is a bounded test. Look for 50 tables, 5,000 bars, zero
failures, and integrity=ok. For all available history, recreate without the
temporary test limit:

```sh
docker compose up -d --force-recreate
docker compose logs -f mt5
```

Server Compose always enables stack mode. MT5 authenticates, Python downloads
history into `/data/market.db`, and MT5 remains open after success. Each start
runs one history job; it is not a periodic updater. Failures exit the container
with a nonzero status. Automatic restart is omitted to avoid repeating a failed
full-history job indefinitely. Existing rows are preserved and updated by time.

Named volumes `mt5-state` and `mt5-data` store terminal state and SQLite data.
Docker initializes their ownership, so no host-directory permission changes are
needed. Normal `docker compose down` preserves them. Removing volumes deletes
the corresponding saved login/history/database. Image exports do not include
volumes, so back up data separately.

After scraping completes, export database/report files to the server host:

```sh
docker compose cp mt5:/data/market.db ./market.db
docker compose cp mt5:/data/market.report.json ./market.report.json
```

Copy only while no scraper is writing; use SQLite's backup API for live backups.
MT5_MAX_BARS defaults to 100,000,000; broker history may be shorter. Latest bars
can still be forming. The coverage report records the actual dates retrieved.

The desktop is bound to server loopback with no VNC password. Access it through
an SSH tunnel rather than publishing it to the internet:

```sh
ssh -L 6080:127.0.0.1:6080 user@server
```

Then browse http://127.0.0.1:6080/vnc.html locally. MT5_DESKTOP_PORT changes the
server loopback port. Docker logs rotate at 10 MB, retaining three files.
Set MT5_IMAGE in server `.env` if exporting or pulling a custom image tag.
Credentials remain inspectable by administrators with Docker access.

### MT5 history boundary handling

MT5 can return its earliest candle again when a request precedes available
history. The scraper retries stale forward pages and confirms that exact
first-candle response with three one-bar probes while connected. Confirmed
boundaries are recorded as `stop_reason=confirmed_first_candle`; unrelated
repeated pages and connection failures remain errors.
