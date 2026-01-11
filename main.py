import asyncio
import logging
import os
from pathlib import Path
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
    from change_log import get_logs, get_token_history, get_url_history
    CHANGE_LOG_AVAILABLE = True
except ImportError:
    CHANGE_LOG_AVAILABLE = False
    def get_logs(limit=100): return []
    def get_token_history(): return None
    def get_url_history(channel=None): return []

app = FastAPI()
templates = Jinja2Templates(directory="templates")
security = HTTPBasic()
logger = logging.getLogger("uvicorn")

load_dotenv("stack.env")
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

@app.on_event("startup")
async def startup_event():
    # Start file watcher for stack.env
    env_file_path = Path("/app/stack.env")
    if env_file_path.exists():
        logger.info(f"[STARTUP] Watching {env_file_path} for changes...")
        asyncio.create_task(watch_env_file(env_file_path))

    # Pre-fetch channels
    for channel in CHANNELS:
        try:
            url = await fetch_stream_url(channel)
            set_cached_url(channel, url)
            logger.info(f"[STARTUP] Cached {channel}")
        except Exception as e:
            logger.warning(f"[STARTUP ERROR] {channel}: {e}")
    asyncio.create_task(auto_refresh_loop())

async def watch_env_file(env_file_path: Path):
    """Watch for file modifications and reload environment."""
    last_mtime = env_file_path.stat().st_mtime

    while True:
        try:
            current_mtime = env_file_path.stat().st_mtime
            if current_mtime != last_mtime:
                logger.info(f"[FILE WATCH] stack.env modified, reloading...")

                # Reload environment
                from dotenv import load_dotenv
                load_dotenv("stack.env", override=True)

                # Clear cache
                from cache import CACHE
                old_size = len(CACHE)
                CACHE.clear()

                # Log the change
                if CHANGE_LOG_AVAILABLE:
                    from change_log import log_change
                    log_change('token_refresh', 'ALL', {
                        'trigger': 'auto_file_watch',
                        'cache_cleared': old_size
                    })

                logger.info(f"[FILE WATCH] Environment reloaded, cache cleared ({old_size} entries)")
                last_mtime = current_mtime

                # Test new token
                try:
                    test_url = await fetch_stream_url("ITV")
                    logger.info(f"[FILE WATCH] New token validated successfully")
                except Exception as e:
                    logger.error(f"[FILE WATCH] New token failed validation: {e}")

            await asyncio.sleep(2)

        except Exception as e:
            logger.error(f"[FILE WATCH] Error watching file: {e}")
            await asyncio.sleep(5)

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
