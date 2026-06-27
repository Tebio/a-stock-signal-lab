#!/usr/bin/env python3
"""Compatibility wrapper for pool strategies 1-3."""
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fenjue.pool_scripts import main_screen_pool


if __name__ == "__main__":
    raise SystemExit(main_screen_pool())
