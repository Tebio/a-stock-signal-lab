from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")


def resolve_trade_date(
    value: str | None, *, now: datetime | None = None
) -> tuple[str, str]:
    if value:
        normalized = datetime.strptime(value.replace("-", ""), "%Y%m%d")
        return normalized.strftime("%Y%m%d"), "argument"
    current = now or datetime.now(tz=SHANGHAI)
    if current.tzinfo is None:
        current = current.replace(tzinfo=SHANGHAI)
    else:
        current = current.astimezone(SHANGHAI)
    return current.strftime("%Y%m%d"), "asia-shanghai-clock"


def resolve_runtime_root(
    cli_root: str | Path | None,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    values = os.environ if env is None else env
    raw = cli_root or values.get("FENJUE_HOME") or "~/.fenjue"
    return Path(raw).expanduser()


def resolve_pool_file(
    pool_file: str | Path | None,
    root: str | Path,
) -> Path:
    if pool_file:
        path = Path(pool_file).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"pool file does not exist: {path}")
        return path
    runtime_root = Path(root).expanduser()
    candidates = {
        path.resolve()
        for directory in (runtime_root, runtime_root / "pools")
        for path in directory.glob("pool_*.json")
        if path.is_file()
    }
    if not candidates:
        raise FileNotFoundError(
            f"no pool_*.json under {runtime_root} or {runtime_root / 'pools'}"
        )
    return max(candidates, key=lambda path: (path.name, str(path.parent)))
