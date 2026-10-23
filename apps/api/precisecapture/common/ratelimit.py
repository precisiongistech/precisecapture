"""Fixed-window rate limits on the cache. `rate` is "<count>/<seconds>" from settings."""

import hashlib

from django.core.cache import cache

from precisecapture.common.errors import ProblemException


class RateLimited(ProblemException):
    status = 429
    slug = "rate-limited"
    title = "Too many requests"


def parse_rate(rate: str) -> tuple[int, int]:
    count, seconds = rate.split("/")
    return int(count), int(seconds)


def _key(scope: str, subject: str) -> str:
    digest = hashlib.sha256(subject.encode()).hexdigest()[:32]
    return f"rl:{scope}:{digest}"


def hit(scope: str, subject: str, rate: str) -> None:
    """Record one hit; raise RateLimited when the window's count is exceeded."""
    limit, window = parse_rate(rate)
    key = _key(scope, subject)
    added = cache.add(key, 1, timeout=window)
    count = 1 if added else cache.incr(key)
    if count > limit:
        raise RateLimited(f"Too many attempts. Try again in up to {window} seconds.")


def reset(scope: str, subject: str) -> None:
    cache.delete(_key(scope, subject))
