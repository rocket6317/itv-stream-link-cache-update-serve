import os
from datetime import timedelta
from cache import get_cached_url

BASE_URL = os.getenv("BASE_URL", "https://example.com")
REFRESH_INTERVAL = int(os.getenv("REFRESH_INTERVAL", "21300"))
CHANNELS = ["ITV", "ITV2", "ITV3", "ITV4", "ITVBe"]

def get_dashboard_data():
    data = {"streams": []}
    for channel in CHANNELS:
        entry = get_cached_url(channel)
        if entry:
            next_refresh = entry["cached_at"] + timedelta(seconds=REFRESH_INTERVAL)
            data["streams"].append({
                "channel": channel,
                "cached_at": entry["cached_at"],
                "expires_at": entry["expires_at"],
                "next_refresh_at": next_refresh,
                "requests": entry.get("requests", 0),
                "url": entry["url"]
            })
    return data
