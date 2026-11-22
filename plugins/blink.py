"""
plugins/blink.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"B" TYPE LINKS — alag kamai wale links (purane links pe koi asar nahi)

Link formats:
  Normal :  https://t.me/<bot>?start=<b64>          (PURANA — untouched)
  Request:  https://t.me/<bot>?start=req_<b64>      (PURANA — untouched)
  B link :  https://t.me/<bot>?start=b_<b64>        (NAYA)
  B req  :  https://t.me/<bot>?start=breq_<b64>     (NAYA, join-request mode)

Har channel ki apni B-link setting (sab alag, global Link Flow / daily goal /
ads-free time / temp-premium se koi lena-dena nahi):
  🎬 Ads      : is channel ke B link pe kitne ads dikhane hain (0 = no ads)
  🔒 FSub     : B link pe FSub lagana hai ya nahi
  🔗 Shortener: B link pe shortener lagana hai ya nahi (alag shortener set kar sakte ho)
  💎 Premium  : asli (paid) premium user ko ads/shortener skip karwana hai ya nahi

Order:  FSub → Ads (Mini App) → Shortener → Link   (jo ON hai wahi chalega)
B link pe har baar ads aate hain (ads-free time / daily goal / "continue without ads" nahi chalta).

ADMIN:
  /blink                      → channels list → har channel ki B-link settings
  /blink <channel_id>         → seedha us channel ki settings
  /setbshortener API site.com → B links ka alag shortener (na ho toh main shortener use hota hai)
  /removebshortener | /bshortener
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import asyncio
import datetime
import logging
import secrets

from pyrogram import filters
from pyrogram.errors import PeerIdInvalid
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo,
)

from bot import Bot, _force_resolve_peer, check_bot_permissions
from config import OWNER_ID
from database.database import Seishiro
from helper_func import decode

logger = logging.getLogger(__name__)

DEFAULT_CFG = {"ads": 2, "fsub": False, "short": False, "prem": True}
ADS_CHOICES = [0, 1, 2, 3, 4, 5, 6, 8, 10, 15]
MIN_SHORT_SECONDS = 12          # shortener ke bina ad dekhe turant vfy link kholne se rokta hai
PAGE = 8


def _S():
    """plugins.start — lazy import (circular import se bachne ke liye)."""
    import plugins.start as S
    return S


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONFIG (DB)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _col():
    return Seishiro.database["blink_cfg"]


async def get_bcfg(channel_id: int) -> dict:
    cfg = dict(DEFAULT_CFG)
    try:
        doc = await _col().find_one({"_id": int(channel_id)})
        if doc:
            for k in DEFAULT_CFG:
                if k in doc:
                    cfg[k] = doc[k]
    except Exception as e:
        logger.error(f"get_bcfg error: {e}")
    cfg["ads"] = max(0, int(cfg["ads"] or 0))
    return cfg


async def set_bcfg(channel_id: int, **fields) -> None:
    await _col().update_one({"_id": int(channel_id)}, {"$set": fields}, upsert=True)


async def _bot_cfg() -> dict:
    from plugins.premium import _get_bot_config
    return await _get_bot_config()


async def get_b_shortener() -> dict:
    c = await _bot_cfg()
    return {"api": c.get("b_shortener_api", ""), "website": c.get("b_shortener_website", "")}


async def b_shorten(long_url: str) -> str:
    """B links ka shortener (alag set ho toh wahi, warna main shortener). Fail/not set → long_url wapas."""
    s = await get_b_shortener()
    if s["api"] and s["website"]:
        try:
            from shortzy import Shortzy
            sz = Shortzy(api_key=s["api"], base_site=s["website"])
            try:
                return await sz.convert(long_url)
            except Exception:
                return await sz.get_quick_link(long_url)
        except Exception as e:
            logger.error(f"B shortener error: {e}")
            return long_url
    from plugins.premium import shorten_link
    return await shorten_link(long_url)


async def _real_premium(uid: int) -> bool:
    """Sirf asli (paid/admin diya hua) premium. Normal links ka temp 'verify' premium / ads-free time count nahi hota
    (woh hamesha ≤ verify_premium_seconds ka hota hai), warna normal link ka free time B link ke ads skip kara deta."""
    if uid == OWNER_ID:
        return True
    try:
        if not await Seishiro.has_premium_access(uid):
            return False
        exp = await Seishiro.get_premium_expiry(uid)
        c = await _bot_cfg()
        temp = max(int(c.get("verify_premium_seconds", 86400) or 0), int(c.get("shortener_free_seconds", 0) or 0))
        if not isinstance(exp, datetime.datetime):
            return False
        return (exp - datetime.datetime.now()).total_seconds() > temp + 60
    except Exception as e:
        logger.error(f"_real_premium error: {e}")
        return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LINK DELIVERY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _deliver(client, uid: int, channel_id: int, is_req: bool, b64: str) -> bool:
    """Final step: channel ka link (original link set ho toh wahi) naye message mein. True = sent."""
    S = _S()
    try:
        await S._clear_flow_msgs(client, uid)
    except Exception:
        pass
    await S._resolve_peer_safe(client, channel_id)
    orig = await Seishiro.get_original_link(channel_id)
    inv = orig or await S._get_fresh_invite_link(client, channel_id, is_req)
    if not inv:
        await client.send_message(
            uid, "<b><blockquote expandable>Invite link error. Dobara try karein.</blockquote></b>")
        return False
    msg = await client.send_message(
        uid,
        "<b><blockquote expandable>ʜᴇʀᴇ ɪs ʏᴏᴜʀ ʟɪɴᴋ! ᴄʟɪᴄᴋ ʙᴇʟᴏᴡ ᴛᴏ ᴘʀᴏᴄᴇᴇᴅ</blockquote></b>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("• ᴄʟɪᴄᴋ ʜᴇʀᴇ •", url=inv)]]),
    )
    asyncio.create_task(S.delete_after_delay(msg, 300))
    if is_req and not orig:
        try:
            await Seishiro.save_user_request_link(
                uid, channel_id, b64, link_msg_id=msg.id, link_chat_id=msg.chat.id, invite_link=inv)
        except Exception as e:
            logger.warning(f"blink save_user_request_link failed: {e}")
    return True


async def _send_shortener_step(client, uid: int, channel_id: int, is_req: bool, b64: str, orig_cid: int) -> bool:
    """Shortener step bhejo. False = shortener kaam nahi kar raha (caller seedha link de de)."""
    token = secrets.token_urlsafe(12)
    await Seishiro.create_verify_token(uid, channel_id, token, is_req, b64)
    await Seishiro.update_alt_session(token, {"btype": True, "b_final": True, "b_orig": int(orig_cid)})
    bot_link = f"https://t.me/{client.username}?start=vfy_{token}"
    short_url = await b_shorten(bot_link)
    if not short_url or short_url == bot_link:
        return False
    await client.send_message(
        uid,
        "<b>🔗 Last Step!</b>\n\n"
        "<blockquote>Niche button pe click karo, short ad complete karo — "
        "uske baad channel link yahin chat mein mil jayega.</blockquote>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Get Channel Link", url=short_url)]]),
    )
    try:
        from plugins.tutorial import send_linkshortner_tutorial_if_not_verified
        asyncio.create_task(send_linkshortner_tutorial_if_not_verified(client, uid, token))
    except Exception:
        pass
    return True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ENTRY: /start b_<b64>  |  /start breq_<b64>
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def handle_blink(client: Bot, message: Message, uid: int, param: str):
    S = _S()
    is_req = param.startswith("breq_")
    b64 = param.split("_", 1)[1] if "_" in param else ""
    invalid = "<b><blockquote expandable>Invalid or expired invite link.</blockquote></b>"
    try:
        orig_cid = int(await decode(b64))
    except Exception as e:
        logger.error(f"B decode failed: {e}")
        return await message.reply_text(invalid)
    if not orig_cid or orig_cid > 0:
        return await message.reply_text(invalid)

    cfg = await get_bcfg(orig_cid)                   # config original channel id se (alias ho tab bhi same)
    channel_id = await Seishiro.get_channel_alias(orig_cid) or orig_cid

    if not await Seishiro.channel_data.find_one({"channel_id": channel_id}):
        await Seishiro.save_channel(channel_id)
    if is_req:
        await Seishiro.save_user_request_link(uid, channel_id, b64)

    # Peer resolve + bot admin check (normal link jaisa)
    try:
        await S._safe_get_chat(client, channel_id)
    except PeerIdInvalid:
        if not await _force_resolve_peer(client, channel_id):
            return await message.reply_text(
                "<b><blockquote expandable>⚠️ Channel resolve nahi hua. Bot ko admin banao aur dobara try karo."
                "</blockquote></b>")
    except Exception as e:
        return await message.reply_text(f"<b><blockquote expandable>Channel error: {str(e)[:80]}</blockquote></b>")
    is_admin_ch, can_invite, reason = await check_bot_permissions(client, channel_id)
    if not is_admin_ch:
        return await message.reply_text(
            f"<b><blockquote expandable>⚠️ Bot admin nahi hai.\nKaaran: {reason}</blockquote></b>")
    if not can_invite:
        return await message.reply_text(
            "<b><blockquote expandable>⚠️ Bot ko 'Invite Users' permission chahiye.</blockquote></b>")

    real_prem = await _real_premium(uid)
    skip_money = bool(cfg["prem"] and real_prem)     # ads + shortener skip

    # ── 1) FSub (B link ki apni setting) ──
    if cfg["fsub"]:
        if not await S._user_fsub_ok(client, uid, ignore_premium=not real_prem):
            return await S.not_joined(client, message)       # Joined/Try again → isi b_ link pe wapas

    if skip_money:
        await _deliver(client, uid, channel_id, is_req, b64)
        return

    # ── 2) Ads (Mini App) ──
    if cfg["ads"] > 0:
        from plugins.miniapp import miniapp_ready, get_miniapp_settings
        if await miniapp_ready():
            ms = await get_miniapp_settings()
            token = secrets.token_urlsafe(12)
            await Seishiro.create_verify_token(uid, channel_id, token, is_req, b64)
            await Seishiro.update_alt_session(token, {
                "btype": True, "b_ads": int(cfg["ads"]), "b_short": bool(cfg["short"]), "b_orig": int(orig_cid)})
            web_url = f"{ms['url']}/miniapp?t={token}"
            rows = [[InlineKeyboardButton("Watch Video Ad", web_app=WebAppInfo(url=web_url))]]
            _tut = (await _bot_cfg()).get("miniapp_tutorial")
            if _tut and _tut.get("kind") == "link" and _tut.get("url"):
                rows.append([InlineKeyboardButton("How to watch ads", url=_tut["url"])])
            elif _tut:
                rows.append([InlineKeyboardButton("How to watch ads", callback_data="ads_tut")])
            prompt = await message.reply_text(
                "<b>Your link is ready</b>\n\n"
                "<blockquote>Tap <b>Watch Video Ad</b>, finish the short ads in the Mini App "
                "and your channel link will arrive in this chat automatically.\n\n"
                f"<a href=\"https://t.me/{client.username}?start=premium\">Premium</a> users skip this step."
                "</blockquote>",
                reply_markup=InlineKeyboardMarkup(rows),
            )
            await Seishiro.set_token_prompt(token, prompt.chat.id, prompt.id)
            return
        logger.warning("B link: ads>0 hai lekin Mini App ready nahi — ads step skip")

    # ── 3) Shortener (ads nahi / Mini App ready nahi) ──
    if cfg["short"]:
        if await _send_shortener_step(client, uid, channel_id, is_req, b64, orig_cid):
            return

    # ── 4) Kuch bhi ON nahi → seedha link ──
    await _deliver(client, uid, channel_id, is_req, b64)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Mini App complete (B token) — start.complete_miniapp_verification se call hota hai
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def complete_blink_ads(client: Bot, uid: int, doc: dict, shown: int):
    """Ads poore hue (token pehle hi claim ho chuka). Ads-free time / daily goal / temp premium NAHI milta.
    Returns (ok, reason, info)."""
    S = _S()
    channel_id = doc["channel_id"]
    is_req = doc.get("is_request", False)
    b64 = doc.get("b64", "")
    orig_cid = int(doc.get("b_orig") or channel_id)

    # ads rotation cursor aage badhao (agla session agle ads se)
    try:
        from plugins.miniapp import get_miniapp_settings, build_steps
        ms = await get_miniapp_settings()
        _all = build_steps(ms["ads"])
        if _all and doc.get("mini_n"):
            await Seishiro.set_ad_cursor(uid, (int(doc.get("mini_cursor", 0)) + int(doc["mini_n"])) % len(_all))
    except Exception as e:
        logger.warning(f"B ad cursor advance failed: {e}")

    try:
        if doc.get("prompt_msg_id"):
            await client.delete_messages(doc.get("prompt_chat_id", uid), doc["prompt_msg_id"])
    except Exception as e:
        logger.warning(f"B prompt msg delete failed: {e}")

    logger.info(f"B ads done: user={uid}, channel={channel_id}, shown={shown}, short={doc.get('b_short')}")

    if doc.get("b_short"):
        if await _send_shortener_step(client, uid, channel_id, is_req, b64, orig_cid):
            return True, "ok", {"short": True}
    ok = await _deliver(client, uid, channel_id, is_req, b64)
    if not ok:
        await Seishiro.unclaim_verify_token(doc["token"])
        return False, "invite_error", {}
    return True, "ok", {}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Shortener se wapas (vfy_<token>, B token) — start._handle_verify_token se call hota hai
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def complete_blink_verify(client: Bot, message: Message, uid: int, doc: dict, token: str):
    created = doc.get("created_at")
    if isinstance(created, datetime.datetime) and \
            (datetime.datetime.now() - created).total_seconds() < MIN_SHORT_SECONDS:
        return await message.reply_text(
            "<b><blockquote expandable>⚠️ Pehle short ad poora complete karo, "
            "phir link milega.</blockquote></b>")
    claimed = await Seishiro.claim_verify_token(token, uid)
    if not claimed:
        return await message.reply_text(
            "<b><blockquote expandable>⚠️ Yeh link pehle use ho chuka hai.\n\n"
            "Dobara channel link pane ke liye original link pe click karo.</blockquote></b>")
    ok = await _deliver(client, uid, claimed["channel_id"], claimed.get("is_request", False), claimed.get("b64", ""))
    if not ok:
        await Seishiro.unclaim_verify_token(token)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ADMIN PANEL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _is_admin(uid: int) -> bool:
    return uid == OWNER_ID or await Seishiro.is_admin(uid)


async def _title(client, cid: int) -> str:
    try:
        return (await client.get_chat(cid)).title or str(cid)
    except Exception:
        return str(cid)


async def _list_ui(client, page: int):
    chans = await Seishiro.show_channels()
    pages = max(1, (len(chans) + PAGE - 1) // PAGE)
    page = max(0, min(page, pages - 1))
    rows = []
    for cid in chans[page * PAGE:(page + 1) * PAGE]:
        rows.append([InlineKeyboardButton(await _title(client, cid), callback_data=f"bl_ch_{cid}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◄ Prev", callback_data=f"bl_list_{page - 1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("Next ►", callback_data=f"bl_list_{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("🔗 B Shortener", callback_data="bl_short_info")])
    rows.append([InlineKeyboardButton("‹ Back", callback_data="link_share")])
    text = ("<b>🅱️ B Links</b>\n\n<i>Channel chuno — uske B link ki alag setting "
            "(ads / FSub / shortener) set karo.</i>\n\n" f"<b>Page {page + 1}/{pages}</b>")
    if not chans:
        text = "<b>🅱️ B Links</b>\n\n📭 Koi channel add nahi hai. Pehle Link Menu → Add Channel."
    return text, InlineKeyboardMarkup(rows)


async def _panel_ui(client, cid: int):
    cfg = await get_bcfg(cid)
    title = await _title(client, cid)
    b64 = await _b64(cid)
    u = client.username
    onoff = lambda v: "✅ ON" if v else "❌ OFF"
    ads_txt = "OFF (no ads)" if cfg["ads"] == 0 else str(cfg["ads"])
    text = (
        f"<b>🅱️ B Link Settings</b>\n\n"
        f"<b>Channel:</b> {title}\n<code>{cid}</code>\n\n"
        f"🎬 Ads: <b>{ads_txt}</b>\n"
        f"🔒 FSub: <b>{onoff(cfg['fsub'])}</b>\n"
        f"🔗 Shortener: <b>{onoff(cfg['short'])}</b>\n"
        f"💎 Premium Bypass: <b>{onoff(cfg['prem'])}</b>\n\n"
        f"<b>B Link:</b>\n<code>https://t.me/{u}?start=b_{b64}</code>\n\n"
        f"<b>B Request Link:</b>\n<code>https://t.me/{u}?start=breq_{b64}</code>\n\n"
        f"<i>Order: FSub → Ads → Shortener → Link</i>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🎬 Ads: {ads_txt}", callback_data=f"bl_ads_{cid}")],
        [InlineKeyboardButton(f"🔒 FSub: {onoff(cfg['fsub'])}", callback_data=f"bl_t_fsub_{cid}")],
        [InlineKeyboardButton(f"🔗 Shortener: {onoff(cfg['short'])}", callback_data=f"bl_t_short_{cid}")],
        [InlineKeyboardButton(f"💎 Premium Bypass: {onoff(cfg['prem'])}", callback_data=f"bl_t_prem_{cid}")],
        [InlineKeyboardButton("‹ Back", callback_data="bl_list_0")],
    ])
    return text, kb


async def _b64(cid: int) -> str:
    from helper_func import encode
    return await encode(str(cid))


@Bot.on_message(filters.command("blink") & filters.private)
async def cmd_blink(client: Bot, msg: Message):
    if not await _is_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    if len(msg.command) > 1:
        try:
            cid = int(msg.command[1])
        except ValueError:
            return await msg.reply("<code>/blink -100123456789</code>")
        if not await Seishiro.reqChannel_exist(cid):
            return await msg.reply("❌ Yeh channel added list mein nahi hai.")
        text, kb = await _panel_ui(client, cid)
        return await msg.reply(text, reply_markup=kb)
    text, kb = await _list_ui(client, 0)
    await msg.reply(text, reply_markup=kb)


@Bot.on_callback_query(filters.regex(r"^bl_"), group=-1)
async def blink_cb(client: Bot, cq: CallbackQuery):
    if not await _is_admin(cq.from_user.id):
        return await cq.answer("Only admins!", show_alert=True)
    d = cq.data
    try:
        if d.startswith("bl_list_"):
            text, kb = await _list_ui(client, int(d.split("_")[2]))
            return await cq.message.edit_text(text, reply_markup=kb)

        if d.startswith("bl_ch_"):
            text, kb = await _panel_ui(client, int(d.split("_", 2)[2]))
            return await cq.message.edit_text(text, reply_markup=kb)

        if d.startswith("bl_t_"):                       # bl_t_<fsub|short|prem>_<cid>
            _, _, key, cid = d.split("_", 3)
            cid = int(cid)
            cfg = await get_bcfg(cid)
            if key not in ("fsub", "short", "prem"):
                return await cq.answer()
            await set_bcfg(cid, **{key: not cfg[key]})
            if key == "short" and not cfg["short"]:     # abhi ON hua
                s = await get_b_shortener()
                from plugins.premium import get_shortener_settings
                m = await get_shortener_settings()
                if not (s["api"] and s["website"]) and not (m["enabled"] and m["api"] and m["website"]):
                    await cq.answer("⚠️ Koi shortener set nahi! /setbshortener se set karo, warna yeh step skip hoga.",
                                    show_alert=True)
            text, kb = await _panel_ui(client, cid)
            return await cq.message.edit_text(text, reply_markup=kb)

        if d.startswith("bl_ads_"):
            cid = int(d.split("_", 2)[2])
            from plugins.miniapp import get_miniapp_settings, build_steps
            total = len(build_steps((await get_miniapp_settings())["ads"]))
            cur = (await get_bcfg(cid))["ads"]
            btns = [InlineKeyboardButton(("• " if n == cur else "") + ("Off" if n == 0 else str(n)),
                                         callback_data=f"bl_setads_{cid}_{n}") for n in ADS_CHOICES]
            rows = [btns[i:i + 4] for i in range(0, len(btns), 4)]
            rows.append([InlineKeyboardButton("‹ Back", callback_data=f"bl_ch_{cid}")])
            return await cq.message.edit_text(
                f"<b>🎬 B Link Ads</b>\n\nIs channel ke B link pe kitne ads dikhane hain?\n"
                f"<i>Abhi Mini App mein total {total} ad slot(s) ON hain — usse zyada set karoge toh utne hi dikhenge.</i>",
                reply_markup=InlineKeyboardMarkup(rows))

        if d.startswith("bl_setads_"):
            _, _, cid, n = d.split("_", 3)
            await set_bcfg(int(cid), ads=max(0, min(50, int(n))))
            text, kb = await _panel_ui(client, int(cid))
            return await cq.message.edit_text(text, reply_markup=kb)

        if d == "bl_short_info":
            s = await get_b_shortener()
            txt = (f"<b>🔗 B Shortener</b>\n\nSite: <code>{s['website'] or 'Not set (main shortener use hoga)'}</code>\n"
                   f"API: <code>{(s['api'][:8] + '...') if s['api'] else 'Not set'}</code>\n\n"
                   f"<code>/setbshortener API_KEY website.com</code>\n<code>/removebshortener</code>")
            return await cq.message.edit_text(
                txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("‹ Back", callback_data="bl_list_0")]]))
    except Exception as e:
        if "MESSAGE_NOT_MODIFIED" in str(e):
            return await cq.answer()
        logger.error(f"blink_cb error ({d}): {e}", exc_info=True)
        await cq.answer("Error — logs check karo", show_alert=True)


@Bot.on_message(filters.command("setbshortener") & filters.private)
async def cmd_set_bshortener(client: Bot, msg: Message):
    if not await _is_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    if len(msg.command) < 3:
        return await msg.reply("<b>Usage:</b> <code>/setbshortener API_KEY website.com</code>")
    from plugins.premium import _set_bot_config
    site = msg.command[2].strip().lower().replace("https://", "").replace("http://", "").rstrip("/")
    await _set_bot_config("b_shortener_api", msg.command[1])
    await _set_bot_config("b_shortener_website", site)
    await msg.reply(f"✅ <b>B Shortener set!</b>\nSite: <code>{site}</code>\n\n"
                    f"Ab jin channels ke B link pe Shortener ON hai wahan yahi use hoga. Purane links pe asar nahi.")


@Bot.on_message(filters.command("removebshortener") & filters.private)
async def cmd_remove_bshortener(client: Bot, msg: Message):
    if not await _is_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    from plugins.premium import _set_bot_config
    await _set_bot_config("b_shortener_api", "")
    await _set_bot_config("b_shortener_website", "")
    await msg.reply("🗑 B shortener hata diya. Ab B links pe main shortener (agar ON ho) use hoga.")


@Bot.on_message(filters.command("bshortener") & filters.private)
async def cmd_bshortener(client: Bot, msg: Message):
    if not await _is_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    s = await get_b_shortener()
    await msg.reply(f"<b>🔗 B Shortener</b>\n\nSite: <code>{s['website'] or 'Not set (main use hoga)'}</code>\n"
                    f"API: <code>{(s['api'][:8] + '...') if s['api'] else 'Not set'}</code>")
