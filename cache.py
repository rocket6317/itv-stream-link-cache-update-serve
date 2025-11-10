from datetime import datetime
import re

# In-memory cache store
cache_store = {}

def extract_expiry(url):
    match = re.search(r"[?&]exp=(\d+)", url)
    if match:
        return int(match.group(1))
    # Fallback: assume 1 hour validity if no exp= found
    return int(datetime.utcnow().timestamp()) + 3600

def set_cached_url(channel, url):
    expiry = extract_expiry(url)
    now = int(datetime.utcnow().timestamp())
    validity = expiry - now
    cache_store[channel] = {
        "url": url,
        "expiry": expiry,
        "validity": validity
    }

def get_cached_url(channel):
    entry = cache_store.get(channel)
    if entry and entry["expiry"] > int(datetime.utcnow().timestamp()):
        return entry["url"]
    return None

def get_cached_meta(channel):
    return cache_store.get(channel, {})
