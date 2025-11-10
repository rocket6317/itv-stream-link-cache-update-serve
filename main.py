import os
import secrets
import logging
from fastapi import FastAPI, Request, Response, Depends, HTTPException, status
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from cache import get_cached_url, set_cached_url
from client import fetch_stream_url
from dashboard import record_link, get_dashboard_data

# ✅ Global logging config
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI()
templates = Jinja2Templates(directory="templates")
security = HTTPBasic()

USERNAME = os.environ["DASHBOARD_USER"]
PASSWORD = os.environ["DASHBOARD_PASS"]
CHANNELS = ["ITV", "ITV2", "ITV3", "ITV4", "ITVBe"]

def authenticate(credentials: HTTPBasicCredentials = Depends(security)):
    if not (
        secrets.compare_digest(credentials.username, USERNAME) and
        secrets.compare_digest(credentials.password, PASSWORD)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

@app.get("/itvx")
async def redirect_itv(request: Request):
    channel = request.query_params.get("channel", "ITV")
    if channel not in CHANNELS:
        raise HTTPException(status_code=400, detail="Invalid channel")

    cached_url = get_cached_url(channel)
    if cached_url:
        record_link(channel, cached_url)
        return RedirectResponse(cached_url)

    stream_url = await fetch_stream_url(channel)
    set_cached_url(channel, stream_url)
    record_link(channel, stream_url)
    return RedirectResponse(stream_url)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request, credentials: HTTPBasicCredentials = Depends(authenticate)):
    return templates.TemplateResponse("dashboard.html", {"request": request})

@app.get("/dashboard/json")
def dashboard_json(credentials: HTTPBasicCredentials = Depends(authenticate)):
    return get_dashboard_data()

@app.get("/raw")
async def serve_raw_manifest():
    manifest = """<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static">
  <!-- DASH manifest content -->
</MPD>"""
    return Response(content=manifest, media_type="text/plain")
