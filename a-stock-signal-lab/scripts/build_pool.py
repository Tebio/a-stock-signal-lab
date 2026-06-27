#!/usr/bin/env python3
"""Compatibility wrapper for the pool builder."""
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fenjue.pool_scripts import main_build_pool


if __name__ == "__main__":
    raise SystemExit(main_build_pool())
