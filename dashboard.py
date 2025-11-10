from cache import CACHE
import time

def get_dashboard_data():
    data = []
    for channel, entry in CACHE.items():
        expires_in = int(entry["expires_at"] - time.time())
        data.append({
            "channel": channel,
            "url": entry["url"],
            "expires_in": f"{expires_in // 60} min",
            "expires_at": time.strftime("%H:%M:%S", time.localtime(entry["expires_at"]))
        })
    return {"streams": data}
