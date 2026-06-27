from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from .v2db import FenjueV2Database


def probability_release_status(
    *,
    independent_decisions: int,
    positive_count: int,
    negative_count: int,
    independent_dates: int,
    calibration_ok: bool,
    reconstructable: bool,
) -> str:
    ready = (
        independent_decisions >= 100
        and positive_count >= 20
        and negative_count >= 20
        and independent_dates >= 60
        and calibration_ok
        and reconstructable
    )
    return "probability_ready" if ready else "frequency_only"


def retire_strategy_for_leakage(
    db: FenjueV2Database, strategy_version_id: str
) -> None:
    db.connection.execute(
        """
        UPDATE strategy_versions
        SET status='retired',retire_reason='leakage',probability_status='suspended'
        WHERE strategy_version_id=?
        """,
        (strategy_version_id,),
    )


class ShadowWriter:
    """Restricted connection that may append only to shadow_decisions."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.connection = sqlite3.connect(self.path, isolation_level=None, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        if self.connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            self.connection.close()
            raise RuntimeError("shadow connection requires foreign keys")

        write_actions = {
            sqlite3.SQLITE_INSERT,
            sqlite3.SQLITE_UPDATE,
            sqlite3.SQLITE_DELETE,
        }

        def authorizer(action, table, column, database, trigger):
            if action in write_actions and table != "shadow_decisions":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        self.connection.set_authorizer(authorizer)

    def append(
        self,
        *,
        strategy_version_id: str,
        code: str,
        logic_cluster_id: str,
        strategy_family: str,
        decision_at_ms: int,
        action: str,
        max_exposure_ratio: float,
        reason_codes: list[str],
        feature_snapshot_id: str,
        data_manifest_id: str,
        production_decision_id: str | None = None,
        outcome_id: str | None = None,
        shadow_id: str | None = None,
    ) -> str:
        shadow_id = shadow_id or f"shadow-{uuid4().hex}"
        self.connection.execute(
            """
            INSERT INTO shadow_decisions
                (shadow_id,production_decision_id,strategy_version_id,code,
                 logic_cluster_id,strategy_family,decision_at_ms,action,
                 max_exposure_ratio,reason_codes_json,feature_snapshot_id,
                 data_manifest_id,outcome_id,displayed_to_user,created_at_ms)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0,?)
            """,
            (
                shadow_id, production_decision_id, strategy_version_id, code,
                logic_cluster_id, strategy_family, decision_at_ms, action,
                max_exposure_ratio, json.dumps(reason_codes), feature_snapshot_id,
                data_manifest_id, outcome_id, decision_at_ms,
            ),
        )
        return shadow_id

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "ShadowWriter":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
