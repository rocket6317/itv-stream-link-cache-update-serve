import os
from cache import CACHE

BASE_URL = os.getenv("BASE_URL", "https://example.com")
CHANNELS = ["ITV", "ITV2", "ITV3", "ITV4", "ITVBe"]

def get_dashboard_data():
    data = {"streams": []}
    for channel in CHANNELS:
        entry = CACHE.get(channel)
        if entry:
            data["streams"].append({
                "channel": channel,
                "cached_at": entry["cached_at"],
                "expires_at": entry["expires_at"],
                "next_refresh_at": entry["expires_at"],
                "requests": entry.get("requests", 0),
                "url": entry["url"]
            })
    return data
