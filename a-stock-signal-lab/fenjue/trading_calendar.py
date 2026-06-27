from __future__ import annotations

from datetime import date, datetime, time, timedelta
import sqlite3
from typing import Iterable, Mapping, Any
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")


class CalendarCoverageError(LookupError):
    pass


def _at_ms(day: str, clock: time) -> int:
    value = datetime.combine(date.fromisoformat(day), clock, tzinfo=SHANGHAI)
    return int(value.timestamp() * 1000)


class TradingCalendar:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def upsert_days(
        self,
        rows: Iterable[Mapping[str, Any]],
        *,
        source: str,
        calendar_version: str,
        available_at_ms: int,
    ) -> None:
        for row in rows:
            day = str(row["trade_date"])
            is_trade_day = int(bool(row["is_trade_day"]))
            clocks = (
                (
                    _at_ms(day, time(9, 30)),
                    _at_ms(day, time(9, 25)),
                    _at_ms(day, time(9, 40)),
                    _at_ms(day, time(10, 30)),
                    _at_ms(day, time(14, 30)),
                    _at_ms(day, time(15, 0)),
                )
                if is_trade_day else (None,) * 6
            )
            self.connection.execute(
                """
                INSERT INTO trading_calendar
                    (trade_date,is_trade_day,exchange,session_open_ms,
                     auction_0925_ms,checkpoint_0940_ms,checkpoint_1030_ms,
                     checkpoint_1430_ms,session_close_ms,source,calendar_version,
                     available_at_ms,created_at_ms)
                VALUES (?,?,'SSE_SZSE',?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(trade_date) DO UPDATE SET
                    is_trade_day=excluded.is_trade_day,
                    session_open_ms=excluded.session_open_ms,
                    auction_0925_ms=excluded.auction_0925_ms,
                    checkpoint_0940_ms=excluded.checkpoint_0940_ms,
                    checkpoint_1030_ms=excluded.checkpoint_1030_ms,
                    checkpoint_1430_ms=excluded.checkpoint_1430_ms,
                    session_close_ms=excluded.session_close_ms,
                    source=excluded.source,
                    calendar_version=excluded.calendar_version,
                    available_at_ms=excluded.available_at_ms
                """,
                (day, is_trade_day, *clocks, source, calendar_version,
                 available_at_ms, available_at_ms),
            )

    def is_trade_day(self, day: str) -> bool:
        row = self.connection.execute(
            "SELECT is_trade_day FROM trading_calendar WHERE trade_date=?", (day,)
        ).fetchone()
        if row is None:
            raise CalendarCoverageError(f"calendar has no row for {day}")
        return bool(row[0])

    def add_trade_days(self, day: str, offset: int) -> str:
        if offset == 0:
            if not self.is_trade_day(day):
                raise CalendarCoverageError(f"{day} is not a trade day")
            return day
        operator = ">" if offset > 0 else "<"
        order = "ASC" if offset > 0 else "DESC"
        row = self.connection.execute(
            f"""
            SELECT trade_date FROM trading_calendar
            WHERE is_trade_day=1 AND trade_date {operator} ?
            ORDER BY trade_date {order} LIMIT 1 OFFSET ?
            """,
            (day, abs(offset) - 1),
        ).fetchone()
        if row is None:
            raise CalendarCoverageError(
                f"calendar coverage missing for {day} offset {offset}"
            )
        return row[0]

    def next_trade_date(self, day: str) -> str:
        return self.add_trade_days(day, 1)

    def trading_days_between(self, start: str, end: str) -> int:
        if start > end:
            return -self.trading_days_between(end, start)
        self.is_trade_day(start)
        end_row = self.connection.execute(
            "SELECT 1 FROM trading_calendar WHERE trade_date=?", (end,)
        ).fetchone()
        if end_row is None:
            raise CalendarCoverageError(f"calendar has no row for {end}")
        return self.connection.execute(
            "SELECT COUNT(*) FROM trading_calendar "
            "WHERE is_trade_day=1 AND trade_date>? AND trade_date<=?",
            (start, end),
        ).fetchone()[0]

    def checkpoints(self, day: str) -> dict[str, int]:
        row = self.connection.execute(
            """
            SELECT is_trade_day,auction_0925_ms,checkpoint_0940_ms,
                   checkpoint_1030_ms,checkpoint_1430_ms
            FROM trading_calendar WHERE trade_date=?
            """,
            (day,),
        ).fetchone()
        if row is None or not row[0]:
            raise CalendarCoverageError(f"no trading session for {day}")
        return {
            "09:25": row[1],
            "09:40": row[2],
            "10:30": row[3],
            "14:30": row[4],
        }

    @staticmethod
    def compatibility_weekdays_between(start: date, end: date) -> int:
        """Legacy fallback while callers are not yet connected to the DB."""
        if start >= end:
            return 0
        days = 0
        cursor = start + timedelta(days=1)
        while cursor <= end:
            if TradingCalendar.compatibility_is_weekday(cursor):
                days += 1
            cursor += timedelta(days=1)
        return days

    @staticmethod
    def compatibility_is_weekday(day: date) -> bool:
        return day.weekday() < 5
