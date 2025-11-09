from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from cache import get_cached_url, set_cached_url
from client import fetch_stream_url

app = FastAPI()

@app.get("/itvx")
async def redirect_itv(request: Request):
    channel = request.query_params.get("channel", "ITV")
    cached_url = get_cached_url(channel)
    if cached_url:
        return RedirectResponse(cached_url)

    stream_url = await fetch_stream_url(channel)
    set_cached_url(channel, stream_url)
    return RedirectResponse(stream_url)
