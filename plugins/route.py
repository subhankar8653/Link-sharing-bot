import datetime
import logging
import os
import time

from aiohttp import web

routes = web.RouteTableDef()
logger = logging.getLogger(__name__)

WEBAPP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webapp")


@routes.get("/", allow_head=True)
async def root_route_handler(request):
    return web.json_response("RexBots - Abhi,Master,Seishiro")


# ═══════════════════════════════════════════════════════════════
# TELEGRAM MINI APP  (ads watch → link delivery)
# NOTE: plugin imports handlers ke andar hain (lazy) taaki
#       bot.py ↔ plugins circular import na ho.
# ═══════════════════════════════════════════════════════════════

@routes.get("/miniapp", allow_head=True)
async def miniapp_page(request):
    return web.FileResponse(
        os.path.join(WEBAPP_DIR, "index.html"),
        headers={"Cache-Control": "no-store"},
    )


async def _auth(body: dict):
    """initData + token verify. Returns (user_id, token, doc, error_code)."""
    from plugins.miniapp import validate_init_data
    from database.database import Seishiro

    user = validate_init_data(str(body.get("initData", "")))
    if not user:
        return None, None, None, "auth"

    token = str(body.get("token", ""))[:64]
    doc = await Seishiro.get_verify_token(token) if token else {}
    if not doc:
        return None, None, None, "invalid"
    if doc.get("used"):
        return None, None, None, "used"
    if int(doc.get("user_id", 0)) != int(user["id"]):
        return None, None, None, "not_yours"
    return int(user["id"]), token, doc, None



# ── Channel info (naam + profile photo) — Mini App header ke liye ──────────
_CH_CACHE: dict = {}          # channel_id -> {"title", "photo": bytes|None, "ts"}
_CH_TTL = 3600


async def _channel_info(bot, cid: int) -> dict:
    c = _CH_CACHE.get(cid)
    if c and time.time() - c["ts"] < _CH_TTL:
        return c
    title, photo = "", None
    try:
        from plugins.start import _resolve_peer_safe
        await _resolve_peer_safe(bot, cid)
        chat = await bot.get_chat(cid)
        title = chat.title or ""
        if chat.photo:
            bio = await bot.download_media(chat.photo.big_file_id, in_memory=True)
            if bio is not None:
                photo = bytes(bio.getbuffer())
    except Exception as e:
        logger.warning(f"channel info fetch failed ({cid}): {e}")
    info = {"title": title, "photo": photo, "ts": time.time()}
    _CH_CACHE[cid] = info
    return info


@routes.get("/miniapp/photo")
async def miniapp_photo(request):
    from database.database import Seishiro
    token = str(request.query.get("t", ""))[:64]
    doc = await Seishiro.get_verify_token(token) if token else {}
    bot = request.app.get("bot")
    if not doc or bot is None:
        return web.Response(status=404)
    info = await _channel_info(bot, doc["channel_id"])
    if not info.get("photo"):
        return web.Response(status=404)
    return web.Response(body=info["photo"], content_type="image/jpeg",
                        headers={"Cache-Control": "private, max-age=3600"})

@routes.post("/api/mini/init")
async def api_mini_init(request):
    from plugins.miniapp import get_miniapp_settings, build_steps
    from database.database import Seishiro

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad_request"}, status=400)

    uid, token, doc, err = await _auth(body)
    if err:
        return web.json_response({"ok": False, "error": err})

    s = await get_miniapp_settings()
    steps = build_steps(s["ads"])
    if not steps:
        return web.json_response({"ok": False, "error": "no_ads"})

    await Seishiro.start_miniapp_session(token, uid)
    bot = request.app.get("bot")
    info = await _channel_info(bot, doc["channel_id"]) if bot else {"title": "", "photo": None}
    return web.json_response({
        "ok": True,
        "steps": steps,
        "min_seconds": s["min_seconds"],
        "uid": uid,
        "channel": {"title": info["title"], "has_photo": bool(info["photo"])},
    })


@routes.post("/api/mini/complete")
async def api_mini_complete(request):
    from plugins.miniapp import get_miniapp_settings, build_steps
    from plugins.start import complete_miniapp_verification

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad_request"}, status=400)

    uid, token, doc, err = await _auth(body)
    if err:
        return web.json_response({"ok": False, "error": err})

    s = await get_miniapp_settings()
    total = len(build_steps(s["ads"]))
    try:
        shown = int(body.get("shown", 0))
        failed = int(body.get("failed", 0))
    except Exception:
        shown, failed = 0, 0
    shown = max(0, min(shown, total))
    failed = max(0, min(failed, total))

    # Kam se kam 1 ad actually dikhna chahiye (adblock/no-fill se bypass na ho)
    if shown < 1:
        return web.json_response({"ok": False, "error": "no_ad_shown"})
    # Saare steps ya toh dekhe gaye ya fail hue hone chahiye
    if shown + failed < total:
        return web.json_response({"ok": False, "error": "incomplete"})

    # Timing check: jitne ads dikhe, utna minimum time guzra hona chahiye
    started = doc.get("mini_started_at")
    if not started:
        return web.json_response({"ok": False, "error": "no_session"})
    elapsed = (datetime.datetime.now() - started).total_seconds()
    if elapsed < shown * s["min_seconds"]:
        return web.json_response({"ok": False, "error": "too_fast"})

    bot = request.app.get("bot")
    if bot is None:
        return web.json_response({"ok": False, "error": "server"})

    try:
        ok, reason, info = await complete_miniapp_verification(bot, uid, token, shown)
    except Exception as e:
        logger.error(f"miniapp complete error: {e}", exc_info=True)
        return web.json_response({"ok": False, "error": "server"})

    return web.json_response({"ok": ok, "error": None if ok else reason, "info": info})
