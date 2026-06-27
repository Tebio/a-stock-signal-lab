import sqlite3
import tempfile
import unittest
from pathlib import Path

from fenjue.events import EventStore
from fenjue.migrations import MigrationRunner
from fenjue.v2db import FenjueV2Database


class EventStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = FenjueV2Database(Path(self.tmp.name) / "v2.sqlite3")
        self.db.initialize()
        self.events = EventStore(self.db)
        self.raw_id = self.events.ingest_raw(
            source_id="cninfo",
            source_tier="A",
            source_url="https://example.test/a",
            content_type="application/json",
            raw_content=b'{"title":"inquiry"}',
            observed_at_ms=931,
            ingested_at_ms=932,
            published_at_ms=920,
        )

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def _event(self):
        event_id = self.events.add_event(
            raw_id=self.raw_id,
            event_id="cninfo:1",
            parser_name="cninfo",
            parser_version="1",
            event_type="REGULATORY_INQUIRY",
            title="问询",
            summary="监管问询",
            observed_at_ms=931,
            published_at_ms=920,
            severity="high",
            evidence_tier="A",
            payload={},
            created_at_ms=933,
        )
        self.events.link_entity(event_id, "stock", "600378", "subject", "negative", 1.0, {})
        return event_id

    def _typed_event(self, event_type, event_id, severity="high", observed=931):
        version = self.events.add_event(
            raw_id=self.raw_id, event_id=event_id, parser_name="cninfo",
            parser_version="1", event_type=event_type, title=event_type,
            summary=event_type, observed_at_ms=observed, published_at_ms=920,
            severity=severity, evidence_tier="A", payload={}, created_at_ms=observed + 1,
        )
        self.events.link_entity(version, "stock", "600378", "subject", "negative", 1.0, {})
        return version

    def test_delayed_fetch_is_not_available_to_earlier_decision(self):
        self._event()
        self.assertEqual(self.events.events_available_for("600378", 925), [])
        self.assertEqual(len(self.events.events_available_for("600378", 931)), 1)

    def test_freeze_requires_real_event_foreign_key(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.events.freeze(
                "600378", "missing", "add", "fixture", 1,
                "manual review", "freeze-policy-v1", 1,
            )

    def test_release_requires_audit_and_store_releases_atomically(self):
        event = self._event()
        freeze = self.events.freeze(
            "600378", event, "add", "regulatory inquiry", 931,
            "A-tier follow-up or manual review", "freeze-policy-v1", 932,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.connection.execute(
                "UPDATE event_freezes SET status='released' WHERE freeze_id=?",
                (freeze,),
            )
        with self.assertRaises(PermissionError):
            self.events.release_freeze(
                freeze, actor="user", release_type="manual",
                evidence={"reviewed": True}, policy_version="freeze-policy-v1",
                released_at_ms=940,
            )
        request = self.events.request_override(
            freeze, requested_by="user", requested_action="release",
            reason="人工核验", evidence={"reviewed": True}, created_at_ms=938,
        )
        self.events.review_override(
            request, reviewed_by="risk-owner", approved=True,
            review_note="证据充分", reviewed_at_ms=939,
        )
        self.assertEqual(len(self.events.active_freezes("600378", 939)), 1)
        self.events.release_freeze(
            freeze, actor="user", release_type="manual",
            evidence={"override_request_id": request}, policy_version="freeze-policy-v1",
            released_at_ms=940,
        )
        self.assertEqual(self.events.active_freezes("600378", 941), [])
        count = self.db.connection.execute(
            "SELECT COUNT(*) FROM freeze_release_audits WHERE freeze_id=?", (freeze,)
        ).fetchone()[0]
        self.assertEqual(count, 1)
        with self.assertRaises(ValueError):
            self.events.release_freeze(
                freeze, actor="user", release_type="manual",
                evidence={"override_request_id": request}, policy_version="freeze-policy-v1",
                released_at_ms=950,
            )

    def test_a_tier_source_outage_blocks_new_risk_until_resolved(self):
        incident = self.events.record_source_incident(
            "cninfo", "A", "unavailable", {"error": "timeout"},
            "source-health-v1", 1000,
        )
        self.assertEqual(
            self.events.new_risk_block_reason(1001),
            "OFFICIAL_EVENT_SOURCE_UNAVAILABLE",
        )
        self.events.resolve_source_incident(incident, 1010)
        self.assertIsNone(self.events.new_risk_block_reason(1011))

    def test_default_policy_freezes_suspension_inquiry_discipline_and_major_notice(self):
        cases = {
            "TRADING_SUSPENSION": "all_scoring",
            "TRADING_RESUMPTION": "new_entry",
            "REGULATORY_INQUIRY": "new_entry",
            "DISCIPLINARY_ACTION": "all_scoring",
            "MAJOR_ANNOUNCEMENT": "new_entry",
        }
        for index, (event_type, expected_scope) in enumerate(cases.items()):
            with self.subTest(event_type=event_type):
                event = self._typed_event(event_type, f"cninfo:policy:{index}")
                freezes = self.events.apply_default_freezes(
                    event, evaluated_at_ms=935 + index
                )
                self.assertIn(expected_scope, {row["freeze_scope"] for row in freezes})

    def test_event_not_available_at_decision_time_cannot_freeze_early(self):
        event = self._typed_event(
            "REGULATORY_INQUIRY", "cninfo:future", observed=1000
        )
        self.assertEqual(
            self.events.apply_default_freezes(event, evaluated_at_ms=999), []
        )

    def test_migration_005_rolls_back_and_reapplies(self):
        runner = MigrationRunner(self.db.connection, self.db.resource_dir / "migrations")
        runner.rollback("005")
        tables = {row[0] for row in self.db.connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        self.assertNotIn("override_requests", tables)
        runner.apply_all()
        tables = {row[0] for row in self.db.connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        self.assertIn("event_freeze_policies", tables)


if __name__ == "__main__":
    unittest.main()
