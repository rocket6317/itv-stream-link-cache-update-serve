from datetime import datetime
import logging

logger = logging.getLogger(__name__)
cache_store = {}

CACHE_DURATION = 6 * 60 * 60  # 6 hours in seconds

def set_cached_url(channel, url):
    now = int(datetime.utcnow().timestamp())
    expiry = now + CACHE_DURATION
    cache_store[channel] = {
        "url": url,
        "expiry": expiry,
        "cached_at": now,
        "validity": CACHE_DURATION,
        "requests": 0
    }
    logger.info(f"[CACHE SET] {channel} | forced expiry: {expiry} | validity: {CACHE_DURATION}s")

def get_cached_url(channel):
    entry = cache_store.get(channel)
    now = int(datetime.utcnow().timestamp())
    if entry and entry["expiry"] > now:
        entry["requests"] += 1
        logger.info(f"[CACHE HIT] {channel} | count: {entry['requests']} | expires in {entry['expiry'] - now}s")
        return entry["url"]
    logger.info(f"[CACHE MISS] {channel}")
    return None

def get_cached_meta(channel):
    return cache_store.get(channel, {})
