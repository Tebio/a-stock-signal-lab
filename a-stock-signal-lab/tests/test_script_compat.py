import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fenjue.script_compat import (
    resolve_pool_file,
    resolve_runtime_root,
    resolve_trade_date,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


class ScriptCompatibilityTests(unittest.TestCase):
    def test_explicit_date_is_normalized_and_source_is_reported(self):
        value, source = resolve_trade_date("2026-06-27")
        self.assertEqual(value, "20260627")
        self.assertEqual(source, "argument")

    def test_missing_date_uses_asia_shanghai_clock_not_static_default(self):
        value, source = resolve_trade_date(
            None, now=datetime(2026, 6, 26, 16, 30, tzinfo=timezone.utc)
        )
        self.assertEqual(value, "20260627")
        self.assertEqual(source, "asia-shanghai-clock")

    def test_runtime_root_precedence_is_cli_then_environment_then_home(self):
        env = {"FENJUE_HOME": "/env/fenjue"}
        self.assertEqual(resolve_runtime_root("/cli/fenjue", env=env), Path("/cli/fenjue"))
        self.assertEqual(resolve_runtime_root(None, env=env), Path("/env/fenjue"))
        self.assertEqual(
            resolve_runtime_root(None, env={}), Path.home() / ".fenjue"
        )

    def test_latest_pool_resolution_does_not_depend_on_current_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pool_20260626.json").write_text("{}", encoding="utf-8")
            latest = root / "pool_20260627.json"
            latest.write_text("{}", encoding="utf-8")
            previous = Path.cwd()
            try:
                os.chdir(Path(tmp).parent)
                self.assertEqual(resolve_pool_file(None, root), latest.resolve())
            finally:
                os.chdir(previous)

    def test_legacy_script_wrappers_offer_help_from_arbitrary_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            for script in ("build_pool.py", "screen_pool.py", "screen_pool2.py"):
                result = subprocess.run(
                    [sys.executable, str(REPO_ROOT / "scripts" / script), "--help"],
                    cwd=tmp,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("--root", result.stdout)

    def test_package_cli_exposes_same_pool_commands(self):
        result = subprocess.run(
            [sys.executable, "-m", "fenjue", "--help"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("build-pool", result.stdout)
        self.assertIn("screen-pool2", result.stdout)
        self.assertIn("v2-budget", result.stdout)


if __name__ == "__main__":
    unittest.main()
