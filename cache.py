import time

_cache = {}

def get_cached_url(channel: str) -> str | None:
    entry = _cache.get(channel)
    if entry:
        url, expires_at = entry
        if time.time() < expires_at:
            return url
        else:
            del _cache[channel]
    return None

def set_cached_url(channel: str, url: str, ttl: int = 300):
    _cache[channel] = (url, time.time() + ttl)
