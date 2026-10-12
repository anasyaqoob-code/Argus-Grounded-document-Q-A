"""Per-user sliding-window rate limiting for expensive endpoints.

Runs in-process (single replica, single worker). No Redis, no external
state — just a dict of deques guarded by a lock. If Argus ever scales
horizontally, swap the store for Redis; the interface stays the same.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from typing import Callable

from fastapi import HTTPException, Request, status

from . import storage

logger = logging.getLogger("argus.rate_limit")

_WINDOW_SECONDS = 60
_HITS: dict[str, deque[float]] = defaultdict(deque)
_LOCK = threading.Lock()


def _check(user_id: str, limit: int, bucket: str) -> tuple[bool, int]:
    key = f"{bucket}:{user_id}"
    now = time.time()
    cutoff = now - _WINDOW_SECONDS

    with _LOCK:
        dq = _HITS[key]
        while dq and dq[0] < cutoff:
            dq.popleft()

        if len(dq) >= limit:
            retry_after = max(1, int(dq[0] + _WINDOW_SECONDS - now) + 1)
            return False, retry_after

        dq.append(now)
        return True, 0


def _record_hit(user_id: str, bucket: str, limit: int) -> None:
    try:
        storage.record_auth_event(user_id, f"rate_limit_hit:{bucket}")
    except Exception:
        logger.exception("Failed to record rate_limit_hit event")


def rate_limit(limit: int, bucket: str) -> Callable:
    """FastAPI dependency factory."""

    def dependency(request: Request) -> None:
        from .main import current_user

        user_id = current_user(request)
        allowed, retry_after = _check(user_id, limit, bucket)
        if not allowed:
            _record_hit(user_id, bucket, limit)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "rate_limited",
                    "bucket": bucket,
                    "limit": limit,
                    "window_seconds": _WINDOW_SECONDS,
                    "retry_after": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

    return dependency


limit_query = rate_limit(20, "query")
limit_image = rate_limit(5, "image")


__all__ = ["rate_limit", "limit_query", "limit_image"]