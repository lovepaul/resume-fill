from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Callable

from fastapi import HTTPException, Request


class RateLimiter:
    def __init__(self, limits: dict[str, tuple[int, int]]) -> None:
        self._limits = limits
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def enforce(self, request: Request, scope: str, client_ip_resolver: Callable[[Request], str]) -> None:
        if scope not in self._limits:
            return
        max_requests, window_seconds = self._limits[scope]
        client_ip = client_ip_resolver(request)
        now = time.time()
        bucket_key = f"{scope}:{client_ip}"

        with self._lock:
            bucket = self._buckets[bucket_key]
            while bucket and bucket[0] <= now - window_seconds:
                bucket.popleft()
            if len(bucket) >= max_requests:
                retry_after = max(1, int(window_seconds - (now - bucket[0])))
                raise HTTPException(
                    status_code=429,
                    detail=f"请求过于频繁，请 {retry_after} 秒后重试",
                )
            bucket.append(now)

