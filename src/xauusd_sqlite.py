"""Scrape XAUUSD historical bars from MetaTrader 5 into SQLite."""

import argparse
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import MetaTrader5 as mt5


TIMEFRAMES = {
    "M1": mt5.TIMEFRAME_M1,
    "M2": mt5.TIMEFRAME_M2,
    "M3": mt5.TIMEFRAME_M3,
    "M4": mt5.TIMEFRAME_M4,
    "M5": mt5.TIMEFRAME_M5,
    "M6": mt5.TIMEFRAME_M6,
    "M10": mt5.TIMEFRAME_M10,
    "M12": mt5.TIMEFRAME_M12,
    "M15": mt5.TIMEFRAME_M15,
    "M20": mt5.TIMEFRAME_M20,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H2": mt5.TIMEFRAME_H2,
    "H3": mt5.TIMEFRAME_H3,
    "H4": mt5.TIMEFRAME_H4,
    "H6": mt5.TIMEFRAME_H6,
    "H8": mt5.TIMEFRAME_H8,
    "H12": mt5.TIMEFRAME_H12,
    "D1": mt5.TIMEFRAME_D1,
    "W1": mt5.TIMEFRAME_W1,
    "MN1": mt5.TIMEFRAME_MN1,
}


def parse_datetime(value: str) -> datetime:
    """Parse an ISO-8601 date/time and normalize it to UTC."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def table_name(symbol: str, timeframe: str) -> str:
    """Return a safe SQLite table name for a symbol/timeframe pair."""
    name = f"{symbol}_{timeframe}"
    if re.fullmatch(r"[A-Za-z0-9_]+", name) is None:
        raise ValueError(f"Invalid symbol for SQLite table name: {symbol!r}")
    return name


def create_schema(connection: sqlite3.Connection, table: str) -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{table}" (
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            time INTEGER NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            tick_volume INTEGER NOT NULL,
            spread INTEGER NOT NULL,
            real_volume INTEGER NOT NULL,
            PRIMARY KEY (symbol, timeframe, time)
        )
        """
    )
    connection.commit()


def scrape(
    database: Path,
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
) -> int:
    """Fetch bars from MT5 and upsert them into SQLite."""
    if timeframe not in TIMEFRAMES:
        raise ValueError(
            f"Unsupported timeframe {timeframe!r}; choose one of {', '.join(TIMEFRAMES)}"
        )
    if start >= end:
        raise ValueError("The start time must be earlier than the end time")

    if not mt5.initialize():
        raise RuntimeError(f"MetaTrader 5 initialization failed: {mt5.last_error()}")

    try:
        if not mt5.symbol_select(symbol, True):
            raise RuntimeError(
                f"Could not select {symbol!r} in MetaTrader 5: {mt5.last_error()}"
            )

        rates = mt5.copy_rates_range(
            symbol, TIMEFRAMES[timeframe], start, end
        )
        if rates is None:
            raise RuntimeError(
                f"Could not retrieve {symbol} data: {mt5.last_error()}"
            )

        rows = [
            (
                symbol,
                timeframe,
                int(rate["time"]),
                float(rate["open"]),
                float(rate["high"]),
                float(rate["low"]),
                float(rate["close"]),
                int(rate["tick_volume"]),
                int(rate["spread"]),
                int(rate["real_volume"]),
            )
            for rate in rates
        ]
    finally:
        mt5.shutdown()

    table = table_name(symbol, timeframe)
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as connection:
        create_schema(connection, table)
        connection.executemany(
            f"""
            INSERT OR REPLACE INTO "{table}" (
                symbol, timeframe, time, open, high, low, close,
                tick_volume, spread, real_volume
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.commit()

    return len(rows)


def main() -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    parser = argparse.ArgumentParser(
        description="Scrape XAUUSD historical bars into a SQLite database."
    )
    parser.add_argument("--db", type=Path, default=Path(__file__).resolve().parent.parent / "data" / "xauusd.db")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", choices=TIMEFRAMES, default="H1")
    parser.add_argument(
        "--start",
        default=(now - timedelta(days=30)).isoformat(),
        help="UTC ISO-8601 start time (default: 30 days ago)",
    )
    parser.add_argument(
        "--end",
        default=now.isoformat(),
        help="UTC ISO-8601 end time (default: now)",
    )
    args = parser.parse_args()

    inserted = scrape(
        args.db,
        args.symbol,
        args.timeframe,
        parse_datetime(args.start),
        parse_datetime(args.end),
    )
    print(
        f"Stored {inserted} {args.timeframe} bars for {args.symbol} "
        f"in {args.db}"
    )


if __name__ == "__main__":
    main()
