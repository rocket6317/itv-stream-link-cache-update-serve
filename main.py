import asyncio
import logging
import os
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.status import HTTP_401_UNAUTHORIZED
from dotenv import load_dotenv
from dashboard import get_dashboard_data
from cache import get_cached_url, set_cached_url
from client import fetch_stream_url

app = FastAPI()
templates = Jinja2Templates(directory="templates")
security = HTTPBasic()
logger = logging.getLogger("uvicorn")

load_dotenv("stack.env")
USERNAME = os.getenv("DASHBOARD_USER")
PASSWORD = os.getenv("DASHBOARD_PASS")
REFRESH_INTERVAL = int(os.getenv("REFRESH_INTERVAL", "21300"))  # default: 5h55m

CHANNELS = ["ITV", "ITV2", "ITV3", "ITV4", "ITVBe"]

def check_auth(credentials: HTTPBasicCredentials):
    if credentials.username != USERNAME or credentials.password != PASSWORD:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED)

@app.get("/itvx")
async def redirect_itv(channel: str):
    url = get_cached_url(channel)
    if not url:
        url = await fetch_stream_url(channel)
        set_cached_url(channel, url)
    return RedirectResponse(url)

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

@app.on_event("startup")
async def startup_event():
    for channel in CHANNELS:
        try:
            url = await fetch_stream_url(channel)
            set_cached_url(channel, url)
            logger.info(f"[STARTUP] Cached {channel}")
        except Exception as e:
            logger.warning(f"[STARTUP ERROR] {channel}: {e}")
    asyncio.create_task(auto_refresh_loop())

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
