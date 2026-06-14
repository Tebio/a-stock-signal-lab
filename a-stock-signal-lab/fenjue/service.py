from __future__ import annotations

import threading
import time
from collections.abc import Iterable
from typing import Protocol


MAIN_PREFIXES = ("600", "601", "603", "605", "000", "001", "002", "003")


class QuoteProvider(Protocol):
    def fetch(self, codes: list[str]) -> dict[str, dict]: ...


def normalize_code(value: str) -> str:
    digits = "".join(char for char in str(value) if char.isdigit())
    if len(digits) < 6:
        raise ValueError(f"invalid stock code: {value}")
    return digits[-6:]


def is_main_board(code: str) -> bool:
    return normalize_code(code).startswith(MAIN_PREFIXES)


class QuoteService:
    def __init__(self, provider: QuoteProvider, cache_ttl: float = 2):
        self.provider = provider
        self.cache_ttl = max(0, cache_ttl)
        self._lock = threading.Lock()
        self._cache: dict[tuple[str, ...], tuple[float, dict[str, dict]]] = {}
        self._inflight: dict[tuple[str, ...], threading.Event] = {}

    def get_quotes(self, values: Iterable[str]) -> dict:
        accepted = []
        rejected = []
        for value in values:
            code = normalize_code(value)
            target = accepted if is_main_board(code) else rejected
            if code not in target:
                target.append(code)
        key = tuple(sorted(accepted))
        if not key:
            return {"quotes": {}, "rejected": rejected, "cached": False}

        owner = False
        with self._lock:
            cached = self._cache.get(key)
            if cached and time.monotonic() - cached[0] <= self.cache_ttl:
                return {
                    "quotes": dict(cached[1]),
                    "rejected": rejected,
                    "cached": True,
                }
            event = self._inflight.get(key)
            if event is None:
                event = threading.Event()
                self._inflight[key] = event
                owner = True

        if not owner:
            event.wait(timeout=15)
            with self._lock:
                cached = self._cache.get(key)
                if cached:
                    return {
                        "quotes": dict(cached[1]),
                        "rejected": rejected,
                        "cached": True,
                    }
            raise RuntimeError("quote request did not produce a result")

        try:
            quotes = self.provider.fetch(list(key))
            with self._lock:
                self._cache[key] = (time.monotonic(), dict(quotes))
            return {"quotes": quotes, "rejected": rejected, "cached": False}
        finally:
            with self._lock:
                self._inflight.pop(key, None)
                event.set()

