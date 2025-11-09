import time
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

_cache = {}

def get_cached_url(channel: str) -> str | None:
    entry = _cache.get(channel)
    if entry:
        url, expires_at = entry
        if time.time() < expires_at:
            logger.info(f"[CACHE HIT] Channel: {channel}")
            return url
        else:
            logger.info(f"[CACHE EXPIRED] Channel: {channel}")
            del _cache[channel]
    else:
        logger.info(f"[CACHE MISS] Channel: {channel}")
    return None

def set_cached_url(channel: str, url: str, ttl: int = 3600):  # 1 hour TTL
    logger.info(f"[CACHE SET] Channel: {channel} | TTL: {ttl}s")
    _cache[channel] = (url, time.time() + ttl)
