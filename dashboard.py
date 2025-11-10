from cache import get_cached_meta
import time
import os

REFRESH_INTERVAL = int(os.getenv("REFRESH_INTERVAL", "21300"))

def get_dashboard_data():
    now = int(time.time())
    next_refresh = now + REFRESH_INTERVAL
    data = []
    for channel in ["ITV", "ITV2", "ITV3", "ITV4", "ITVBe"]:
        meta = get_cached_meta(channel)
        if meta:
            expires_in = meta["expiry"] - now
            data.append({
                "channel": channel,
                "url": meta["url"],
                "cached_at": time.strftime("%H:%M:%S", time.localtime(meta["cached_at"])),
                "expires_at": time.strftime("%H:%M:%S", time.localtime(meta["expiry"])),
                "expires_in": f"{expires_in // 60} min",
                "next_refresh_at": time.strftime("%H:%M:%S", time.localtime(next_refresh)),
                "requests": meta["requests"]
            })
    return {"streams": data}
