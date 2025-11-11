from datetime import datetime, timedelta

CACHE = {}
RECENT_REQUESTS = {}  # (channel, ip) → timestamp

def get_cached_url(channel: str, ip: str = None):
    entry = CACHE.get(channel)
    if not entry or entry["expires_at"] < datetime.utcnow():
        return None

    if ip:
        key = (channel, ip)
        now = datetime.utcnow()
        last = RECENT_REQUESTS.get(key)
        if not last or (now - last).total_seconds() > 2:  # ⏱️ 2-second window
            entry["requests"] = entry.get("requests", 0) + 1
            RECENT_REQUESTS[key] = now

    return entry

def set_cached_url(channel: str, url: str, ttl: int = 21600):
    now = datetime.utcnow()
    CACHE[channel] = {
        "url": url,
        "cached_at": now,
        "expires_at": now + timedelta(seconds=ttl),
        "requests": 0
    }

def peek_cached_entry(channel: str):
    entry = CACHE.get(channel)
    if not entry:
        return None
    if entry["expires_at"] < datetime.utcnow():
        return None
    return entry
