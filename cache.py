import time

_cache = {}

def get_cached_url(channel: str) -> str | None:
    entry = _cache.get(channel)
    if entry:
        url, expires_at = entry
        if time.time() < expires_at:
            print(f"[CACHE HIT] Channel: {channel}")
            return url
        else:
            print(f"[CACHE EXPIRED] Channel: {channel}")
            del _cache[channel]
    else:
        print(f"[CACHE MISS] Channel: {channel}")
    return None

def set_cached_url(channel: str, url: str, ttl: int = 300):
    print(f"[CACHE SET] Channel: {channel} | TTL: {ttl}s")
    _cache[channel] = (url, time.time() + ttl)
