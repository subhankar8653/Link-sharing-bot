import os
import time
from urllib.parse import urlparse

from aiohttp import web
from .route import routes

_ORIGINS = {"ts": 0.0, "set": set()}


async def _allowed_origins() -> set:
    """Mini App ka frontend alag host par (Vercel/Blogspot) ho toh us origin ko API ki permission."""
    if time.time() - _ORIGINS["ts"] < 60:
        return _ORIGINS["set"]
    allowed = {o.strip().rstrip("/") for o in os.environ.get("MINIAPP_ORIGINS", "").split(",") if o.strip()}
    try:
        from plugins.miniapp import get_miniapp_settings
        url = (await get_miniapp_settings())["url"]
        if url:
            p = urlparse(url)
            allowed.add(f"{p.scheme}://{p.netloc}")
    except Exception:
        pass
    _ORIGINS.update(ts=time.time(), set=allowed)
    return allowed


@web.middleware
async def cors_middleware(request, handler):
    origin = request.headers.get("Origin")
    if not origin or not request.path.startswith("/api/"):
        return await handler(request)
    if request.method == "OPTIONS":
        resp = web.Response(status=204)
    else:
        resp = await handler(request)
    if origin in await _allowed_origins():
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "POST, GET, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Max-Age"] = "86400"
    return resp


async def web_server(bot=None):
    web_app = web.Application(client_max_size=30000000, middlewares=[cors_middleware])
    web_app["bot"] = bot          # Mini App backend ko bot client chahiye (link bhejne ke liye)
    web_app.add_routes(routes)
    return web_app
