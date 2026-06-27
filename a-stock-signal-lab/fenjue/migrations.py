from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    up_path: Path
    down_path: Path


def _statements(script: str) -> list[str]:
    statements: list[str] = []
    pending = ""
    for line in script.splitlines():
        pending += line + "\n"
        if sqlite3.complete_statement(pending):
            statements.append(pending.strip())
            pending = ""
    if pending.strip():
        raise ValueError("incomplete SQL migration statement")
    return statements


class MigrationRunner:
    pattern = re.compile(r"^(?P<version>\d+)_(?P<name>.+)_up\.sql$")

    def __init__(self, connection: sqlite3.Connection, directory: str | Path):
        self.connection = connection
        self.directory = Path(directory)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at_ms INTEGER NOT NULL
            )
            """
        )

    def discover(self) -> list[Migration]:
        migrations: list[Migration] = []
        for up_path in sorted(self.directory.glob("*_up.sql")):
            match = self.pattern.match(up_path.name)
            if not match:
                continue
            version = match.group("version")
            name = match.group("name")
            down_path = self.directory / f"{version}_{name}_down.sql"
            if not down_path.exists():
                raise FileNotFoundError(f"missing rollback migration: {down_path}")
            migrations.append(Migration(version, name, up_path, down_path))
        return migrations

    def applied_versions(self) -> set[str]:
        return {
            row[0] for row in self.connection.execute(
                "SELECT version FROM schema_migrations"
            )
        }

    def _execute(self, statements: list[str], finalize) -> None:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            for statement in statements:
                self.connection.execute(statement)
            finalize()
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        else:
            self.connection.execute("COMMIT")

    def apply_all(self, applied_at_ms: int = 0) -> list[str]:
        applied = self.applied_versions()
        changed: list[str] = []
        for migration in self.discover():
            if migration.version in applied:
                continue
            statements = _statements(migration.up_path.read_text(encoding="utf-8"))
            self._execute(
                statements,
                lambda m=migration: self.connection.execute(
                    "INSERT INTO schema_migrations(version,name,applied_at_ms) "
                    "VALUES (?,?,?)",
                    (m.version, m.name, applied_at_ms),
                ),
            )
            changed.append(migration.version)
        return changed

    def rollback(self, version: str) -> None:
        migration = next(
            (item for item in self.discover() if item.version == version), None
        )
        if migration is None:
            raise KeyError(f"unknown migration: {version}")
        if version not in self.applied_versions():
            raise ValueError(f"migration is not applied: {version}")
        statements = _statements(migration.down_path.read_text(encoding="utf-8"))
        self._execute(
            statements,
            lambda: self.connection.execute(
                "DELETE FROM schema_migrations WHERE version=?", (version,)
            ),
        )

    def dry_run(self) -> list[str]:
        clone = sqlite3.connect(":memory:", isolation_level=None)
        clone.execute("PRAGMA foreign_keys=ON")
        self.connection.backup(clone)
        runner = MigrationRunner(clone, self.directory)
        runner.apply_all()
        for migration in reversed(runner.discover()):
            if migration.version in runner.applied_versions():
                runner.rollback(migration.version)
        changed = runner.apply_all()
        if clone.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("migration dry-run integrity failure")
        clone.close()
        return changed
