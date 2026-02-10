import httpx
import os
import json
import logging
import base64
from datetime import datetime, timezone
from fastapi import HTTPException
from change_log import log_change

# Try to import event_tracker, handle if not available
try:
    from event_tracker import log_event
    EVENT_TRACKER_AVAILABLE = True
except ImportError:
    EVENT_TRACKER_AVAILABLE = False
    def log_event(*args, **kwargs):
        pass  # Stub implementation

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

def get_token_age_hours(access_token):
    """Calculate token age in hours from JWT expiration claim.

    Returns:
        Token age in hours, or None if token is invalid
    """
    if not access_token:
        return None

    try:
        parts = access_token.split('.')
        if len(parts) >= 2:
            payload = parts[1]
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += '=' * padding
            decoded = base64.urlsafe_b64decode(payload)
            data = json.loads(decoded)

            if 'exp' in data:
                exp_timestamp = data['exp']
                now = datetime.now(timezone.utc).timestamp()
                hours_remaining = (exp_timestamp - now) / 3600

                # Estimate total token lifetime (usually ~24 hours for ITV)
                # and calculate current age
                estimated_lifetime_hours = 24
                age_hours = estimated_lifetime_hours - hours_remaining
                return max(0, age_hours)
    except (json.JSONDecodeError, ValueError, KeyError):
        pass

    return None


def extract_cdn(url):
    """Extract CDN provider from URL."""
    try:
        if 'akamai' in url.lower():
            return 'akamai'
        elif 'fastly' in url.lower():
            return 'fastly'
        elif 'cloudflare' in url.lower():
            return 'cloudflare'
        return 'unknown'
    except:
        return 'unknown'

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

    # Log fetch start
    if EVENT_TRACKER_AVAILABLE:
        log_event('url_fetch_start', {'channel': channel})

    if not access_token:
        if EVENT_TRACKER_AVAILABLE:
            log_event('url_fetch_error_other', {
                'channel': channel,
                'error': 'No token configured'
            }, severity='critical')
        raise HTTPException(
            status_code=500,
            detail="No ITV access token configured. Please add ITV_ACCESS_TOKEN to your .env file."
        )

    # Calculate token age
    token_age_hours = get_token_age_hours(access_token)

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

            # Handle different status codes with event logging
            if response.status_code == 401:
                error_details = {
                    'channel': channel,
                    'token_age_hours': token_age_hours,
                    'status': 401
                }
                if EVENT_TRACKER_AVAILABLE:
                    log_event('url_fetch_error_401', error_details, severity='error')
                logger.error(f"Response body: {response.text[:500]}")
                log_change('url_error', channel, {'status': 401, 'body': response.text[:500]})
                raise HTTPException(status_code=502, detail=f"ITV API returned 401 - token may be expired")

            elif response.status_code == 403:
                error_details = {
                    'channel': channel,
                    'token_age_hours': token_age_hours,
                    'status': 403
                }
                if EVENT_TRACKER_AVAILABLE:
                    log_event('url_fetch_error_403', error_details, severity='error')
                logger.error(f"Response body: {response.text[:500]}")
                log_change('url_error', channel, {'status': 403, 'body': response.text[:500]})
                raise HTTPException(status_code=502, detail=f"ITV API returned 403 - access forbidden")

            elif response.status_code == 502:
                if EVENT_TRACKER_AVAILABLE:
                    log_event('url_fetch_error_502', {
                        'channel': channel,
                        'token_age_hours': token_age_hours
                    }, severity='error')
                log_change('url_error', channel, {'status': 502})
                raise HTTPException(status_code=502, detail="ITV API returned 502 Bad Gateway")

            elif response.status_code == 503:
                if EVENT_TRACKER_AVAILABLE:
                    log_event('url_fetch_error_503', {
                        'channel': channel,
                        'token_age_hours': token_age_hours
                    }, severity='error')
                log_change('url_error', channel, {'status': 503})
                raise HTTPException(status_code=502, detail="ITV API returned 503 Service Unavailable")

            elif response.status_code != 200:
                if EVENT_TRACKER_AVAILABLE:
                    log_event('url_fetch_error_other', {
                        'channel': channel,
                        'status': response.status_code,
                        'token_age_hours': token_age_hours
                    }, severity='warning')
                logger.error(f"Response body: {response.text[:500]}")
                log_change('url_error', channel, {'status': response.status_code, 'body': response.text[:500]})
                response.raise_for_status()

            url = response.json()['Playlist']['Video']['VideoLocations'][0]['Url']

            # Log success with CDN info
            if EVENT_TRACKER_AVAILABLE:
                log_event('url_fetch_success', {
                    'channel': channel,
                    'token_age_hours': token_age_hours,
                    'cdn': extract_cdn(url)
                })

            log_change('url_refresh', channel, {'url': url})  # Log full URL
            return url

        except httpx.TimeoutException:
            if EVENT_TRACKER_AVAILABLE:
                log_event('url_fetch_error_timeout', {
                    'channel': channel,
                    'token_age_hours': token_age_hours
                }, severity='error')
            log_change('url_error', channel, {'error': 'timeout'})
            raise HTTPException(status_code=502, detail="ITV API request timed out")

        except httpx.RequestError as e:
            if EVENT_TRACKER_AVAILABLE:
                log_event('url_fetch_error_other', {
                    'channel': channel,
                    'error': str(e),
                    'error_type': 'RequestError',
                    'token_age_hours': token_age_hours
                }, severity='error')
            logger.error(f"Failed to fetch stream URL: {e}")
            log_change('url_error', channel, {'error': str(e)})
            raise HTTPException(status_code=502, detail=f"Failed to fetch stream URL: {e}")
