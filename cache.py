from datetime import datetime, timedelta

CACHE = {}

def get_cached_url(channel: str):
    entry = CACHE.get(channel)
    if not entry:
        return None
    if entry["expires_at"] < datetime.utcnow():
        return None
    entry["requests"] = entry.get("requests", 0) + 1
    return entry

def set_cached_url(channel: str, url: str, ttl: int = 21600):
    now = datetime.utcnow()
    CACHE[channel] = {
        "url": url,
        "cached_at": now,
        "expires_at": now + timedelta(seconds=ttl),
        "requests": 0
    }
