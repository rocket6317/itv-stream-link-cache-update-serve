import asyncio
import logging
import os
from pathlib import Path
from logging.handlers import RotatingFileHandler
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.status import HTTP_401_UNAUTHORIZED
from dotenv import load_dotenv
from dashboard import get_dashboard_data
from cache import get_cached_url, set_cached_url, peek_cached_entry
from client import fetch_stream_url

# Try to import change_log, handle if not available
try:
    from change_log import get_logs, get_token_history, get_url_history, analyze_url_changes
    CHANGE_LOG_AVAILABLE = True
except ImportError:
    CHANGE_LOG_AVAILABLE = False
    def get_logs(limit=100): return []
    def get_token_history(): return None
    def get_url_history(channel=None): return []
    def analyze_url_changes(): return None

# Try to import event_tracker and pattern_analyzer
try:
    from event_tracker import get_events, get_event_stats, log_event
    from pattern_analyzer import generate_recommendations, get_summary_dashboard
    EVENT_TRACKER_AVAILABLE = True
except ImportError:
    EVENT_TRACKER_AVAILABLE = False
    def get_events(*args, **kwargs): return []
    def get_event_stats(*args, **kwargs): return {}
    def generate_recommendations(): return {}
    def get_summary_dashboard(): return {}
    def log_event(*args, **kwargs): pass

app = FastAPI()
templates = Jinja2Templates(directory="templates")
security = HTTPBasic()
logger = logging.getLogger("uvicorn")

# Setup file logging for uvicorn
LOG_DIR = Path("/app/logs")
LOG_DIR.mkdir(exist_ok=True)

uvicorn_logger = logging.getLogger("uvicorn")
uvicorn_logger.setLevel(logging.INFO)

file_handler = RotatingFileHandler(
    LOG_DIR / "uvicorn.log",
    maxBytes=10*1024*1024,
    backupCount=5
)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(levelname)s - %(message)s'
))
uvicorn_logger.addHandler(file_handler)

# Custom Jinja2 filter for event styling
def event_class_filter(event_type: str) -> str:
    """Map event types to CSS classes for styling."""
    if event_type in ['script_success', 'token_extracted', 'token_updated', 'container_restarted']:
        return 'success'
    elif event_type in ['chrome_timeout', 'page_timeout', 'token_failed', 'chrome_failed']:
        return 'error'
    elif event_type in ['token_info']:
        return 'info'
    else:
        return 'warning'

# Register the filter with Jinja2
import jinja2
templates.env.filters['event_class'] = event_class_filter

load_dotenv("/app/stack.env")
USERNAME = os.getenv("DASHBOARD_USER")
PASSWORD = os.getenv("DASHBOARD_PASS")
REFRESH_INTERVAL = int(os.getenv("REFRESH_INTERVAL", "21300"))
CHANNELS = ["ITV", "ITV2", "ITV3", "ITV4", "ITVBe"]

def check_auth(credentials: HTTPBasicCredentials):
    if credentials.username != USERNAME or credentials.password != PASSWORD:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED)

from fastapi import Request

@app.get("/itvx")
async def redirect_itv(channel: str, request: Request):
    ip = request.client.host
    entry = get_cached_url(channel, ip)
    if entry:
        return RedirectResponse(entry["url"], status_code=302)
    raise HTTPException(status_code=503, detail="Stream not ready or expired")

@app.get("/dashboard")
async def dashboard(
    request: Request,
    credentials: HTTPBasicCredentials = Depends(security)
):
    check_auth(credentials)
    data = get_dashboard_data()
    return templates.TemplateResponse("dashboard.html", {"request": request, "data": data})

@app.get("/dashboard/json")
async def dashboard_json(credentials: HTTPBasicCredentials = Depends(security)):
    check_auth(credentials)
    return get_dashboard_data()

@app.get("/raw")
async def raw_manifest():
    return RedirectResponse("https://example.com/static.mpd")

@app.get("/health")
async def health_check():
    """Health check endpoint that also verifies token validity."""
    try:
        # Try to fetch a stream URL to verify token is valid
        url = await fetch_stream_url("ITV")
        return {
            "status": "healthy",
            "token_valid": True,
            "test_stream": url[:100] + "..."
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "token_valid": False,
            "error": str(e)
        }, 503

@app.post("/admin/reload-token")
async def reload_token(
    credentials: HTTPBasicCredentials = Depends(security)
):
    """Manually trigger a token reload from environment."""
    check_auth(credentials)

    # Reload environment variables
    from dotenv import load_dotenv
    load_dotenv("stack.env", override=True)

    # Clear the cache to force re-fetch with new token
    from cache import CACHE
    CACHE.clear()

    return {"status": "success", "message": "Token reloaded from environment"}

@app.get("/admin/token-status")
async def token_status(credentials: HTTPBasicCredentials = Depends(security)):
    """Get current token status including expiration time."""
    check_auth(credentials)

    import base64
    import json
    from datetime import datetime

    token = os.getenv('ITV_ACCESS_TOKEN', '')
    if not token:
        return {'valid': False, 'error': 'No token found'}

    try:
        parts = token.split('.')
        if len(parts) >= 2:
            payload = parts[1]
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += '=' * padding
            decoded = base64.urlsafe_b64decode(payload)
            data = json.loads(decoded)

            if 'exp' in data:
                exp_timestamp = data['exp']
                exp_datetime = datetime.fromtimestamp(exp_timestamp)
                now = datetime.utcnow()
                hours_remaining = (exp_datetime - now).total_seconds() / 3600

                return {
                    'valid': True,
                    'expires_at': exp_datetime.isoformat(),
                    'hours_remaining': round(hours_remaining, 2),
                    'warning': hours_remaining < 6
                }
    except Exception as e:
        return {'valid': False, 'error': f'Failed to decode token: {str(e)}'}

    return {'valid': True, 'warning': 'Unknown expiration'}

# Token refresh restart marker file
# Used to detect if container was just restarted by automation script
# Marker is created in /app/logs which is a mounted volume from host
RESTART_MARKER_FILE = Path("/app/logs/.automation_restart")
# If marker exists and is younger than this many seconds, skip startup token refresh
RESTART_MARKER_TTL = 300  # 5 minutes


def should_skip_startup_refresh():
    """Check if container was just restarted by automation script.

    Returns True if the restart marker file exists and is recent.
    This prevents a refresh loop when automation script restarts container.
    """
    if not RESTART_MARKER_FILE.exists():
        return False

    try:
        import time
        # Check file age
        file_age = time.time() - RESTART_MARKER_FILE.stat().st_mtime
        if file_age < RESTART_MARKER_TTL:
            logger.info(f"[STARTUP] Skipping token refresh - automation restart detected ({file_age:.0f}s ago)")
            return True
        else:
            # Marker is old, remove it
            RESTART_MARKER_FILE.unlink(missing_ok=True)
            return False
    except Exception as e:
        logger.warning(f"[STARTUP] Error checking restart marker: {e}")
        return False


def clear_restart_marker():
    """Remove the restart marker file (called after successful startup)."""
    try:
        RESTART_MARKER_FILE.unlink(missing_ok=True)
    except Exception:
        pass


@app.on_event("startup")
async def startup_event():
    # Log service startup
    if EVENT_TRACKER_AVAILABLE:
        log_event('startup', {'channels': CHANNELS})

    # Check if this is an automation restart (skip refresh to prevent loops)
    is_automation_restart = should_skip_startup_refresh()

    # Only fetch URLs if token is valid, not an automation restart
    if not is_automation_restart:
        # Pre-fetch channels
        for channel in CHANNELS:
            try:
                url = await fetch_stream_url(channel)
                set_cached_url(channel, url)
                logger.info(f"[STARTUP] Cached {channel}")
            except Exception as e:
                logger.warning(f"[STARTUP ERROR] {channel}: {e}")
    else:
        logger.info("[STARTUP] Skipping channel pre-fetch after automation restart")

    # Clear the marker after startup checks complete
    clear_restart_marker()

    asyncio.create_task(auto_refresh_loop())
    asyncio.create_task(log_scanner_loop())


async def log_scanner_loop():
    """Periodically scan uvicorn logs for error patterns."""
    while True:
        try:
            if EVENT_TRACKER_AVAILABLE:
                from log_parser import scan_and_log_errors
                count = scan_and_log_errors()
                if count and count > 0:
                    logger.info(f"[LOG SCANNER] Found {count} HTTP errors in last hour")
        except Exception as e:
            logger.error(f"[LOG SCANNER] Error: {e}")
        await asyncio.sleep(3600)  # Run every hour

async def auto_refresh_loop():
    while True:
        for channel in CHANNELS:
            try:
                url = await fetch_stream_url(channel)
                set_cached_url(channel, url)
                logger.info(f"[AUTO REFRESH] {channel} updated.")
            except Exception as e:
                logger.warning(f"[AUTO REFRESH ERROR] {channel}: {e}")
        await asyncio.sleep(REFRESH_INTERVAL)

@app.get("/logs")
async def view_logs(
    request: Request,
    credentials: HTTPBasicCredentials = Depends(security)
):
    """View recent change logs."""
    check_auth(credentials)
    try:
        logs = get_logs(100)
        return templates.TemplateResponse("logs.html", {"request": request, "logs": logs})
    except Exception as e:
        logger.error(f"Error in /logs: {e}")
        return templates.TemplateResponse("logs.html", {"request": request, "logs": []})

@app.get("/logs/json")
async def view_logs_json(credentials: HTTPBasicCredentials = Depends(security)):
    """Get logs as JSON."""
    check_auth(credentials)
    return get_logs(200)

@app.get("/stats")
async def view_stats(
    request: Request,
    credentials: HTTPBasicCredentials = Depends(security)
):
    """View statistics about token and URL changes."""
    check_auth(credentials)
    try:
        token_stats = get_token_history()
        channel_stats = {}
        for ch in CHANNELS:
            try:
                history = get_url_history(ch)
                channel_stats[ch] = history[-10:] if history else []
            except Exception:
                channel_stats[ch] = []
        return templates.TemplateResponse("stats.html", {
            "request": request,
            "token_stats": token_stats,
            "channel_stats": channel_stats,
            "channels": CHANNELS
        })
    except Exception as e:
        logger.error(f"Error in /stats: {e}")
        return templates.TemplateResponse("stats.html", {
            "request": request,
            "token_stats": None,
            "channel_stats": {ch: [] for ch in CHANNELS},
            "channels": CHANNELS
        })

@app.get("/stats/json")
async def view_stats_json(credentials: HTTPBasicCredentials = Depends(security)):
    """Get stats as JSON."""
    check_auth(credentials)
    return {
        'token': get_token_history(),
        'channels': {ch: get_url_history(ch)[-10:] for ch in CHANNELS}
    }

@app.get("/debug")
async def debug_info():
    """Debug endpoint to check if new files are loaded."""
    import os
    return {
        "change_log_exists": os.path.exists('/app/change_log.py'),
        "templates_exist": os.path.exists('/app/templates/logs.html'),
        "files_in_app": os.listdir('/app') if os.path.exists('/app') else [],
    }

def get_token_refresh_logs(limit=100):
    """Read token refresh logs from the log file."""
    import json
    log_file = '/home/dietpi/itv/token_refresh.log'

    if not os.path.exists(log_file):
        return []

    try:
        with open(log_file, 'r') as f:
            logs = json.load(f)
        # Return last N entries, most recent first
        return logs[-limit:][::-1]
    except Exception as e:
        logger.error(f"Error reading token refresh logs: {e}")
        return []

@app.get("/token-logs")
async def view_token_logs(
    request: Request,
    credentials: HTTPBasicCredentials = Depends(security)
):
    """View token refresh logs."""
    check_auth(credentials)
    logs = get_token_refresh_logs(200)
    return templates.TemplateResponse("token_logs.html", {"request": request, "logs": logs})

@app.get("/token-logs/json")
async def view_token_logs_json(credentials: HTTPBasicCredentials = Depends(security)):
    """Get token refresh logs as JSON."""
    check_auth(credentials)
    return get_token_refresh_logs(500)

@app.get("/url-analysis")
async def url_analysis(credentials: HTTPBasicCredentials = Depends(security)):
    """Analyze URL changes to determine if URLs change independently of tokens."""
    check_auth(credentials)
    if not CHANGE_LOG_AVAILABLE:
        return {"error": "Change log module not available"}
    return analyze_url_changes()


# New pattern analysis endpoints
@app.get("/patterns")
async def view_patterns(
    request: Request,
    credentials: HTTPBasicCredentials = Depends(security)
):
    """View failure patterns and recommendations."""
    check_auth(credentials)
    if not EVENT_TRACKER_AVAILABLE:
        return templates.TemplateResponse("patterns.html", {
            "request": request,
            "error": "Event tracker module not available"
        })
    analysis = generate_recommendations()
    return templates.TemplateResponse("patterns.html", {
        "request": request,
        "analysis": analysis,
        "available": True
    })


@app.get("/patterns/json")
async def view_patterns_json(credentials: HTTPBasicCredentials = Depends(security)):
    """Get pattern analysis as JSON."""
    check_auth(credentials)
    if not EVENT_TRACKER_AVAILABLE:
        return {"error": "Event tracker module not available"}
    return generate_recommendations()


@app.get("/events")
async def view_events(
    request: Request,
    credentials: HTTPBasicCredentials = Depends(security),
    event_type: str = None,
    hours: int = 24
):
    """View raw events with filtering."""
    check_auth(credentials)
    if not EVENT_TRACKER_AVAILABLE:
        return templates.TemplateResponse("events.html", {
            "request": request,
            "events": [],
            "filter_type": event_type,
            "hours": hours,
            "error": "Event tracker module not available"
        })
    events = get_events(event_type=event_type, hours_ago=hours)
    return templates.TemplateResponse("events.html", {
        "request": request,
        "events": events,
        "filter_type": event_type,
        "hours": hours,
        "available": True
    })


@app.get("/events/json")
async def view_events_json(
    credentials: HTTPBasicCredentials = Depends(security),
    event_type: str = None,
    hours: int = 24
):
    """Get events as JSON."""
    check_auth(credentials)
    if not EVENT_TRACKER_AVAILABLE:
        return {"error": "Event tracker module not available"}
    return get_events(event_type=event_type, hours_ago=hours)


@app.get("/events/stats")
async def view_events_stats(
    credentials: HTTPBasicCredentials = Depends(security),
    hours: int = 24
):
    """Get event statistics."""
    check_auth(credentials)
    if not EVENT_TRACKER_AVAILABLE:
        return {"error": "Event tracker module not available"}
    return get_event_stats(hours_ago=hours)
