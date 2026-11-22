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


@routes.get("/tribute", allow_head=True)
async def tribute_page(request):
    return web.FileResponse(
        os.path.join(WEBAPP_DIR, "tribute.html"),
        headers={"Cache-Control": "no-store"},
    )


@routes.get("/go", allow_head=True)
async def go_page(request):
    return web.FileResponse(
        os.path.join(WEBAPP_DIR, "go.html"),
        headers={"Cache-Control": "no-store"},
    )


@routes.post("/api/mini/alt")
async def api_mini_alt(request):
    """Alternative method page (/go): Mini App jaisa session.
    {t, go}   → smart links (Ads/Session + rotation) + countdown seconds
    {t, done} → saare ads ho gaye: shortener ON ho toh uska URL, warna link
    {t, ret}  → shortener se wapas aaya: link
    Token hi secret hai (browser mein Telegram login nahi hota)."""
    from plugins.miniapp import get_alt_settings, get_miniapp_settings, pick_session
    from plugins.start import complete_miniapp_verification
    from database.database import Seishiro
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad_request"}, status=400)

    token = str(body.get("t", ""))[:40]
    doc = await Seishiro.get_verify_token(token) if token else {}
    if not doc or doc.get("used") or not doc.get("alt_on"):
        return web.json_response({"ok": False, "error": "invalid"})
    alt = await get_alt_settings()
    bot = request.app.get("bot")
    if not alt["enabled"] or bot is None:
        return web.json_response({"ok": False, "error": "off"})

    uid   = doc["user_id"]
    s     = await get_miniapp_settings()
    min_s = max(3, int(s["min_seconds"]))
    now   = datetime.datetime.now()
    links = alt["links"]
    short = bool(doc.get("alt_next"))

    async def finish():
        n = int(doc.get("alt_n") or 0)
        try:
            ok, reason, info = await complete_miniapp_verification(bot, uid, token, max(1, n))
        except Exception as e:
            logger.error(f"alt complete error: {e}", exc_info=True)
            return web.json_response({"ok": False, "error": "server"})
        if ok and links and n > 0:              # rotation: agla alt session agle smart link se
            await Seishiro.set_alt_cursor(uid, (int(doc.get("alt_cursor0") or 0) + n) % len(links))
        info = dict(info or {})
        ch = await _channel_info(bot, doc["channel_id"])
        info["title"] = ch.get("title", "")
        return web.json_response({"ok": ok, "error": None if ok else reason, "info": info,
                                  "bot_url": f"https://t.me/{bot.username}"})

    if body.get("go"):
        if not links and not short:
            return web.json_response({"ok": False, "error": "off"})
        cursor = await Seishiro.get_alt_cursor(uid)
        steps, n = pick_session(links, s["per_session"], cursor) if links else ([], 0)
        await Seishiro.update_alt_session(token, {"alt_started_at": now, "alt_cursor0": cursor, "alt_n": n,
                                                  "alt_ads_done": False, "alt_short_at": None})
        ch = await _channel_info(bot, doc["channel_id"])
        return web.json_response({"ok": True, "steps": steps, "min_seconds": min_s, "short": short,
                                  "channel": {"title": ch.get("title", ""), "has_photo": bool(ch.get("photo"))}})

    if body.get("done"):
        started = doc.get("alt_started_at")
        n = int(doc.get("alt_n") or 0)
        if not isinstance(started, datetime.datetime):
            return web.json_response({"ok": False, "error": "no_session"})
        if (now - started).total_seconds() < n * min_s - 1:
            return web.json_response({"ok": False, "error": "too_fast"})
        if short:                                # last step: shortener
            await Seishiro.update_alt_session(token, {"alt_ads_done": True, "alt_short_at": now})
            return web.json_response({"ok": True, "phase": "short", "next": doc["alt_next"]})
        return await finish()

    if body.get("ret"):                          # shortener se wapas
        sh_at = doc.get("alt_short_at")
        if not doc.get("alt_ads_done") or not isinstance(sh_at, datetime.datetime):
            return web.json_response({"ok": False, "error": "no_session"})
        if (now - sh_at).total_seconds() < 5:
            return web.json_response({"ok": False, "error": "too_fast"})
        return await finish()

    return web.json_response({"ok": False, "error": "bad_request"})


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
    from plugins.miniapp import get_miniapp_settings, build_steps, pick_session
    from database.database import Seishiro

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad_request"}, status=400)

    uid, token, doc, err = await _auth(body)
    if err:
        return web.json_response({"ok": False, "error": err})

    s = await get_miniapp_settings()
    all_steps = build_steps(s["ads"])
    if not all_steps:
        return web.json_response({"ok": False, "error": "no_ads"})

    # Per-session ads: user ke cursor se shuru karke N ads (agla session wahin se)
    cursor = await Seishiro.get_ad_cursor(uid)
    steps, n = pick_session(all_steps, s["per_session"], cursor)
    await Seishiro.start_miniapp_session(token, uid, cursor, n)
    bot = request.app.get("bot")
    info = await _channel_info(bot, doc["channel_id"]) if bot else {"title": "", "photo": None}
    return web.json_response({
        "ok": True,
        "steps": steps,
        "min_seconds": s["min_seconds"],
        "uid": uid,
        "channel": {"title": info["title"], "has_photo": bool(info["photo"])},
        "fallback": s["fb_daily"] > 0,
        "tutorial": bool((await _get_cfg()).get("miniapp_tutorial")),
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
    total = int(doc.get("mini_n") or 0) or len(build_steps(s["ads"]))   # is session ke ads (per-session ke hisaab se)
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


async def _get_cfg() -> dict:
    from plugins.premium import _get_bot_config
    return await _get_bot_config()


@routes.post("/api/mini/fallback")
async def api_mini_fallback(request):
    """Ads load nahi hue: bina ads FSub-> link (limited)."""
    from plugins.start import complete_via_fallback
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad_request"}, status=400)
    uid, token, doc, err = await _auth(body)
    if err:
        return web.json_response({"ok": False, "error": err})
    started = doc.get("mini_started_at")
    if not started or (datetime.datetime.now() - started).total_seconds() < 8:
        return web.json_response({"ok": False, "error": "too_fast"})   # session khulte hi turant skip nahi
    bot = request.app.get("bot")
    if bot is None:
        return web.json_response({"ok": False, "error": "server"})
    try:
        ok, reason, info = await complete_via_fallback(bot, uid, token)
    except Exception as e:
        logger.error(f"miniapp fallback error: {e}", exc_info=True)
        return web.json_response({"ok": False, "error": "server"})
    return web.json_response({"ok": ok, "error": None if ok else reason, "info": info})


@routes.post("/api/mini/tutorial")
async def api_mini_tutorial(request):
    from plugins.miniapp import send_ads_tutorial
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad_request"}, status=400)
    uid, token, doc, err = await _auth(body)
    if err:
        return web.json_response({"ok": False, "error": err})
    bot = request.app.get("bot")
    ok = bool(bot) and await send_ads_tutorial(bot, uid)
    return web.json_response({"ok": ok, "error": None if ok else "no_tutorial"})


@routes.get("/config.js")
async def miniapp_config_js(request):
    # Railway se serve hone par API same origin hai. Vercel par is file ko apne Railway URL se badlo.
    return web.Response(text='window.SYNC_API = ""; window.SYNC_MODE = "both"; window.BOT_USERNAME = "";', content_type="application/javascript",
                        headers={"Cache-Control": "no-store"})


@routes.post("/api/sync/{action}")
async def api_sync(request):
    from plugins.miniapp import validate_init_data
    from plugins.sync_app import handle
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad_request"}, status=400)
    user = validate_init_data(str(body.get("initData", "")))
    if not user:
        return web.json_response({"ok": False, "error": "auth"})
    try:
        res = await handle(request.match_info["action"], user, body, request.app.get("bot"))
    except Exception as e:
        logger.error(f"sync api error ({request.match_info['action']}): {e}", exc_info=True)
        res = {"ok": False, "error": "server"}
    return web.json_response(res)
