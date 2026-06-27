from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from .v2db import FenjueV2Database


class EventStore:
    def __init__(self, db: FenjueV2Database):
        self.db = db

    def ingest_raw(
        self,
        *,
        source_id: str,
        source_tier: str,
        source_url: str,
        content_type: str,
        raw_content: bytes,
        observed_at_ms: int,
        ingested_at_ms: int,
        published_at_ms: int | None = None,
        external_id: str | None = None,
        http_status: int | None = 200,
        fetch_metadata: dict[str, Any] | None = None,
    ) -> str:
        digest = hashlib.sha256(raw_content).hexdigest()
        existing = self.db.connection.execute(
            "SELECT raw_id FROM raw_snapshots WHERE source_id=? AND content_sha256=?",
            (source_id, digest),
        ).fetchone()
        if existing:
            return existing["raw_id"]
        raw_id = f"raw-{uuid4().hex}"
        self.db.connection.execute(
            """
            INSERT INTO raw_snapshots
                (raw_id,source_id,source_tier,source_url,external_id,content_type,
                 content_sha256,raw_content,http_status,published_at_ms,observed_at_ms,
                 ingested_at_ms,fetch_metadata_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                raw_id, source_id, source_tier, source_url, external_id, content_type,
                digest, raw_content, http_status, published_at_ms, observed_at_ms,
                ingested_at_ms,
                json.dumps(fetch_metadata or {}, ensure_ascii=False, sort_keys=True),
            ),
        )
        return raw_id

    def add_event(
        self,
        *,
        raw_id: str,
        event_id: str,
        parser_name: str,
        parser_version: str,
        event_type: str,
        title: str,
        summary: str,
        observed_at_ms: int,
        published_at_ms: int | None,
        severity: str,
        evidence_tier: str,
        payload: dict[str, Any],
        created_at_ms: int,
        schema_version: int = 1,
        event_at_ms: int | None = None,
        effective_at_ms: int | None = None,
    ) -> str:
        available_at_ms = max(observed_at_ms, published_at_ms or observed_at_ms)
        event_version_id = f"event-version-{uuid4().hex}"
        self.db.connection.execute(
            """
            INSERT INTO normalized_events
                (event_version_id,event_id,raw_id,parser_name,parser_version,
                 schema_version,event_type,title,summary,event_at_ms,published_at_ms,
                 observed_at_ms,available_at_ms,effective_at_ms,severity,evidence_tier,
                 status,normalized_payload_json,created_at_ms)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'active', ?,?)
            """,
            (
                event_version_id, event_id, raw_id, parser_name, parser_version,
                schema_version, event_type, title, summary, event_at_ms,
                published_at_ms, observed_at_ms, available_at_ms, effective_at_ms,
                severity, evidence_tier,
                json.dumps(payload, ensure_ascii=False, sort_keys=True), created_at_ms,
            ),
        )
        return event_version_id

    def link_entity(
        self,
        event_version_id: str,
        entity_type: str,
        entity_id: str,
        relation: str,
        exposure_direction: str,
        exposure_confidence_ratio: float,
        evidence: dict[str, Any],
    ) -> None:
        self.db.connection.execute(
            """
            INSERT INTO event_entity_links
                (event_version_id,entity_type,entity_id,relation,exposure_direction,
                 exposure_confidence_ratio,evidence_json)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                event_version_id, entity_type, entity_id, relation,
                exposure_direction, exposure_confidence_ratio,
                json.dumps(evidence, ensure_ascii=False, sort_keys=True),
            ),
        )

    def events_available_for(self, code: str, decision_at_ms: int) -> list[dict[str, Any]]:
        rows = self.db.connection.execute(
            """
            SELECT e.* FROM normalized_events e
            JOIN event_entity_links l ON l.event_version_id=e.event_version_id
            WHERE l.entity_type='stock' AND l.entity_id=?
              AND e.status='active' AND e.available_at_ms<=?
            ORDER BY e.available_at_ms,e.event_version_id
            """,
            (code, decision_at_ms),
        ).fetchall()
        return [dict(row) for row in rows]

    def freeze(
        self,
        code: str,
        event_version_id: str,
        freeze_scope: str,
        reason: str,
        starts_at_ms: int,
        release_condition: str,
        policy_version: str,
        created_at_ms: int,
        ends_at_ms: int | None = None,
    ) -> str:
        freeze_id = f"freeze-{uuid4().hex}"
        self.db.connection.execute(
            """
            INSERT INTO event_freezes
                (freeze_id,code,event_version_id,freeze_scope,freeze_reason,
                 starts_at_ms,ends_at_ms,release_condition,status,policy_version,
                 created_at_ms)
            VALUES (?,?,?,?,?,?,?,?,'active',?,?)
            """,
            (
                freeze_id, code, event_version_id, freeze_scope, reason,
                starts_at_ms, ends_at_ms, release_condition, policy_version,
                created_at_ms,
            ),
        )
        return freeze_id

    def release_freeze(
        self,
        freeze_id: str,
        *,
        actor: str,
        release_type: str,
        evidence: dict[str, Any],
        policy_version: str,
        released_at_ms: int,
        release_event_version_id: str | None = None,
    ) -> str:
        audit_id = f"freeze-release-{uuid4().hex}"
        with self.db.transaction() as connection:
            connection.execute(
                """
                INSERT INTO freeze_release_audits
                    (release_audit_id,freeze_id,release_type,released_by,
                     release_evidence_json,release_event_version_id,policy_version,
                     released_at_ms,created_at_ms)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    audit_id, freeze_id, release_type, actor,
                    json.dumps(evidence, ensure_ascii=False, sort_keys=True),
                    release_event_version_id, policy_version, released_at_ms,
                    released_at_ms,
                ),
            )
            connection.execute(
                "UPDATE event_freezes SET status='released',ends_at_ms=? "
                "WHERE freeze_id=? AND status='active'",
                (released_at_ms, freeze_id),
            )
        return audit_id

    def active_freezes(self, code: str, at_ms: int) -> list[dict[str, Any]]:
        rows = self.db.connection.execute(
            """
            SELECT * FROM event_freezes
            WHERE code=? AND status='active' AND starts_at_ms<=?
              AND (ends_at_ms IS NULL OR ends_at_ms>?)
            ORDER BY starts_at_ms,freeze_id
            """,
            (code, at_ms, at_ms),
        ).fetchall()
        return [dict(row) for row in rows]

    def record_source_incident(
        self,
        source_id: str,
        source_tier: str,
        incident_type: str,
        details: dict[str, Any],
        policy_version: str,
        started_at_ms: int,
    ) -> str:
        incident_id = f"source-incident-{uuid4().hex}"
        blocks_new_risk = int(
            source_tier == "A"
            and incident_type in {"unavailable", "stale", "time_inconsistent"}
        )
        self.db.connection.execute(
            """
            INSERT INTO source_health_incidents
                (source_incident_id,source_id,source_tier,incident_type,status,
                 blocks_new_risk,details_json,policy_version,started_at_ms,created_at_ms)
            VALUES (?,?,?,?, 'open', ?,?,?,?,?)
            """,
            (
                incident_id, source_id, source_tier, incident_type, blocks_new_risk,
                json.dumps(details, ensure_ascii=False, sort_keys=True),
                policy_version, started_at_ms, started_at_ms,
            ),
        )
        return incident_id

    def resolve_source_incident(self, incident_id: str, resolved_at_ms: int) -> None:
        self.db.connection.execute(
            "UPDATE source_health_incidents SET status='resolved',resolved_at_ms=? "
            "WHERE source_incident_id=? AND status='open'",
            (resolved_at_ms, incident_id),
        )

    def new_risk_block_reason(self, at_ms: int) -> str | None:
        row = self.db.connection.execute(
            """
            SELECT source_incident_id FROM source_health_incidents
            WHERE source_tier='A' AND blocks_new_risk=1 AND started_at_ms<=?
              AND (resolved_at_ms IS NULL OR resolved_at_ms>?)
            LIMIT 1
            """,
            (at_ms, at_ms),
        ).fetchone()
        return "OFFICIAL_EVENT_SOURCE_UNAVAILABLE" if row else None
