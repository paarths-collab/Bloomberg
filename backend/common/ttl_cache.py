"""
Small thread-safe LRU + TTL cache with a hard size bound.

Several services cached results in plain dicts keyed by user-controlled strings (ticker, query, URL,
date range), so an unauthenticated client could grow process memory without limit. `TTLCache` caps the
number of entries (least recently used goes first, expired entries are dropped before live ones) and
expires entries after `ttl` seconds.

Expired entries are NOT removed on a normal `get`: they stay readable through `get_stale` until the
size bound or a newer `set` replaces them, which is what lets callers serve stale data during an
upstream outage.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Hashable, Optional, Tuple


class TTLCache:
    def __init__(
        self,
        maxsize: int = 512,
        ttl: float = 300.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.maxsize = max(1, int(maxsize))
        self.ttl = float(ttl)
        self._clock = clock
        self._lock = threading.Lock()
        self._data: "OrderedDict[Hashable, Tuple[float, Any]]" = OrderedDict()

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def __contains__(self, key: Hashable) -> bool:
        return self.get(key) is not None

    def get(self, key: Hashable, default: Any = None) -> Any:
        """Value for `key` if present and not expired, else `default`."""
        with self._lock:
            row = self._data.get(key)
            if row is None or self._clock() >= row[0]:
                return default
            self._data.move_to_end(key)
            return row[1]

    def get_stale(self, key: Hashable, default: Any = None) -> Any:
        """Value for `key` even if it has expired (still bounded by maxsize)."""
        with self._lock:
            row = self._data.get(key)
            if row is None:
                return default
            self._data.move_to_end(key)
            return row[1]

    def set(self, key: Hashable, value: Any, ttl: Optional[float] = None) -> None:
        with self._lock:
            now = self._clock()
            self._data[key] = (now + (self.ttl if ttl is None else float(ttl)), value)
            self._data.move_to_end(key)
            if len(self._data) > self.maxsize:
                for k in [k for k, (exp, _) in self._data.items() if exp <= now and k != key]:
                    del self._data[k]
                    if len(self._data) <= self.maxsize:
                        break
                while len(self._data) > self.maxsize:
                    self._data.popitem(last=False)  # least recently used

    def pop(self, key: Hashable, default: Any = None) -> Any:
        with self._lock:
            row = self._data.pop(key, None)
            return default if row is None else row[1]

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
