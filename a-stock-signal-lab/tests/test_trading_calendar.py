import tempfile
import unittest
from datetime import date
from pathlib import Path

from fenjue.migrations import MigrationRunner
from fenjue.pool import validate_pool_date
from fenjue.trading_calendar import CalendarCoverageError, TradingCalendar
from fenjue.v2db import FenjueV2Database


class TradingCalendarTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = FenjueV2Database(Path(self.tmp.name) / "calendar.sqlite3")
        self.db.initialize()
        self.calendar = TradingCalendar(self.db.connection)
        self.calendar.upsert_days(
            [
                {"trade_date": "2026-06-26", "is_trade_day": True},
                {"trade_date": "2026-06-27", "is_trade_day": False},
                {"trade_date": "2026-06-28", "is_trade_day": False},
                {"trade_date": "2026-06-29", "is_trade_day": True},
                {"trade_date": "2026-06-30", "is_trade_day": False},
                {"trade_date": "2026-07-01", "is_trade_day": True},
            ],
            source="fixture",
            calendar_version="test-v1",
            available_at_ms=1,
        )

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_next_trade_date_skips_weekend_and_exchange_holiday(self):
        self.assertEqual(
            self.calendar.next_trade_date("2026-06-26"), "2026-06-29"
        )
        self.assertEqual(
            self.calendar.next_trade_date("2026-06-29"), "2026-07-01"
        )

    def test_add_trade_days_uses_calendar_rows_for_positive_and_negative_horizon(self):
        self.assertEqual(
            self.calendar.add_trade_days("2026-06-26", 2), "2026-07-01"
        )
        self.assertEqual(
            self.calendar.add_trade_days("2026-07-01", -2), "2026-06-26"
        )

    def test_missing_calendar_coverage_is_rejected_not_guessed(self):
        with self.assertRaises(CalendarCoverageError):
            self.calendar.next_trade_date("2026-07-01")

    def test_checkpoint_times_are_stored_for_each_trade_day(self):
        checkpoints = self.calendar.checkpoints("2026-06-29")
        self.assertLess(checkpoints["09:25"], checkpoints["09:40"])
        self.assertLess(checkpoints["10:30"], checkpoints["14:30"])

    def test_pool_age_uses_exchange_holiday_injected_calendar(self):
        result = validate_pool_date(
            "pool_20260626.json",
            today=date.fromisoformat("2026-07-01"),
            calendar=self.calendar,
        )
        self.assertEqual(result["trading_days_old"], 2)

    def test_migration_is_reversible_and_reapplicable(self):
        runner = MigrationRunner(self.db.connection, self.db.resource_dir / "migrations")
        runner.rollback("001")
        tables = {
            row[0] for row in self.db.connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='table'"
            )
        }
        self.assertNotIn("trading_calendar", tables)
        runner.apply_all()
        self.assertIn(
            "trading_calendar",
            {
                row[0] for row in self.db.connection.execute(
                    "SELECT name FROM sqlite_schema WHERE type='table'"
                )
            },
        )


if __name__ == "__main__":
    unittest.main()
