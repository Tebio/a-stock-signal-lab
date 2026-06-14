from __future__ import annotations

import threading
import time
from datetime import date, datetime, timedelta

from .runtime import Runtime
from .service import normalize_code


def normalize_history_code(code: str) -> str:
    text = str(code).strip().lower()
    if len(text) == 8 and text[:2] in {"sh", "sz"} and text[2:].isdigit():
        return text
    return normalize_code(text)


class UpstreamGate:
    def __init__(self, limit: int = 6):
        self.limit = max(1, limit)
        self._semaphore = threading.BoundedSemaphore(self.limit)

    def __enter__(self):
        self._semaphore.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self._semaphore.release()


class DailyBarService:
    def __init__(
        self,
        runtime: Runtime,
        provider,
        *,
        gate: UpstreamGate | None = None,
        today=date.today,
    ):
        self.runtime = runtime
        self.provider = provider
        self.gate = gate or UpstreamGate()
        self.today = today
        self._lock = threading.Lock()
        self._inflight: dict[str, threading.Event] = {}

    def get(self, code: str, years: int = 2) -> list[dict]:
        return self.get_with_status(code, years=years)["rows"]

    def get_with_status(self, code: str, years: int = 2) -> dict:
        code = normalize_history_code(code)
        today = self.today()
        refresh_date = today.isoformat()
        state = self.runtime.refresh_state("daily", code)
        if state and state["refresh_date"] == refresh_date:
            return {
                "rows": self.runtime.load_daily(code),
                "stale": state["status"] != "ok",
                "error": state.get("error"),
            }

        owner = False
        with self._lock:
            event = self._inflight.get(code)
            if event is None:
                event = threading.Event()
                self._inflight[code] = event
                owner = True
        if not owner:
            event.wait(timeout=30)
            state = self.runtime.refresh_state("daily", code)
            return {
                "rows": self.runtime.load_daily(code),
                "stale": bool(state and state["status"] != "ok"),
                "error": state.get("error") if state else None,
            }

        try:
            cached = self.runtime.load_daily(code)
            try:
                with self.gate:
                    if cached and hasattr(self.provider, "fetch_range"):
                        latest = datetime.strptime(
                            cached[-1]["trade_date"],
                            "%Y-%m-%d",
                        ).date()
                        rows = self.provider.fetch_range(
                            code,
                            latest + timedelta(days=1),
                            today,
                        )
                    else:
                        rows = self.provider.fetch(code, years=years)
                self.runtime.upsert_daily(rows)
                self.runtime.mark_refresh(
                    "daily",
                    code,
                    refresh_date,
                    status="ok",
                )
                return {
                    "rows": self.runtime.load_daily(code),
                    "stale": False,
                    "error": None,
                }
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                self.runtime.mark_refresh(
                    "daily",
                    code,
                    refresh_date,
                    status="error",
                    error=error,
                )
                if cached:
                    return {"rows": cached, "stale": True, "error": error}
                raise
        finally:
            with self._lock:
                self._inflight.pop(code, None)
                event.set()


class MinuteBarService:
    def __init__(
        self,
        runtime: Runtime,
        provider,
        *,
        cache_ttl: float = 60,
        gate: UpstreamGate | None = None,
    ):
        self.runtime = runtime
        self.provider = provider
        self.cache_ttl = max(0, cache_ttl)
        self.gate = gate or UpstreamGate()
        self._lock = threading.Lock()
        self._inflight: dict[tuple[str, int], threading.Event] = {}
        self._results: dict[tuple[str, int], tuple[float, dict]] = {}

    def get(self, code: str, scale: int = 5, limit: int = 240) -> dict:
        code = normalize_code(code)
        key = (code, scale)
        now = time.monotonic()
        with self._lock:
            memory = self._results.get(key)
            if memory and now - memory[0] <= self.cache_ttl:
                return dict(memory[1])

        cached = self.runtime.load_minute(code, scale)
        if (
            cached["rows"]
            and cached["fetched_at"] is not None
            and time.time() - cached["fetched_at"] <= self.cache_ttl
        ):
            result = {
                "rows": cached["rows"],
                "stale": False,
                "cached": True,
                "error": None,
            }
            with self._lock:
                self._results[key] = (now, result)
            return dict(result)

        owner = False
        with self._lock:
            event = self._inflight.get(key)
            if event is None:
                event = threading.Event()
                self._inflight[key] = event
                owner = True
        if not owner:
            event.wait(timeout=20)
            with self._lock:
                result = self._results.get(key)
                if result:
                    return dict(result[1])
            cached = self.runtime.load_minute(code, scale)
            if cached["rows"]:
                return {
                    "rows": cached["rows"],
                    "stale": True,
                    "cached": True,
                    "error": "并发刷新未返回新数据，使用最近缓存。",
                }
            raise RuntimeError("minute request did not produce a result")

        try:
            try:
                with self.gate:
                    rows = self.provider.fetch(code, scale=scale, limit=limit)
                self.runtime.upsert_minute(rows)
                result = {
                    "rows": rows,
                    "stale": False,
                    "cached": False,
                    "error": None,
                }
            except Exception as exc:
                cached = self.runtime.load_minute(code, scale)
                if not cached["rows"]:
                    raise
                result = {
                    "rows": cached["rows"],
                    "stale": True,
                    "cached": True,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            with self._lock:
                self._results[key] = (time.monotonic(), result)
            return dict(result)
        finally:
            with self._lock:
                self._inflight.pop(key, None)
                event.set()
