#!/usr/bin/env python3
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fenjue.migrations import MigrationRunner
from fenjue.v2db import FenjueV2Database


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        database = FenjueV2Database(Path(tmp) / "migration-dry-run.sqlite3")
        database.initialize()
        runner = MigrationRunner(
            database.connection, database.resource_dir / "migrations"
        )
        expected = [migration.version for migration in runner.discover()]
        replayed = runner.dry_run()
        if replayed != expected:
            raise RuntimeError(f"migration replay mismatch: {replayed} != {expected}")
        if database.connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("source database failed integrity check")
        database.close()
    print("migration dry-run ok: " + ",".join(expected))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
