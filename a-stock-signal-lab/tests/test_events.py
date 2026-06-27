import sqlite3
import tempfile
import unittest
from pathlib import Path

from fenjue.events import EventStore
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
        self.events.release_freeze(
            freeze, actor="user", release_type="manual",
            evidence={"reviewed": True}, policy_version="freeze-policy-v1",
            released_at_ms=940,
        )
        self.assertEqual(self.events.active_freezes("600378", 941), [])
        count = self.db.connection.execute(
            "SELECT COUNT(*) FROM freeze_release_audits WHERE freeze_id=?", (freeze,)
        ).fetchone()[0]
        self.assertEqual(count, 1)

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


if __name__ == "__main__":
    unittest.main()
