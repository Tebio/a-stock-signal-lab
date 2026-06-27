import sqlite3
import tempfile
import unittest
from pathlib import Path

from fenjue.v2db import FenjueV2Database


class FenjueV2DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "fenjue-v2.sqlite3"
        self.db = FenjueV2Database(self.path)
        self.db.initialize()

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_initializes_canonical_schema_with_foreign_keys(self):
        self.assertEqual(self.db.connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        tables = self.db.connection.execute(
            "SELECT name FROM sqlite_schema "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        self.assertEqual(len(tables), 30)
        self.assertEqual(self.db.connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_rejects_orphan_audit_row(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.connection.execute(
                "INSERT INTO manual_overrides "
                "(override_id, decision_id, system_action, user_action, "
                "override_reason, action_time_ms) VALUES (?, ?, ?, ?, ?, ?)",
                ("override-1", "missing", "HOLD", "HOLD", "fixture", 1),
            )

    def test_money_price_and_quantity_columns_are_not_real(self):
        bad = []
        for (table,) in self.db.connection.execute(
            "SELECT name FROM sqlite_schema "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ):
            for row in self.db.connection.execute(f"PRAGMA table_info({table})"):
                name, sql_type = row[1], row[2].upper()
                if sql_type == "REAL" and any(
                    token in name
                    for token in ("price", "amount", "equity", "fee", "quantity", "qty")
                ):
                    bad.append((table, name))
        self.assertEqual(bad, [])

    def test_integrity_report_is_clean_on_empty_database(self):
        report = self.db.integrity_report()
        self.assertEqual(report["integrity_check"], "ok")
        self.assertEqual(report["foreign_key_violations"], [])
        self.assertEqual(report["violations"], [])

    def test_compatibility_probe_reports_runtime_capabilities(self):
        probe = self.db.compatibility_probe()
        self.assertEqual(probe["foreign_keys"], 1)
        self.assertIn("sqlite_version", probe)
        self.assertIn("json1", probe)


if __name__ == "__main__":
    unittest.main()
