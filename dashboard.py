import time
import logging
import difflib
from datetime import datetime
from cache import get_cached_meta

logger = logging.getLogger(__name__)

latest_links = {}
link_history = {}

def record_link(channel: str, new_url: str):
    current_url = latest_links.get(channel)
    if current_url != new_url:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        logger.info(f"[LINK CHANGE] Channel: {channel} | Time: {timestamp}")
        latest_links[channel] = new_url
        link_history.setdefault(channel, []).append({
            "url": new_url,
            "timestamp": timestamp
        })

def highlight_diff(old: str, new: str) -> str:
    diff = difflib.ndiff(old, new)
    result = ""
    for part in diff:
        if part.startswith("+ "):
            result += f"<b style='color:red'>{part[2:]}</b>"
        elif part.startswith("  "):
            result += part[2:]
    return result

def get_dashboard_data():
    data = {
        "latest": latest_links,
        "history": {},
        "diffs": {},
        "counts": {},
        "elapsed": {},
        "expiry": {},
        "validity": {},
        "requests": {},
        "expiry_str": {}
    }
    now = datetime.now()
    for channel, history in link_history.items():
        data["history"][channel] = history
        data["counts"][channel] = len(history)

        last_time = datetime.strptime(history[-1]["timestamp"], "%Y-%m-%d %H:%M:%S")
        delta = now - last_time
        hours, remainder = divmod(delta.total_seconds(), 3600)
        minutes, _ = divmod(remainder, 60)
        data["elapsed"][channel] = f"{int(hours)}h {int(minutes)}m ago"

        if len(history) >= 2:
            old = history[-2]["url"]
            new = history[-1]["url"]
            data["diffs"][channel] = highlight_diff(old, new)
        else:
            data["diffs"][channel] = f"<b>{history[-1]['url']}</b>"

        meta = get_cached_meta(channel)
        data["expiry"][channel] = meta.get("expiry", 0)
        data["validity"][channel] = meta.get("validity", 0)
        data["requests"][channel] = meta.get("requests", 0)
        if meta.get("expiry"):
            dt = datetime.fromtimestamp(meta["expiry"])
            data["expiry_str"][channel] = dt.strftime("%a %d %b %Y %H:%M")
        else:
            data["expiry_str"][channel] = "Unknown"
    return data
