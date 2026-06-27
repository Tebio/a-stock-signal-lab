import sqlite3
import tempfile
import unittest
from pathlib import Path

from fenjue.shadow import (
    ShadowWriter,
    probability_release_status,
    retire_strategy_for_leakage,
)
from fenjue.v2db import FenjueV2Database


class ShadowGovernanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "v2.sqlite3"
        self.db = FenjueV2Database(self.path)
        self.db.initialize()

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_shadow_connection_cannot_write_positions(self):
        writer = ShadowWriter(self.path)
        try:
            with self.assertRaises(sqlite3.DatabaseError):
                writer.connection.execute(
                    "UPDATE positions SET mode='RISK' WHERE account_id='main'"
                )
        finally:
            writer.close()

    def test_99_samples_still_publish_frequency_only(self):
        status = probability_release_status(
            independent_decisions=99,
            positive_count=40,
            negative_count=59,
            independent_dates=70,
            calibration_ok=True,
            reconstructable=True,
        )
        self.assertEqual(status, "frequency_only")

    def test_probability_requires_every_release_gate(self):
        status = probability_release_status(
            independent_decisions=120,
            positive_count=50,
            negative_count=70,
            independent_dates=65,
            calibration_ok=True,
            reconstructable=True,
        )
        self.assertEqual(status, "probability_ready")

    def test_leakage_retires_version_with_legal_enum(self):
        self.db.connection.execute(
            """
            INSERT INTO strategy_versions
                (strategy_version_id,strategy_family,sample_cluster,code_sha256,
                 feature_set_version,policy_version,parameter_json,status,
                 probability_status,created_at_ms)
            VALUES ('v1','NEW_ENTRY','EVENT_LOGIC_AUCTION','hash','features-v1',
                    'policy-v1','{}','shadow','calibrating',1)
            """
        )
        retire_strategy_for_leakage(self.db, "v1")
        row = self.db.connection.execute(
            "SELECT status,retire_reason,probability_status FROM strategy_versions "
            "WHERE strategy_version_id='v1'"
        ).fetchone()
        self.assertEqual(tuple(row), ("retired", "leakage", "suspended"))


if __name__ == "__main__":
    unittest.main()
