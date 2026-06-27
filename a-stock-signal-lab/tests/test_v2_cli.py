import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from fenjue.cli import main
from fenjue.v2db import FenjueV2Database


class V2CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--root", str(self.root), *args])
        return code, output.getvalue()

    def test_v2_init_and_integrity_commands(self):
        code, initialized = self.call("v2-init")
        self.assertEqual(code, 0)
        self.assertIn("fenjue-v2.sqlite3", initialized)
        code, output = self.call("v2-integrity")
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["integrity_check"], "ok")
        self.assertEqual(payload["violations"], [])

    def test_v2_ledger_records_user_buy_without_broker_import(self):
        self.call("v2-init")
        code, output = self.call(
            "v2-ledger",
            "--account", "main",
            "--code", "600378",
            "--mode", "CORE_HOLD",
            "--logic-cluster", "electronic_specialty_gases",
            "--core-floor", "500",
            "--quantity", "1000",
            "--buy-price", "18.72",
            "--buy-date", "2026-06-27",
            "--sellable-from", "2026-06-30",
            "--trade-date", "2026-06-27",
            "--equity-fen", "10000000",
        )
        self.assertEqual(code, 0)
        payload = json.loads(output)
        self.assertEqual(payload["total_qty"], 1000)
        self.assertEqual(payload["sellable_qty"], 0)
        with FenjueV2Database(self.root / "data" / "fenjue-v2.sqlite3") as db:
            stored = db.connection.execute(
                "SELECT buy_price_x10000 FROM position_lots"
            ).fetchone()[0]
        self.assertEqual(stored, 187200)


if __name__ == "__main__":
    unittest.main()
