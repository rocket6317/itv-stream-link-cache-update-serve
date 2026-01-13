import httpx
import os
import json
import logging
from fastapi import HTTPException
from change_log import log_change

logger = logging.getLogger("uvicorn")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
    'Accept': 'application/vnd.itv.online.playlist.sim.v3+json',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.itv.com/',
    'Origin': 'https://www.itv.com',
    'Content-Type': 'application/json',
}

def get_cookies_and_user_id():
    """Build cookies from environment variables and extract user ID from session."""
    cookies = {}
    user_id = None
    access_token = None

    # Read direct user ID and access token from environment (simpler approach)
    user_id = os.getenv('ITV_USER_ID')
    access_token = os.getenv('ITV_ACCESS_TOKEN')

    if user_id:
        logger.info(f"Using ITV_USER_ID from environment: {user_id}")
    if access_token:
        logger.info("Using ITV_ACCESS_TOKEN from environment")

    # Read any additional cookies (supports both old and new naming)
    for key, value in os.environ.items():
        if key.startswith('ITV_COOKIE_'):
            cookie_name = key.replace('ITV_COOKIE_', '')
            cookies[cookie_name] = value
        elif key == 'ITV_COOKIE_CONSENT':
            cookies['Itv.cck'] = value
        elif key == 'ITV_COOKIE_CLIENT_ID':
            cookies['Itv.Cid'] = value

    # If no user ID or access token, try to parse from Itv.Session cookie
    if not user_id or not access_token:
        if 'Itv.Session' in cookies:
            try:
                # The value might be wrapped in quotes in .env, strip them
                clean_value = cookies['Itv.Session'].strip().strip('"').strip("'")
                session_data = json.loads(clean_value)
                if 'tokens' in session_data and 'content' in session_data['tokens']:
                    content = session_data['tokens']['content']
                    if not user_id:
                        user_id = content.get('sub') or content.get('accountProfileIdInUse', '').replace('_0', '')
                    if not access_token:
                        access_token = content.get('access_token')
                    logger.info(f"Extracted user ID from session: {user_id}")
                    if access_token:
                        logger.info("Extracted access token from session")
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Could not parse Itv.Session cookie as JSON: {e}")

    # Legacy fallback
    if not cookies:
        legacy_cookie = os.getenv('ITV_SESSION_COOKIE')
        if legacy_cookie:
            cookies['SyrenisCookieFormConsent_Itv.Session'] = legacy_cookie

    return cookies, user_id, access_token

def build_request_data(user_id=None, access_token=None):
    """Build the request data payload with user ID and token (matches browser structure)."""
    # Use actual user ID from session, or fallback to generic UUID
    itv_user_id = user_id or "{4f129513-1f5b-4dc9-8a2a-b6434e93c938}"

    data = {
        "client": {
            "version": "4.1",
            "id": "browser",
            "supportsAdPods": True,
            "service": "itv.x",
            "appversion": "2.443.4",
            "ssaiClientSdkVersion": "3",
            "ssaiExtraParams": {}
        },
        "device": {
            "manufacturer": "Chrome",
            "model": "143.0.0.0",
            "os": {
                "name": "macOS",
                "version": "10.15.7",
                "type": "desktop"
            },
            "deviceGroup": "dotcom"
        },
        "user": {
            "token": access_token or ""
        },
        "variantAvailability": {
            "player": "dash",
            "featureset": {
                "min": ["mpeg-dash", "widevine"],
                "max": ["mpeg-dash", "widevine"]
            },
            "platformTag": "dotcom",
            "drm": {
                "system": "widevine",
                "maxSupported": "L3"
            }
        }
    }
    return data

async def fetch_stream_url(channel: str) -> str:
    cookies, user_id, access_token = get_cookies_and_user_id()

    if not access_token:
        raise HTTPException(
            status_code=500,
            detail="No ITV access token configured. Please add ITV_ACCESS_TOKEN to your .env file."
        )

    # Build request data with the access token
    request_data = build_request_data(user_id, access_token)

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            response = await client.post(
                f"https://simulcast.itv.com/playlist/itvonline/{channel}",
                headers=HEADERS,
                cookies=cookies,
                json=request_data,
            )
            logger.info(f"Response status: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"Response body: {response.text[:500]}")
                log_change('url_error', channel, {'status': response.status_code, 'body': response.text[:500]})
            response.raise_for_status()
            url = response.json()['Playlist']['Video']['VideoLocations'][0]['Url']
            log_change('url_refresh', channel, {'url': url})  # Log full URL
            return url
        except Exception as e:
            logger.error(f"Failed to fetch stream URL: {e}")
            log_change('url_error', channel, {'error': str(e)})
            raise HTTPException(status_code=502, detail=f"Failed to fetch stream URL: {e}")
