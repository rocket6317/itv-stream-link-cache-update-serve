from cache import get_cached_meta
import time

def get_dashboard_data():
    data = []
    for channel in ["ITV", "ITV2", "ITV3", "ITV4", "ITVBe"]:
        meta = get_cached_meta(channel)
        if meta:
            expires_in = meta["expiry"] - int(time.time())
            data.append({
                "channel": channel,
                "url": meta["url"],
                "expires_in": f"{expires_in // 60} min",
                "expires_at": time.strftime("%H:%M:%S", time.localtime(meta["expiry"])),
                "requests": meta["requests"]
            })
    return {"streams": data}
