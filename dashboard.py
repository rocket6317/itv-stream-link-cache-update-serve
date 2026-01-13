import os
import base64
import json
from datetime import timedelta, datetime, timezone
from cache import peek_cached_entry

REFRESH_INTERVAL = int(os.getenv("REFRESH_INTERVAL", "21300"))
CHANNELS = ["ITV", "ITV2", "ITV3", "ITV4", "ITVBe"]

def extract_jwt_expiration(url):
    """Extract JWT expiration time from URL."""
    try:
        # JWT is embedded in URL after /jwt/
        if '/jwt/' in url:
            jwt_part = url.split('/jwt/')[1].split('?')[0].split('#')[0]
            # Split JWT into parts: header.payload.signature
            parts = jwt_part.split('.')
            if len(parts) >= 2:
                # Decode payload (second part)
                payload = parts[1]
                # Add padding if needed
                padding = 4 - len(payload) % 4
                if padding != 4:
                    payload += '=' * padding
                decoded = base64.urlsafe_b64decode(payload)
                data = json.loads(decoded)
                if 'exp' in data:
                    # exp is Unix timestamp
                    return datetime.fromtimestamp(data['exp'], tz=timezone.utc)
        return None
    except Exception:
        return None

def get_dashboard_data():
    data = {"streams": []}
    for channel in CHANNELS:
        entry = peek_cached_entry(channel)
        if entry:
            next_refresh = entry["cached_at"] + timedelta(seconds=REFRESH_INTERVAL)
            url = entry["url"]
            jwt_expiration = extract_jwt_expiration(url)

            # Calculate URL age
            url_age = None
            url_age_hours = None
            if jwt_expiration:
                # Get cached_at as timezone-aware
                cached_at_utc = entry["cached_at"].replace(tzinfo=timezone.utc)
                now_utc = datetime.now(timezone.utc)

                # Calculate total lifespan (cached to expiration)
                total_lifespan = (jwt_expiration - cached_at_utc).total_seconds()

                # Calculate elapsed time since cached
                elapsed = (now_utc - cached_at_utc).total_seconds()

                # Calculate remaining time
                remaining = (jwt_expiration - now_utc).total_seconds()

                # Calculate percentage used
                if total_lifespan > 0:
                    percent_used = (elapsed / total_lifespan) * 100
                else:
                    percent_used = 0

                url_age = {
                    "cached_at": cached_at_utc,
                    "expires_at": jwt_expiration,
                    "total_hours": total_lifespan / 3600,
                    "elapsed_hours": elapsed / 3600,
                    "remaining_hours": remaining / 3600,
                    "percent_used": min(percent_used, 100),
                    "is_expired": remaining < 0
                }

            data["streams"].append({
                "channel": channel,
                "cached_at": entry["cached_at"],
                "expires_at": entry["expires_at"],
                "next_refresh_at": next_refresh,
                "requests": entry.get("requests", 0),
                "url": url,
                "jwt_expiration": jwt_expiration,
                "url_age": url_age
            })
    return data
