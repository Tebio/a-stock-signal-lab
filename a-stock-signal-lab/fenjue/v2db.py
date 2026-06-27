from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class FenjueV2Database:
    """SQLite boundary for the V2 audit and decision system.

    A database instance owns one connection. Every new instance enables and
    verifies foreign keys before exposing the connection to callers.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(
            self.path,
            timeout=30,
            isolation_level=None,
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA busy_timeout = 30000")
        if self.connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            self.connection.close()
            raise RuntimeError("SQLite foreign key enforcement is unavailable")

    @property
    def resource_dir(self) -> Path:
        return Path(__file__).resolve().parent / "sql"

    def initialize(self) -> None:
        schema = (self.resource_dir / "schema_v2.sql").read_text(encoding="utf-8")
        self.connection.executescript(schema)
        if self.connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Fenjue V2 schema failed SQLite integrity_check")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield self.connection
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        else:
            self.connection.execute("COMMIT")

    def compatibility_probe(self) -> dict[str, object]:
        json1 = False
        try:
            json1 = self.connection.execute(
                "SELECT json_valid(?)", ('{"fenjue":2}',)
            ).fetchone()[0] == 1
        except sqlite3.OperationalError:
            pass
        return {
            "sqlite_version": sqlite3.sqlite_version,
            "foreign_keys": self.connection.execute("PRAGMA foreign_keys").fetchone()[0],
            "json1": json1,
            "compile_options": [
                row[0] for row in self.connection.execute("PRAGMA compile_options")
            ],
        }

    def integrity_report(self) -> dict[str, object]:
        integrity = self.connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = [dict(row) for row in self.connection.execute("PRAGMA foreign_key_check")]
        violations: list[dict[str, object]] = []
        sql = (self.resource_dir / "integrity_checks.sql").read_text(encoding="utf-8")
        without_line_comments = "\n".join(
            line for line in sql.splitlines() if not line.lstrip().startswith("--")
        )
        statement = ""
        for line in without_line_comments.splitlines():
            statement += line + "\n"
            if not sqlite3.complete_statement(statement):
                continue
            stripped = statement.strip()
            statement = ""
            if not stripped.upper().startswith("SELECT"):
                continue
            cursor = self.connection.execute(stripped)
            names = [item[0] for item in cursor.description or ()]
            for row in cursor.fetchall():
                data = dict(zip(names, row))
                check_name = str(data.get("check_name", ""))
                if not check_name.startswith("INFO_"):
                    violations.append(data)
        return {
            "integrity_check": integrity,
            "foreign_key_violations": foreign_keys,
            "violations": violations,
        }

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "FenjueV2Database":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
