import asyncio
import secrets
import time
import logging
from collections import defaultdict
from asyncio import Lock
from functools import wraps

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ChatAction
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, WebAppInfo
)
from pyrogram.errors import (
    FloodWait, InputUserDeactivated, UserIsBlocked, PeerIdInvalid, RPCError
)
from pyrogram.errors.exceptions.bad_request_400 import UserNotParticipant

from bot import Bot, _force_resolve_peer, check_bot_permissions
from datetime import datetime, timedelta
from config import *
from database.database import Seishiro
from plugins.settings import revoke_invite_after_5_minutes
from plugins.premium import shorten_link, _get_bot_config
from plugins.miniapp import build_steps, miniapp_ready, get_miniapp_settings, seconds_until_ist_midnight, get_link_flow, seq_next, seq_index
from plugins.fsub_extra import render_fsub_text
from plugins.sync_app import sync_enabled_and_url, sync_register_from_bot, intro_message
from helper_func import *
from plugins.tutorial import send_fsub_tutorial_if_not_joined, send_linkshortner_tutorial_if_not_verified

logger = logging.getLogger(__name__)

# ── TTL Chat Cache (10 minute) ────────────────────────────────────────────────
# Ek hi channel ko baar baar GetFullChannel se fetch karne pe FloodWait aata hai.
# Cache mein rakhne se Telegram API calls drastically kam ho jaate hain.
_CHAT_CACHE: dict[int, tuple] = {}   # {channel_id: (chat_object, timestamp)}
_CHAT_CACHE_TTL = 600                # 10 minute

def _get_cached_chat(cid: int):
    entry = _CHAT_CACHE.get(cid)
    if entry:
        obj, ts = entry
        if (datetime.now() - ts).total_seconds() < _CHAT_CACHE_TTL:
            return obj
    return None

def _set_cached_chat(cid: int, obj):
    _CHAT_CACHE[cid] = (obj, datetime.now())


async def _safe_get_chat(client, cid: int, retries: int = 3):
    """
    get_chat ka flood-safe wrapper.
    FloodWait aaye toh wait karke retry karo (max 3 baar).
    Cache se milega toh Telegram call hi nahi hoga.
    """
    cached = _get_cached_chat(cid)
    if cached:
        return cached

    for attempt in range(retries):
        try:
            data = await client.get_chat(cid)
            _set_cached_chat(cid, data)
            return data
        except FloodWait as fw:
            wait = fw.value + 2
            logger.warning(f"FloodWait {wait}s on get_chat({cid}), attempt {attempt+1}/{retries}")
            await asyncio.sleep(wait)
        except PeerIdInvalid:
            raise
        except Exception as e:
            logger.error(f"get_chat({cid}) error: {e}")
            raise
    raise Exception(f"get_chat({cid}) failed after {retries} retries (FloodWait)")


async def _safe_get_member(client, cid: int, uid: int, retries: int = 3):
    """
    get_chat_member ka flood-safe wrapper.
    FloodWait aaye toh wait karke retry karo.
    """
    for attempt in range(retries):
        try:
            return await client.get_chat_member(cid, uid)
        except FloodWait as fw:
            wait = fw.value + 2
            logger.warning(f"FloodWait {wait}s on get_chat_member({cid},{uid}), attempt {attempt+1}/{retries}")
            await asyncio.sleep(wait)
        except Exception:
            raise
    raise Exception(f"get_chat_member({cid},{uid}) failed after {retries} retries (FloodWait)")


# Legacy dict — kuch jagah directly use hota tha, ab _safe_get_chat use karo
chat_data_cache = {}
channel_locks   = defaultdict(Lock)

# ═══════════════════════════════════════════
# ADMIN FILTER
# ═══════════════════════════════════════════

async def _is_admin(user_id: int) -> bool:
    return user_id == OWNER_ID or await Seishiro.is_admin(user_id)

async def check_admin(filter, client, message):
    try:
        return await _is_admin(message.from_user.id)
    except Exception as e:
        logger.error(f"check_admin error: {e}")
        return False

admin = filters.create(check_admin)


# ═══════════════════════════════════════════
# FSUB SMART AUTO-CHECK (step-by-step, background poll)
# /auto_check ON hone par hi active hota hai. OFF hone par is poore block
# ka koi effect nahi — behaviour bilkul pehle jaisa hi rehta hai
# (not_joined() function jo neeche hai, wahi use hoti hai, unchanged).
#
# ON hone par: ek waqt mein sirf EK channel ka step dikhaya jaata hai.
# User join/request karte hi (background poll se auto-detect ya "Maine
# Join Kar Liya" button se manually) agla step khud-ba-khud dikh jaata
# hai. Sabhi steps complete hote hi purana step-message delete karke
# asli link (func) deliver ho jaata hai.
# ═══════════════════════════════════════════

AUTO_CHECK_FAST_INTERVAL = 2       # pehle 30 second bahut fast check (request turant detect ho)
AUTO_CHECK_FAST_WINDOW   = 30       # itne second tak fast mode chalega
AUTO_CHECK_POLL_INTERVAL = 5        # uske baad normal interval
AUTO_CHECK_MAX_DURATION  = 900      # 15 minute tak hi poll karo, uske baad chhod do

# Per-user ek hi poll task chale — dobara /start karne pe duplicate na bane
_auto_check_tasks: dict[int, asyncio.Task] = {}

# Per-user stepwise FSub state: message/func/args/kwargs (link deliver karne
# ke liye) + step_msg (jo message edit/delete hoga) + shown_step (abhi konsa
# step display ho raha hai).
_fsub_context: dict[int, dict] = {}


async def _channel_join_status(client, uid: int, cid: int) -> bool:
    """Ek channel ke liye user join/request kiya hai ya nahi — check_fsub aur
    stepwise dono jagah yahi single source of truth use karte hain."""
    try:
        m = await _safe_get_member(client, cid, uid)
        ok = m.status in {
            ChatMemberStatus.OWNER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.MEMBER
        }
        if ok:
            try:
                if await Seishiro.req_user_exist(cid, uid):
                    await Seishiro.del_req_user(cid, uid)
            except Exception:
                pass
        return ok
    except UserNotParticipant:
        if await Seishiro.get_channel_mode(cid) == "on":
            return await Seishiro.req_user_exist(cid, uid)
        return False
    except Exception as e:
        logger.error(f"_channel_join_status error: {e}")
        return False


async def _compute_fresh_pending_order(client, uid: int) -> list:
    """Naya stepwise session shuru hote waqt call hota hai — ABHI (real-time) ke
    hisaab se jo FSub channels join/request nahi hue unki FIXED, ordered list
    banata hai. Yehi list poore session ke dauraan stable rehti hai (isse hi
    'Total Steps' nikalta hai) — chahe user pehle kitna bhi join kar chuka ho ya
    baad mein kisi channel ko leave kyun na kar de, session shuru hote hi sirf
    UTNE hi steps count honge jitne us waqt sach mein pending the."""
    channels = await Seishiro.get_fsub_channels()
    pending_order = []
    for cid in channels:
        try:
            joined = await _channel_join_status(client, uid, cid)
        except Exception as e:
            logger.error(f"_compute_fresh_pending_order check error {cid}: {e}")
            joined = False
        if not joined:
            pending_order.append(cid)
    return pending_order


async def _current_pending_within_order(client, uid: int, channel_order: list) -> list:
    """channel_order (fixed session list) mein se abhi bhi kaun se pending hain,
    check karo — usi fixed order mein."""
    pending = []
    for cid in channel_order:
        try:
            joined = await _channel_join_status(client, uid, cid)
        except Exception as e:
            logger.error(f"_current_pending_within_order check error {cid}: {e}")
            joined = False
        if not joined:
            pending.append(cid)
    return pending


async def _build_fsub_channel_button(client, cid: int, position: int):
    """Ek channel ka join/request button banao — not_joined() ki hi link-building
    logic yahan reuse hoti hai (username link / persistent invite link / custom name)."""
    try:
        if cid in chat_data_cache:
            data = chat_data_cache[cid]
        else:
            try:
                data = await _safe_get_chat(client, cid)
                chat_data_cache[cid] = data
            except PeerIdInvalid:
                if not await _force_resolve_peer(client, cid):
                    return None
                data = await _safe_get_chat(client, cid)
                chat_data_cache[cid] = data

        mode = await Seishiro.get_channel_mode(cid)
        if data.username:
            link = f"https://t.me/{data.username}"
        else:
            link = await _get_persistent_fsub_link(client, cid, is_request=(mode == "on"))
            if not link:
                return None

        custom_name = await Seishiro.get_fsub_channel_name(cid)
        if custom_name:
            btn_text = f"🔴 {custom_name}"
        else:
            label = "Request" if mode == "on" else "Join"
            btn_text = f"🔴 {label} channel {position:02d}"
        return InlineKeyboardButton(text=btn_text, url=link)
    except Exception as e:
        logger.error(f"_build_fsub_channel_button error {cid}: {e}")
        return None


def _fsub_step_caption(step_num: int, total: int) -> str:
    return (
        "<b>Welcome! 😁</b>\n\n"
        "<blockquote>Apni link paane ke liye niche diye gaye channels ko "
        "step-by-step join ya request karna hai.\n"
        f"Tᴏᴛᴀʟ Sᴛᴇᴘs: {total:02d}</blockquote>\n\n"
        f"📍 <b>Sᴛᴇᴘ {step_num:02d}/{total:02d}</b>\n"
        "<blockquote>🔴 Niche diya gaya channel join ya request karein — karte hi "
        "agla step khud-ba-khud NAYE message mein dikh jayega.\n"
        "Turant check karwana ho toh niche wala 🔵 button dabayein.</blockquote>"
    )


async def _fsub_step_caption_async(step_num: int, total: int, user=None) -> str:
    """Admin ne custom fsub text set kiya ho toh wahi (+ step number), warna default caption."""
    custom = ((await Seishiro.get_fsub_ui()).get("text") or "").strip()
    if custom:
        return f"{render_fsub_text(custom, user)}\n\n<b>Step {step_num:02d}/{total:02d}</b>"
    return _fsub_step_caption(step_num, total)


async def _send_fsub_ui(message, caption: str, markup):
    """Fsub screen bhejo: custom/default photo ke saath; photo 'none' ho ya fail ho toh sirf text.
    Message ID save hota hai taaki link aate hi ye screen delete ho jaye."""
    ui  = await Seishiro.get_fsub_ui()
    pic = ui.get("pic") or FSUB_PIC
    sent = None
    if pic != "none":
        try:
            sent = await message.reply_photo(photo=pic, caption=caption, reply_markup=markup)
        except Exception as e:
            logger.warning(f"fsub photo send failed, falling back to text: {e}")
    if sent is None:
        sent = await message.reply_text(caption, reply_markup=markup)
    try:
        await Seishiro.push_flow_msg(message.from_user.id, sent.chat.id, sent.id)
    except Exception:
        pass
    return sent


async def _clear_flow_msgs(client, uid: int) -> None:
    """Link se pehle ke saare flow messages (FSub screen etc.) delete — naya link message akela aaye."""
    for chat_id, msg_id in await Seishiro.pop_flow_msgs(uid):
        try:
            await client.delete_messages(chat_id, msg_id)
        except Exception:
            pass


async def _build_next_step(client, channel_order: list, pending_cids: list, total: int, user=None):
    """pending_cids (channel_order ke fixed order mein) se pehla wala channel try
    karo jiska button ban jaaye (koi resolve na ho paaye toh agle pe skip).
    step_num = us channel ki position channel_order mein (1-based) — yehi number
    caption aur button dono mein consistent dikhta hai.
    Return: (step_num, cid, caption, buttons) ya None."""
    for cid in pending_cids:
        step_num = channel_order.index(cid) + 1
        btn = await _build_fsub_channel_button(client, cid, step_num)
        if btn:
            caption = await _fsub_step_caption_async(step_num, total, user)
            buttons = InlineKeyboardMarkup([
                [btn],
                [InlineKeyboardButton("🔵 Mᴀɪɴᴇ Jᴏɪɴ Kᴀʀ Lɪʏᴀ", callback_data="fsub_stepcheck")]
            ])
            return step_num, cid, caption, buttons
    return None


async def _finish_fsub_stepwise(client: Client, uid: int):
    """Sabhi steps complete — purana step-message delete karo aur asli link deliver karo."""
    ctx = _fsub_context.pop(uid, None)
    if not ctx:
        return
    step_msg = ctx.get("step_msg")
    if step_msg:
        try:
            await step_msg.delete()
        except Exception:
            pass
    message = ctx.get("message")
    func    = ctx.get("func")
    args    = ctx.get("args", ())
    kwargs  = ctx.get("kwargs", {})
    if message is None or func is None:
        return
    try:
        await func(client, message, *args, **kwargs)
    except Exception as e:
        logger.error(f"_finish_fsub_stepwise deliver error for {uid}: {e}")


async def _refresh_fsub_step(client: Client, uid: int) -> str:
    """FSub step ko latest pending status ke hisaab se refresh karta hai.
    Naya step aane par PURANA step-message DELETE karke NAYA message bheja
    jaata hai (sirf silent edit nahi) — taaki user ko turant, saaf-saaf pata
    chale ki agla step aa gaya hai.
    Return: "finished" | "advanced" | "same" | "no_context" | "error" """
    ctx = _fsub_context.get(uid)
    if not ctx:
        return "no_context"

    channel_order = ctx.get("channel_order") or []
    total = ctx.get("total_steps", len(channel_order))

    if not channel_order:
        return "error"

    pending_cids = await _current_pending_within_order(client, uid, channel_order)

    if not pending_cids:
        await _finish_fsub_stepwise(client, uid)
        return "finished"

    _ctx_msg = ctx.get("message")
    built = await _build_next_step(client, channel_order, pending_cids, total,
                                   user=getattr(_ctx_msg, "from_user", None))
    if built is None:
        return "error"

    step_num, cid, caption, buttons = built

    if ctx.get("shown_step") == step_num:
        return "same"

    # Purana step-message hata do — naya step hamesha ek NAYE message ke roop
    # mein bhejte hain, taaki user ko chat mein fresh notification jaisa dikhe.
    old_step_msg = ctx.get("step_msg")
    if old_step_msg is not None:
        try:
            await old_step_msg.delete()
        except Exception as e:
            logger.error(f"_refresh_fsub_step old msg delete failed for {uid}: {e}")

    orig_message = ctx.get("message")
    if orig_message is None:
        return "error"
    try:
        new_msg = await _send_fsub_ui(orig_message, caption, buttons)
        ctx["step_msg"] = new_msg
        ctx["shown_step"] = step_num
        return "advanced"
    except Exception as e:
        logger.error(f"_refresh_fsub_step send failed for {uid}: {e}")
        return "error"


async def not_joined_stepwise(client: Client, message: Message, uid: int):
    """/auto_check ON hone par not_joined() ki jagah ye chalta hai — sirf ek
    (agla pending) channel ka step dikhata hai, sab ek saath nahi.
    Har fresh /start pe pending channels ABHI ke real status se (fresh) compute
    hote hain — taaki agar user pehle link le chuka ho aur baad mein koi channel
    leave kar de, to sirf utne hi (jo abhi sach mein pending hain) steps dikhein,
    purana total nahi."""
    temp = await message.reply("<b><i>ᴡᴀɪᴛ ᴀ sᴇᴄ..</i></b>")
    if not temp:
        return
    try:
        channel_order = await _compute_fresh_pending_order(client, uid)
        ctx = _fsub_context.get(uid)
        if ctx is None:
            try:
                await temp.delete()
            except Exception:
                pass
            return
        ctx["channel_order"] = channel_order
        ctx["total_steps"]   = len(channel_order)

        status = await _refresh_fsub_step(client, uid)
        try:
            await temp.delete()
        except Exception:
            pass
        if status == "error":
            community = await Seishiro.get_community()
            await message.reply_text(f"<b><i>No valid channels found. Contact @{community['username']}</i></b>")
    except Exception as e:
        logger.error(f"not_joined_stepwise error: {e}")
        try:
            await temp.delete()
        except Exception:
            pass


def _start_auto_check_poll(uid: int, client: Client):
    existing = _auto_check_tasks.get(uid)
    if existing and not existing.done():
        return  # is user ke liye pehle se ek poll chal raha hai
    task = asyncio.create_task(_auto_check_poll_loop(client, uid))
    _auto_check_tasks[uid] = task


async def _auto_check_poll_loop(client: Client, uid: int):
    elapsed = 0
    try:
        while elapsed < AUTO_CHECK_MAX_DURATION:
            # Pehle 30 second fast (2s) polling — request/join turant detect ho,
            # uske baad normal (5s) interval taaki rate-limit na lage.
            interval = AUTO_CHECK_FAST_INTERVAL if elapsed < AUTO_CHECK_FAST_WINDOW else AUTO_CHECK_POLL_INTERVAL
            await asyncio.sleep(interval)
            elapsed += interval
            try:
                # Beech mein kisi ne /auto_check off kar diya toh poll rok do
                if not await Seishiro.get_auto_check():
                    return
                status = await _refresh_fsub_step(client, uid)
                if status in ("finished", "no_context"):
                    return
            except Exception as e:
                logger.error(f"auto_check poll error for {uid}: {e}")
                return
    finally:
        _auto_check_tasks.pop(uid, None)


async def notify_fsub_event(client: Client, uid: int):
    """Real-time trigger — jab user kisi channel mein join ya join-request karta hai
    (plugins/approve.py ke on_chat_join_request / on_chat_member_updated se call
    hota hai), tab turant is user ka stepwise step check/advance ho jaata hai.
    Background poll ka wait nahi karna padta. Agar is user ka koi stepwise session
    hi active nahi hai (auto_check OFF ya already complete), to chup-chaap kuch nahi hota."""
    if uid not in _fsub_context:
        return
    try:
        await _refresh_fsub_step(client, uid)
    except Exception as e:
        logger.error(f"notify_fsub_event error for {uid}: {e}")


# /auto_check ON hone par step-message ke "✅ Maine Join Kar Liya" button ka handler.
@Bot.on_callback_query(filters.regex(r"^fsub_stepcheck$"), group=-1)
async def fsub_stepcheck_cb(client: Bot, cq: CallbackQuery):
    uid = cq.from_user.id
    try:
        status = await _refresh_fsub_step(client, uid)

        if status == "finished":
            await cq.answer("🟢 Sabhi steps complete! Link bheji ja rahi hai...")
        elif status == "advanced":
            await cq.answer("🟢 Step complete! Agla step dikh raha hai.")
        elif status == "same":
            await cq.answer(
                "🔴 Abhi tak aapne upar wale channel ko join/request nahi kiya! Pehle join/request karein.",
                show_alert=True
            )
        elif status == "no_context":
            await cq.answer("⚠️ Session expire ho gaya, /start dobara bhejo.", show_alert=True)
        else:
            await cq.answer("⚠️ Error aaya, thodi der baad try karein.", show_alert=True)
    except Exception as e:
        logger.error(f"fsub_stepcheck_cb error: {e}")
        try:
            await cq.answer("⚠️ Error, dobara try karo.", show_alert=True)
        except Exception:
            pass


# ═══════════════════════════════════════════
# FORCE SUBSCRIBE DECORATOR
# ═══════════════════════════════════════════

async def _user_fsub_ok(client, uid):
    channels = await Seishiro.get_fsub_channels()
    if not channels or uid == OWNER_ID:
        return True
    # Premium users FSub bypass karte hain
    if await Seishiro.has_premium_access(uid):
        logger.info(f"User {uid} premium — FSub bypassed")
        return True

    # ── FSUB CHECK DURATION (cooldown) ─────────────────────────
    # ON hone par: agar user ne is duration window (12h/24h/48h/7d)
    # ke andar hi last FSub pass kiya tha, to naya channel add hone
    # par bhi dubara check nahi lagega — turant access mil jaata hai.
    try:
        duration_cfg = await Seishiro.get_fsub_check_duration()
    except Exception as e:
        logger.error(f"fsub_check_duration fetch error: {e}")
        duration_cfg = {"enabled": False, "hours": 0}
    duration_on = bool(duration_cfg.get("enabled")) and duration_cfg.get("hours", 0) > 0

    if duration_on:
        try:
            verified_at = await Seishiro.get_fsub_verified_at(uid)
        except Exception as e:
            logger.error(f"fsub_verified_at fetch error: {e}")
            verified_at = None
        if verified_at and (datetime.utcnow() - verified_at) < timedelta(hours=duration_cfg["hours"]):
            return True

    # ── PARALLEL CHECK (fast) ─────────────────────────────────
    # Sab channels simultaneously check karo — ek ke baad ek nahi
    results = await asyncio.gather(*[_channel_join_status(client, uid, cid) for cid in channels], return_exceptions=True)
    for cid, res in zip(channels, results):
        # Exception aa gayi toh False maano
        sub_ok = res if isinstance(res, bool) else False
        if not sub_ok:
            if await Seishiro.get_channel_mode(cid) == "on":
                # Request mode: ek baar aur check karo (no sleep)
                sub_ok = await _channel_join_status(client, uid, cid)
                if sub_ok:
                    continue
            return False

    # Yahan tak pahunche matlab poora FSub sach mein pass hua — agar
    # cooldown feature ON hai, is waqt ka timestamp save kar do.
    if duration_on:
        try:
            await Seishiro.set_fsub_verified(uid)
        except Exception as e:
            logger.error(f"set_fsub_verified error: {e}")

    return True


def check_fsub(func):
    @wraps(func)
    async def wrapper(client, message, *args, **kwargs):
        uid = message.from_user.id

        # /start premium (text link se) — plans dekhne ke liye FSub nahi
        try:
            _c0 = getattr(message, "command", None)
            if _c0 and _c0[0].lower() == "start" and len(_c0) > 1 and _c0[1] == "premium":
                return await func(client, message, *args, **kwargs)
        except Exception:
            pass

        # Senpai Sync ON ho toh plain /start (ya ref link) par FSub nahi — seedha welcome +
        # "Open Senpai Sync" button. FSub sirf channel-link wale /start par lagega.
        try:
            _cmd = getattr(message, "command", None)
            if _cmd and _cmd[0].lower() == "start":
                _param = _cmd[1] if len(_cmd) > 1 else ""
                if (not _param or _param.startswith("ref_")) and await sync_enabled_and_url():
                    return await func(client, message, *args, **kwargs)
        except Exception as e:
            logger.warning(f"fsub skip check failed: {e}")

        # Link flow: channel link ke liye FSub kab lagana hai (miniapp.py -> Link Flow)
        _link_param = ""
        try:
            _cmd2 = getattr(message, "command", None)
            if _cmd2 and _cmd2[0].lower() == "start" and len(_cmd2) > 1 and not _cmd2[1].startswith("ref_"):
                _link_param = _cmd2[1]
        except Exception:
            _link_param = ""
        _flow = await get_link_flow() if _link_param else ""
        if _flow == "custom":
            # Custom sequence: is open par FSub step hai (aur user join nahi) toh FSub screen, warna FSub entry par nahi
            try:
                if await Seishiro.has_ads_free(uid) or await Seishiro.has_ads_bypass(uid):
                    return await func(client, message, *args, **kwargs)
                _ms = await get_miniapp_settings()
                _step, _ = seq_next(_ms["seq"], await Seishiro.get_link_pos(uid), await _user_fsub_ok(client, uid))
            except Exception as e:
                logger.warning(f"custom flow peek failed: {e}")
                _step = "ads"
            if _step == "fsub":
                _flow = "fsub_ads"          # neeche wala FSub screen + fsub_pending wala raasta
            else:
                return await func(client, message, *args, **kwargs)
        if _flow in ("ads_fsub", "ads_only"):
            # Entry par FSub nahi: "ads_only" mein kabhi nahi, "ads_fsub" mein ads ke baad (neeche link branch / Mini App complete)
            return await func(client, message, *args, **kwargs)

        async def is_subscribed(uid):
            return await _user_fsub_ok(client, uid)

        try:
            if not await is_subscribed(uid):
                if _flow == "fsub_ads":
                    await Seishiro.set_fsub_pending(uid)    # FSub ke baad pehli baar seedha link (ads nahi)
                # Smart auto-check: sirf ON hone par hi step-by-step flow +
                # background poll lagta hai. OFF (default) hone par bilkul
                # pehle jaisa not_joined() (sab channels ek saath) chalta hai.
                try:
                    auto_on = await Seishiro.get_auto_check()
                except Exception as e:
                    logger.error(f"auto_check fetch error: {e}")
                    auto_on = False

                if auto_on:
                    _fsub_context[uid] = {
                        "message": message, "func": func, "args": args, "kwargs": kwargs,
                        "step_msg": None, "shown_step": None,
                    }
                    await not_joined_stepwise(client, message, uid)
                    _start_auto_check_poll(uid, client)
                    return
                return await not_joined(client, message)
            return await func(client, message, *args, **kwargs)
        except Exception as e:
            logger.error(f"check_fsub error: {e}")
            await message.reply_text("An unexpected error occurred. Please contact the developer.")
    return wrapper


class _UserMsg:
    """Message jaisa object — Mini App complete hone par FSub screen bhejne ke liye (not_joined ko chahiye)."""
    def __init__(self, client, user, payload: str):
        self._c = client
        self.from_user = user
        self.command = ["start", payload]
        self.text = f"/start {payload}"

    async def reply(self, text, **kw):
        return await self._c.send_message(self.from_user.id, text, **{k: v for k, v in kw.items() if k == "reply_markup"})

    reply_text = reply

    async def reply_photo(self, photo, caption=None, reply_markup=None, **kw):
        return await self._c.send_photo(self.from_user.id, photo=photo, caption=caption, reply_markup=reply_markup)

    async def reply_chat_action(self, action):
        try:
            await self._c.send_chat_action(self.from_user.id, action)
        except Exception:
            pass


async def _fsub_gate(client, message) -> bool:
    """FSub pass ho toh True. Warna FSub screen dikha ke False (Joined button wapas isi link par laata hai)."""
    if await _user_fsub_ok(client, message.from_user.id):
        return True
    await not_joined(client, message)
    return False


# ═══════════════════════════════════════════
# NOT JOINED
# ═══════════════════════════════════════════

async def not_joined(client: Client, message: Message):
    uid  = message.from_user.id
    temp = await message.reply("<b><i>ᴡᴀɪᴛ ᴀ sᴇᴄ..</i></b>")
    if not temp:
        return

    buttons    = []
    ch_buttons = []     # channel buttons alag collect hote hain taaki layout (1/2 per row) lag sake
    count      = 0
    layout     = await Seishiro.get_fsub_layout()

    try:
        channels = await Seishiro.get_fsub_channels()
        # Position map: jo channel pehle add hua uska 01, baad mein add hua uska 02...
        # (get_fsub_channels() ab created_at ke hisaab se sorted aata hai)
        position_map = {cid: idx for idx, cid in enumerate(channels, start=1)}

        # Multi fake links with row positioning (Jojo system)
        if channels:
            fake_links = await Seishiro.get_fake_links()
            for fake in fake_links:
                pos = max(0, min(int(fake.get("row", 1)) - 1, len(buttons)))
                buttons.insert(pos, [InlineKeyboardButton(text=fake["button_text"], url=fake["url"])])

        for cid in channels:
            await message.reply_chat_action(ChatAction.TYPING)

            is_member = False
            try:
                m         = await _safe_get_member(client, cid, uid)
                is_member = m.status in {
                    ChatMemberStatus.OWNER,
                    ChatMemberStatus.ADMINISTRATOR,
                    ChatMemberStatus.MEMBER
                }
            except UserNotParticipant:
                pass
            except Exception as e:
                logger.error(f"Member check {cid}: {e}")

            if is_member:
                continue

            # Request mode: agar user pehle se hi is channel pe join-request
            # bhej chuka hai, toh yeh channel dobara button list mein nahi
            # aana chahiye — chahe koi naya fsub channel add kyun na hua ho.
            try:
                if await Seishiro.get_channel_mode(cid) == "on" and await Seishiro.req_user_exist(cid, uid):
                    continue
            except Exception as e:
                logger.error(f"Req-exist check {cid}: {e}")

            try:
                if cid in chat_data_cache:
                    data = chat_data_cache[cid]
                else:
                    try:
                        data = await _safe_get_chat(client, cid)
                        chat_data_cache[cid] = data
                    except PeerIdInvalid:
                        if not await _force_resolve_peer(client, cid):
                            continue
                        data = await _safe_get_chat(client, cid)
                        chat_data_cache[cid] = data

                mode = await Seishiro.get_channel_mode(cid)
                if data.username:
                    link = f"https://t.me/{data.username}"
                else:
                    # ── PERMANENT link: ek hi channel ke liye ek hi link, koi expiry/timer nahi ──
                    # (mode == "on" -> single permanent REQUEST link, warna single permanent JOIN link)
                    link = await _get_persistent_fsub_link(client, cid, is_request=(mode == "on"))
                    if not link:
                        continue

                # Custom name check — agar set hai toh wahi use karo, warna default naam:
                # Request mode ON  -> "⚡ Request channel 01 ⚡"
                # Request mode OFF -> "⚡ Join channel 01 ⚡"
                # (number = channel add hone ka order, pehla channel = 01, dusra = 02...)
                custom_name = await Seishiro.get_fsub_channel_name(cid)
                if custom_name:
                    btn_text = custom_name
                else:
                    pos = position_map.get(cid, count + 1)
                    if layout == 2:
                        # 2-per-row: chhota label taaki half-width button mein fit ho
                        btn_text = f"⚡ {'Req' if mode == 'on' else 'Join'} Channel {pos} ⚡"
                    else:
                        label = "Request" if mode == "on" else "Join"
                        btn_text = f"⚡ {label} channel {pos:02d} ⚡"
                ch_buttons.append(InlineKeyboardButton(text=btn_text, url=link))
                count += 1
                try:
                    await temp.edit(f"<b>{'! ' * count}</b>")
                except Exception:
                    pass

            except Exception as e:
                logger.error(f"FSub button error {cid}: {e}")
                continue

        if layout == 2:
            for i in range(0, len(ch_buttons), 2):
                buttons.append(ch_buttons[i:i + 2])    # aakhri odd button akela (full width)
        else:
            for b in ch_buttons:
                buttons.append([b])

        try:
            buttons.append([InlineKeyboardButton(
                text='• Jᴏɪɴᴇᴅ •',
                url=f"https://t.me/{client.username}?start={message.command[1]}"
            )])
        except (IndexError, AttributeError):
            pass

        if not buttons:
            community = await Seishiro.get_community()
            return await temp.edit(f"<b><i>No valid channels found. Contact @{community['username']}</i></b>")

        try:
            await temp.delete()
        except Exception:
            pass

        _custom = ((await Seishiro.get_fsub_ui()).get("text") or "").strip()
        _caption = render_fsub_text(_custom, message.from_user) if _custom else (
            "<b>Welcome! 😁\n\n"
            "<blockquote>Links pane ke liye niche diye gaye "
            "channels join karein ya request karein.</blockquote></b>"
        )
        await _send_fsub_ui(message, _caption, InlineKeyboardMarkup(buttons))

        # ── FSub Tutorial: 30s baad check, join nahi kiya toh video ──
        async def _check_joined_all(check_uid: int) -> bool:
            try:
                chs = await Seishiro.get_fsub_channels()
                for cid in chs:
                    try:
                        m = await _safe_get_member(client, cid, check_uid)
                        if m.status not in {
                            ChatMemberStatus.OWNER,
                            ChatMemberStatus.ADMINISTRATOR,
                            ChatMemberStatus.MEMBER,
                        }:
                            return False
                    except Exception:
                        if await Seishiro.get_channel_mode(cid) == "on":
                            if not await Seishiro.req_user_exist(cid, check_uid):
                                return False
                        else:
                            return False
                return True
            except Exception:
                return False

        asyncio.create_task(
            send_fsub_tutorial_if_not_joined(client, uid, _check_joined_all)
        )

    except Exception as e:
        logger.error(f"not_joined error: {e}")
        try:
            community = await Seishiro.get_community()
            await temp.edit(f"<b><i>Error! Contact @{community['username']}</i></b>\n<blockquote expandable>{e}</blockquote>")
        except Exception:
            pass


# ═══════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════

async def _resolve_peer_safe(client: Bot, channel_id: int) -> bool:
    """Peer resolve karo — PeerIdInvalid pe deep resolve, FloodWait pe retry."""
    try:
        await _safe_get_chat(client, channel_id)
        return True
    except PeerIdInvalid:
        return await _force_resolve_peer(client, channel_id)
    except Exception:
        return True  # Other errors — channel exist karta hai


async def _get_fresh_invite_link(client: Bot, channel_id: int, is_request: bool) -> str | None:
    """
    Fresh invite link banao aur DB mein save karo.
    4 minute ke andar purana link reuse hoga.
    """
    async with channel_locks[channel_id]:
        old = await Seishiro.get_current_invite_link(channel_id)
        if old:
            ch  = await Seishiro.channel_data.find_one({"channel_id": channel_id})
            cat = ch.get("invite_link_created_at") if ch else None
            # Cached link sirf tab reuse karo jab type (join/request) bhi match kare —
            # warna dusre mode ka link galat type mein sabko mil jayega (conflict).
            if cat and old.get("is_request") == is_request and (datetime.now() - cat).total_seconds() < 240:
                return old["invite_link"]
            try:
                await client.revoke_chat_invite_link(channel_id, old["invite_link"])
            except Exception:
                pass

        try:
            for attempt in range(3):
                try:
                    inv  = await client.create_chat_invite_link(
                        chat_id=channel_id,
                        expire_date=datetime.now() + timedelta(minutes=5),
                        creates_join_request=is_request
                    )
                    await Seishiro.save_invite_link(channel_id, inv.invite_link, is_request)
                    return inv.invite_link
                except FloodWait as fw:
                    wait = fw.value + 2
                    logger.warning(f"FloodWait {wait}s on create_invite_link({channel_id}), attempt {attempt+1}/3")
                    await asyncio.sleep(wait)
            logger.error(f"create_invite_link({channel_id}) failed after 3 retries")
            return None
        except Exception as e:
            logger.error(f"create_invite_link failed {channel_id}: {e}")
            return None


async def _get_persistent_fsub_link(client: Bot, channel_id: int, is_request: bool) -> str | None:
    """
    FSub channel ke liye EK PERMANENT invite link banao — koi expire_date nahi,
    koi 4-minute rotation nahi. Ek baar ban gaya toh hamesha wahi ek link reuse
    hoga aur usi se sab users join/request karenge (Telegram admin panel mein
    bhi koi expiry timer nahi dikhega).

    Sirf FSub button banane ke liye use hota hai (not_joined). Link-sharing
    feature (verify/premium/shortener flow) apna _get_fresh_invite_link() hi
    use karta rehta hai — us feature se koi conflict nahi hai.
    """
    async with channel_locks[channel_id]:
        old = await Seishiro.get_current_invite_link(channel_id)
        if old and old.get("invite_link"):
            # Mode (join/request) same hai toh purana permanent link seedha reuse karo.
            if old.get("is_request") == is_request:
                return old["invite_link"]
            # Mode badla (join <-> request) — purana revoke karke naya permanent link banao.
            try:
                await client.revoke_chat_invite_link(channel_id, old["invite_link"])
            except Exception:
                pass

        try:
            for attempt in range(3):
                try:
                    inv = await client.create_chat_invite_link(
                        chat_id=channel_id,
                        creates_join_request=is_request
                        # expire_date jaan-bujhkar NAHI diya — link permanent rahega.
                    )
                    await Seishiro.save_invite_link(channel_id, inv.invite_link, is_request)
                    return inv.invite_link
                except FloodWait as fw:
                    wait = fw.value + 2
                    logger.warning(f"FloodWait {wait}s on create_invite_link({channel_id}), attempt {attempt+1}/3")
                    await asyncio.sleep(wait)
            logger.error(f"create_invite_link({channel_id}) failed after 3 retries")
            return None
        except Exception as e:
            logger.error(f"create_invite_link failed {channel_id}: {e}")
            return None


async def _send_invite_msg(message: Message, invite_link: str):
    """Direct invite link bhejo (premium user ya shortener off)."""
    try:
        await _clear_flow_msgs(message._client, message.from_user.id)
    except Exception:
        pass
    wait = await message.reply_text("<b><i>ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ...</i></b>")
    await asyncio.sleep(0.5)
    await wait.delete()

    link_msg = await message.reply_text(
        "<b><blockquote expandable>ʜᴇʀᴇ ɪs ʏᴏᴜʀ ʟɪɴᴋ! ᴄʟɪᴄᴋ ʙᴇʟᴏᴡ ᴛᴏ ᴘʀᴏᴄᴇᴇᴅ</blockquote></b>",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("• ᴄʟɪᴄᴋ ʜᴇʀᴇ •", url=invite_link)
        ]])
    )
    asyncio.create_task(delete_after_delay(link_msg, 300))
    return link_msg  # caller ke liye return karo taaki ID save ho sake


async def delete_after_delay(msg, delay: int):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except Exception:
        pass


# ═══════════════════════════════════════════
# VERIFY TOKEN HANDLER
# User shortener complete karke vfy_<token> ke
# saath bot pe aata hai
# ═══════════════════════════════════════════

async def _handle_verify_token(client: Bot, message: Message, uid: int, token: str):
    """
    Flow:
    1. Token DB mein dhundo
    2. Already used? → reject
    3. Dusre user ka token? → reject
    4. Temp premium do (setverifytime duration)
    5. Fresh invite link banao aur do
    6. Token mark used
    """
    doc = await Seishiro.get_verify_token(token)

    if not doc:
        return await message.reply_text(
            "<b><blockquote expandable>"
            "⚠️ Invalid ya expired verification link.\n\n"
            "Dobara try karo — original link pe click karo."
            "</blockquote></b>"
        )

    if doc.get("used"):
        return await message.reply_text(
            "<b><blockquote expandable>"
            "⚠️ Yeh link pehle use ho chuka hai.\n\n"
            "Dobara channel link pane ke liye original link pe click karo."
            "</blockquote></b>"
        )

    if doc.get("user_id") and doc["user_id"] != uid:
        return await message.reply_text(
            "<b><blockquote expandable>"
            "⚠️ Yeh link tumhare liye nahi hai."
            "</blockquote></b>"
        )

    channel_id = doc["channel_id"]
    is_request = doc.get("is_request", False)

    # Temp premium duration
    cfg     = await _get_bot_config()
    seconds = cfg.get("verify_premium_seconds", 86400)  # default 24h

    # Temp premium do
    await Seishiro.add_premium(uid, seconds)
    logger.info(f"Temp premium: user={uid}, seconds={seconds}, channel={channel_id}")

    # Peer resolve
    await _resolve_peer_safe(client, channel_id)

    # Fresh invite link
    invite_link = await _get_fresh_invite_link(client, channel_id, is_request)
    if not invite_link:
        return await message.reply_text(
            "<b><blockquote expandable>"
            "✅ Verified! Lekin invite link banane mein error.\n"
            "Dobara try karein."
            "</blockquote></b>"
        )

    # Token use mark karo
    await Seishiro.mark_token_used(token)

    hours = seconds // 3600
    mins  = (seconds % 3600) // 60
    dur   = f"{hours}h" if mins == 0 else f"{hours}h {mins}m"

    link_msg = await message.reply_text(
        f"✅ <b>Verified! Yeh raha aapka link:</b>\n\n"
        f"<blockquote>"
        f"⚡ Agle <b>{dur}</b> tak direct links milenge — koi ads nahi, koi FSub nahi!\n"
        f"Time khatam hone ke baad dobara shortener complete karna padega.\n\n"
        f"💎 Hamesha ads-free rehne ke liye <b>Premium</b> lo!"
        f"</blockquote>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("• ᴄʟɪᴄᴋ ʜᴇʀᴇ •", url=invite_link)],
            [InlineKeyboardButton("💎 Buy Premium", callback_data="prem_plans")],
        ])
    )

    # 5 min baad sirf message delete karo — link ko FORCE revoke NAHI karna,
    # kyunki yeh SAME shared invite link fsub gate aur doosre users ke saath
    # bhi cached/shared hota hai. Force-revoke karne se dusre features (fsub
    # gate, doosre users ka same-link) achanak toot jaate the — conflict bug.
    # Link apne aap hi _get_fresh_invite_link() se 4 min baad naturally rotate
    # ho jaata hai jab agla request aata hai.
    async def cleanup():
        await asyncio.sleep(300)
        try:
            await link_msg.delete()
        except Exception:
            pass

    asyncio.create_task(cleanup())


# ═══════════════════════════════════════════
# MINI APP COMPLETE HANDLER
# Mini App mein saare ads dekh liye → backend (plugins/route.py)
# yeh function call karta hai → user ko bot chat mein link milta hai
# ═══════════════════════════════════════════

async def _extend_free(uid: int, seconds: int) -> None:
    """Free access sirf badhao — kabhi kam mat karo (lambi premium ko overwrite nahi karta)."""
    if seconds <= 0:
        return
    cur = await Seishiro.get_premium_expiry(uid)
    target = datetime.now() + timedelta(seconds=seconds)
    if isinstance(cur, datetime) and cur >= target:
        return
    await Seishiro.add_premium(uid, seconds)


async def complete_miniapp_verification(client: Bot, uid: int, token: str, shown: int = 1) -> tuple[bool, str, dict]:
    """
    Returns (ok, reason, info).  reason: "ok" | "invalid_or_used" | "invite_error"
    info: {"daily_count", "goal", "goal_reached", "fsub_required"}
    Token atomically claim hota hai, isliye double submit se 2 links nahi jaate.

    Link flow "Ads first, then FSub": ads phase poora hote hi (daily goal ya goal OFF) FSub check hota hai —
    pass nahi hua toh link ki jagah FSub screen jati hai; Joined dabane par link milta hai.
    """
    doc = await Seishiro.claim_verify_token(token, uid)
    if not doc:
        return False, "invalid_or_used", {}

    channel_id = doc["channel_id"]
    is_request = doc.get("is_request", False)
    b64        = doc.get("b64", "")
    shown      = max(1, shown)

    ms    = await get_miniapp_settings()
    flow  = ms["flow"]
    goal  = ms["daily_goal"]
    prior = await Seishiro.get_miniapp_daily_count(uid)
    phase1_done = goal == 0 or (prior + shown) >= goal           # ads phase poora hua?
    fsub_ok = True
    if flow == "ads_fsub" and phase1_done:
        fsub_ok = await _user_fsub_ok(client, uid)

    invite_link = None
    if fsub_ok:
        await _resolve_peer_safe(client, channel_id)
        invite_link = await _get_fresh_invite_link(client, channel_id, is_request)
        if not invite_link:
            await Seishiro.unclaim_verify_token(token)           # user dobara try kar sake
            return False, "invite_error", {}

    # ── Daily goal / ads-free time (hamesha ads-free, premium nahi: FSub flow ke hisaab se lagta hai) ──
    daily_count = await Seishiro.add_miniapp_progress(uid, shown)
    goal_hit    = False
    # Per-session ads: agla session ads list mein is session ke baad se shuru hoga
    try:
        _all = build_steps(ms["ads"])
        if _all and doc.get("mini_n"):
            await Seishiro.set_ad_cursor(uid, (int(doc.get("mini_cursor", 0)) + int(doc["mini_n"])) % len(_all))
    except Exception as e:
        logger.warning(f"ad cursor advance failed: {e}")
    if flow == "custom":
        # Custom sequence: ek ads-session = ek step. Aakhri step ke baad free time, fir dobara 1st se.
        _seq = ms["seq"]
        _np  = seq_index(_seq, "ads", await Seishiro.get_link_pos(uid)) + 1
        if _np >= len(_seq):
            await Seishiro.set_ads_free(uid, ms["seq_free"]); _np = 0
        await Seishiro.set_link_pos(uid, _np)
    elif goal > 0:
        if daily_count >= goal:
            goal_hit = True
            await Seishiro.set_ads_free(uid, ms["goal_reward_seconds"])
            await Seishiro.reset_miniapp_progress(uid)
    else:
        await Seishiro.set_ads_free(uid, ms["free_seconds"])
    logger.info(f"MiniApp verified: user={uid}, channel={channel_id}, shown={shown}, "
                f"daily={daily_count}/{goal}, goal_hit={goal_hit}, flow={flow}, fsub_ok={fsub_ok}")

    # ── Purana "Watch Video Ad" wala message delete ──
    try:
        if doc.get("prompt_msg_id"):
            await client.delete_messages(doc.get("prompt_chat_id", uid), doc["prompt_msg_id"])
    except Exception as e:
        logger.warning(f"prompt msg delete failed: {e}")

    info = {"daily_count": daily_count, "goal": goal, "goal_reached": goal_hit, "fsub_required": not fsub_ok}

    if not fsub_ok:
        # Ads ho gaye, ab FSub: screen bhejo. Joined -> /start payload -> ads-free + FSub ok -> direct link
        try:
            user = await client.get_users(uid)
            payload = ("req_" + b64) if is_request else b64
            await not_joined(client, _UserMsg(client, user, payload))
        except Exception as e:
            logger.error(f"fsub screen after ads failed: {e}", exc_info=True)
        return True, "ok", info

    # Pehle ke FSub/welcome messages hatao, phir link bilkul NAYE message mein
    await _clear_flow_msgs(client, uid)

    # ── Normal-style link message (sirf CLICK HERE button) ──
    link_msg = await client.send_message(
        uid,
        "<b><blockquote expandable>ʜᴇʀᴇ ɪs ʏᴏᴜʀ ʟɪɴᴋ! ᴄʟɪᴄᴋ ʙᴇʟᴏᴡ ᴛᴏ ᴘʀᴏᴄᴇᴇᴅ</blockquote></b>",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("• ᴄʟɪᴄᴋ ʜᴇʀᴇ •", url=invite_link)
        ]])
    )
    asyncio.create_task(delete_after_delay(link_msg, 300))

    info["invite_link"] = invite_link      # Mini App ka success screen bhi isi link ka button dikhata hai

    # ── Request-mode: approve notification ke liye link save (normal flow jaisa) ──
    if is_request and b64:
        try:
            await Seishiro.save_user_request_link(
                uid, channel_id, b64,
                link_msg_id=link_msg.id, link_chat_id=link_msg.chat.id, invite_link=invite_link
            )
        except Exception as e:
            logger.warning(f"save_user_request_link failed: {e}")

    return True, "ok", info


async def complete_via_fallback(client: Bot, uid: int, token: str) -> tuple[bool, str, dict]:
    """
    Ads load nahi hue / black screen: user "Continue without ads" dabata hai.
    FSub pass hai toh seedha link, warna FSub screen (Joined ke baad seedha link, ads nahi).
    Din mein limited baar (Ad Fallback setting); ads-free time / daily goal nahi milta.
    """
    ms = await get_miniapp_settings()
    limit = ms["fb_daily"]
    if limit <= 0:
        return False, "fb_disabled", {}
    if not await Seishiro.fallback_use(uid, limit):
        return False, "fb_limit", {}
    doc = await Seishiro.claim_verify_token(token, uid)
    if not doc:
        return False, "invalid_or_used", {}

    channel_id = doc["channel_id"]
    is_request = doc.get("is_request", False)
    b64        = doc.get("b64", "")
    fsub_ok    = await _user_fsub_ok(client, uid)

    invite_link = None
    if fsub_ok:
        await _resolve_peer_safe(client, channel_id)
        invite_link = await _get_fresh_invite_link(client, channel_id, is_request)
        if not invite_link:
            await Seishiro.unclaim_verify_token(token)
            return False, "invite_error", {}
    else:
        await Seishiro.set_ads_bypass(uid, 1800)       # Joined ke baad link: ads dobara nahi

    logger.info(f"MiniApp fallback: user={uid}, channel={channel_id}, fsub_ok={fsub_ok}")

    try:
        if doc.get("prompt_msg_id"):
            await client.delete_messages(doc.get("prompt_chat_id", uid), doc["prompt_msg_id"])
    except Exception as e:
        logger.warning(f"prompt msg delete failed: {e}")

    if not fsub_ok:
        try:
            user = await client.get_users(uid)
            payload = ("req_" + b64) if is_request else b64
            await not_joined(client, _UserMsg(client, user, payload))
        except Exception as e:
            logger.error(f"fsub screen after fallback failed: {e}", exc_info=True)
        return True, "ok", {"fsub_required": True, "fallback": True}

    await _clear_flow_msgs(client, uid)
    link_msg = await client.send_message(
        uid,
        "<b><blockquote expandable>ʜᴇʀᴇ ɪs ʏᴏᴜʀ ʟɪɴᴋ! ᴄʟɪᴄᴋ ʙᴇʟᴏᴡ ᴛᴏ ᴘʀᴏᴄᴇᴇᴅ</blockquote></b>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("• ᴄʟɪᴄᴋ ʜᴇʀᴇ •", url=invite_link)]])
    )
    asyncio.create_task(delete_after_delay(link_msg, 300))
    if is_request and b64:
        try:
            await Seishiro.save_user_request_link(
                uid, channel_id, b64,
                link_msg_id=link_msg.id, link_chat_id=link_msg.chat.id, invite_link=invite_link)
        except Exception as e:
            logger.warning(f"save_user_request_link failed: {e}")
    return True, "ok", {"invite_link": invite_link, "fallback": True}


# ═══════════════════════════════════════════
# /start COMMAND
# ═══════════════════════════════════════════

@Bot.on_message(filters.command('start') & filters.private)
@check_fsub
async def start_command(client: Bot, message: Message):
    uid = message.from_user.id

    # Ban check
    if await Seishiro.is_user_banned(uid):
        community = await Seishiro.get_community()
        return await message.reply_text(
            "🚫 Yᴏᴜ ᴀʀᴇ ʙᴀɴɴᴇᴅ!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Contact", url=community["link"])
            ]])
        )

    await Seishiro.add_user(uid, message)

    try:
        text = message.text

        # ── /start premium: plans screen ───────────────────────────────
        if len(text) > 7 and text.split(" ", 1)[1].strip() == "premium":
            from plugins.premium import _build_plans_ui
            caption, kb, ui = await _build_plans_ui()
            try:
                await message.reply_photo(photo=ui["sub_img"], caption=caption, reply_markup=kb)
            except Exception:
                await message.reply_text(caption, reply_markup=kb)
            return

        # ── Referral (/start ref_<uid>): Senpai Sync login + referrer save, phir normal welcome ──
        if len(text) > 7 and text.split(" ", 1)[1].startswith("ref_"):
            await sync_register_from_bot(message.from_user, text.split(" ", 1)[1][4:])
            text = "/start"

        # ── Deep link ─────────────────────────────────────────────────
        if len(text) > 7:
            try:
                param = text.split(" ", 1)[1]

                # ── Verify token (shortener complete ke baad) ──────────
                if param.startswith("vfy_"):
                    return await _handle_verify_token(client, message, uid, param[4:])

                # ── Normal encoded channel link ────────────────────────
                is_request = param.startswith("req_")
                b64        = param[4:] if is_request else param

                try:
                    channel_id = int(await decode(b64))
                except Exception as e:
                    logger.error(f"Decode failed: {e}")
                    return await message.reply_text(
                        "<b><blockquote expandable>Invalid or expired invite link.</blockquote></b>"
                    )

                if not channel_id or channel_id > 0:
                    return await message.reply_text(
                        "<b><blockquote expandable>Invalid or expired invite link.</blockquote></b>"
                    )

                # ── Channel Alias Check ────────────────────────────────
                # Agar purana channel ban ho gaya aur alias set hai,
                # toh silently naye channel pe redirect karo
                alias_id = await Seishiro.get_channel_alias(channel_id)
                if alias_id:
                    logger.info(f"Alias redirect: {channel_id} → {alias_id}")
                    channel_id = alias_id

                # Channel DB mein save
                if not await Seishiro.channel_data.find_one({"channel_id": channel_id}):
                    await Seishiro.save_channel(channel_id)

                # ── Request link save karo for approve notification ────
                if is_request:
                    await Seishiro.save_user_request_link(uid, channel_id, b64)

                # Peer resolve
                try:
                    chat = await _safe_get_chat(client, channel_id)
                    logger.info(f"Peer OK: {channel_id} → {chat.title}")
                except PeerIdInvalid:
                    if not await _force_resolve_peer(client, channel_id):
                        return await message.reply_text(
                            "<b><blockquote expandable>"
                            "⚠️ Channel resolve nahi hua. Bot ko admin banao aur dobara try karo."
                            "</blockquote></b>"
                        )
                except Exception as e:
                    return await message.reply_text(
                        f"<b><blockquote expandable>Channel error: {str(e)[:80]}</blockquote></b>"
                    )

                # Admin check
                is_admin_ch, can_invite, reason = await check_bot_permissions(client, channel_id)
                if not is_admin_ch:
                    return await message.reply_text(
                        f"<b><blockquote expandable>⚠️ Bot admin nahi hai.\nKaaran: {reason}</blockquote></b>"
                    )
                if not can_invite:
                    return await message.reply_text(
                        "<b><blockquote expandable>⚠️ Bot ko 'Invite Users' permission chahiye.</blockquote></b>"
                    )

                # Encoded link save
                if is_request:
                    await Seishiro.save_encoded_link2(channel_id, b64)
                else:
                    await Seishiro.save_encoded_link(channel_id)

                # Original link check
                orig = await Seishiro.get_original_link(channel_id)
                if orig:
                    return await message.reply_text(
                        "<b><blockquote expandable>Your channel link 👇</blockquote></b>",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("• ᴄʟɪᴄᴋ ʜᴇʀᴇ •", url=orig)
                        ]])
                    )

                # ── Link flow: kab direct link, kab ads ───────────────
                flow     = await get_link_flow()
                _premium = await Seishiro.has_premium_access(uid)
                direct   = _premium or flow == "fsub_only"            # fsub_only: ads kabhi nahi
                if not direct and await Seishiro.has_ads_bypass(uid):
                    # "Continue without ads" (ads fail hue the): FSub pass karo -> seedha link
                    if not await _fsub_gate(client, message):
                        return
                    await Seishiro.pop_ads_bypass(uid)
                    direct = True
                if not direct and await Seishiro.has_ads_free(uid):   # ads-free time chal raha hai
                    if flow == "ads_fsub" and not await _fsub_gate(client, message):
                        return                                         # FSub screen dikha di
                    direct = True
                if not direct and flow == "fsub_ads" and await Seishiro.pop_fsub_pending(uid):
                    direct = True                                      # FSub abhi complete hua -> seedha link

                # ── Custom sequence (miniapp.py -> Link Flow -> Custom) ──
                if not direct and flow == "custom":
                    _ms   = await get_miniapp_settings()
                    _seq  = _ms["seq"]
                    _pos  = await Seishiro.get_link_pos(uid)
                    if await Seishiro.has_ads_free(uid):               # free time chal raha hai
                        direct = True
                    elif await Seishiro.pop_fsub_pending(uid):         # FSub step abhi complete hua -> seedha link
                        _np = seq_index(_seq, "fsub", _pos) + 1
                        direct = True
                        if _np >= len(_seq):
                            await Seishiro.set_ads_free(uid, _ms["seq_free"]); _np = 0
                        await Seishiro.set_link_pos(uid, _np)
                    else:
                        _step, _i = seq_next(_seq, _pos, await _user_fsub_ok(client, uid))
                        if _step == "free":                            # baaki saare steps skip hue (FSub already joined)
                            await Seishiro.set_ads_free(uid, _ms["seq_free"])
                            await Seishiro.set_link_pos(uid, 0)
                            direct = True
                        elif _step == "fsub":                          # wrapper ne screen nahi dikhayi (edge case)
                            if not await _fsub_gate(client, message):
                                await Seishiro.set_fsub_pending(uid)
                                return
                            await Seishiro.set_link_pos(uid, _i + 1 if _i + 1 < len(_seq) else 0)
                            direct = True
                        # _step == "ads" -> neeche Mini App (Watch Video Ad)

                # ── Premium / ads-free / flow ke hisaab se → direct link ──
                if direct:
                    inv = await _get_fresh_invite_link(client, channel_id, is_request)
                    if not inv:
                        return await message.reply_text(
                            "<b><blockquote expandable>Invite link error. Dobara try karein.</blockquote></b>"
                        )
                    sent = await _send_invite_msg(message, inv)
                    if is_request and sent:
                        await Seishiro.save_user_request_link(
                            uid, channel_id, b64,
                            link_msg_id=sent.id,
                            link_chat_id=sent.chat.id,
                            invite_link=inv
                        )
                    return

                # ── Free user → Mini App (Watch Video Ad) flow ─────────
                # Mini App ON ho toh shortener ki jagah yahi chalega.
                if await miniapp_ready():
                    ms    = await get_miniapp_settings()
                    token = secrets.token_urlsafe(12)
                    await Seishiro.create_verify_token(uid, channel_id, token, is_request, b64)
                    web_url = f"{ms['url']}/miniapp?t={token}"
                    _tut = (await _get_bot_config()).get("miniapp_tutorial")
                    _rows = [[InlineKeyboardButton("Watch Video Ad", web_app=WebAppInfo(url=web_url))]]
                    if _tut and _tut.get("kind") == "link" and _tut.get("url"):
                        _rows.append([InlineKeyboardButton("How to watch ads", url=_tut["url"])])
                    elif _tut:
                        _rows.append([InlineKeyboardButton("How to watch ads", callback_data="ads_tut")])
                    prompt_msg = await message.reply_text(
                        "<b>Your link is ready</b>\n\n"
                        "<blockquote>Tap <b>Watch Video Ad</b>, finish the short ads in the Mini App "
                        "and your channel link will arrive in this chat automatically.\n\n"
                        f"<a href=\"https://t.me/{client.username}?start=premium\">Premium</a> users skip this step."
                        "</blockquote>",
                        reply_markup=InlineKeyboardMarkup(_rows)
                    )
                    await Seishiro.set_token_prompt(token, prompt_msg.chat.id, prompt_msg.id)
                    return

                # ── Free user → shortener flow ─────────────────────────
                cfg          = await _get_bot_config()
                shortener_on = cfg.get("shortener_enabled", False) and bool(cfg.get("shortener_api"))

                if not shortener_on:
                    # Shortener off — direct link do
                    inv = await _get_fresh_invite_link(client, channel_id, is_request)
                    if not inv:
                        return await message.reply_text(
                            "<b><blockquote expandable>Invite link error. Dobara try karein.</blockquote></b>"
                        )
                    sent = await _send_invite_msg(message, inv)
                    if is_request and sent:
                        await Seishiro.save_user_request_link(
                            uid, channel_id, b64,
                            link_msg_id=sent.id,
                            link_chat_id=sent.chat.id,
                            invite_link=inv
                        )
                    return

                # Shortener ON:
                # 1. Token banao
                # 2. Bot verify link → shortener se pass karo
                # 3. User ko shortened URL do
                # 4. User ad complete kare → vfy_<token> pe aaye → temp premium + fresh link
                token = secrets.token_urlsafe(12)
                await Seishiro.create_verify_token(uid, channel_id, token)

                bot_link  = f"https://t.me/{client.username}?start=vfy_{token}"
                short_url = await shorten_link(bot_link)
                logger.info(f"Shortener URL for user {uid}, channel {channel_id}")

                await message.reply_text(
                    "<b>🔗 Aapka Link Ready Hai!</b>\n\n"
                    "<blockquote>"
                    "Niche button pe click karo.\n"
                    "Short ad complete karne ke baad automatically "
                    "channel link mil jayega — <b>koi waiting nahi!</b>\n\n"
                    "⚡ <b>Premium users</b> ko yeh step kabhi nahi karna padta!"
                    "</blockquote>",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔗 Get Channel Link", url=short_url)],
                        [InlineKeyboardButton("💎 Buy Premium — No Ads Ever", callback_data="prem_plans")],
                    ])
                )

                # ── LinkShortner Tutorial: 30s baad check ──
                asyncio.create_task(
                    send_linkshortner_tutorial_if_not_verified(client, uid, token)
                )

            except Exception as e:
                logger.error(f"Deep link error: {e}", exc_info=True)
                await message.reply_text(
                    "<b><blockquote expandable>Invalid or expired invite link.</blockquote></b>"
                )

        # ── Normal /start ──────────────────────────────────────────────
        else:
            # Senpai Sync ON ho toh bot start par login + Mini App ka button
            sync_url = await sync_enabled_and_url()
            if sync_url:
                await sync_register_from_bot(message.from_user)
            text, markup, _ = await intro_message(message.from_user)
            await message.reply_text(text, reply_markup=markup, disable_web_page_preview=True)

    except Exception as e:
        logger.error(f"FATAL start_command: {e}", exc_info=True)
        await message.reply_text("<b>Unexpected error. Please try again later.</b>")


# ═══════════════════════════════════════════
# BROADCAST
# ═══════════════════════════════════════════

@Bot.on_message(filters.command("broadcast") & filters.private & admin)
async def broadcast_handler(bot: Client, m: Message):
    try:
        if not m.reply_to_message:
            return await m.reply_text("<b>⚠️ Reply to a message and use /broadcast</b>")

        try:
            all_users = await Seishiro.get_all_users()
        except Exception as e:
            return await m.reply_text(f"<b>❌ Error fetching users: {e}</b>")

        msg     = m.reply_to_message
        sts_msg = await m.reply_text("📤 Broadcast started...")

        done = failed = success = 0
        start_time = time.time()

        try:
            total = await Seishiro.total_users_count()
        except Exception:
            total = 0

        async for user in all_users:
            try:
                sts = await send_msg(user['_id'], msg)
                success += (sts == 200)
                failed  += (sts != 200)
                if sts == 400:
                    try:
                        await Seishiro.delete_user(user['_id'])
                    except Exception:
                        pass
                done += 1
                if done % 20 == 0:
                    try:
                        await sts_msg.edit(
                            f"📤 Broadcasting...\nTotal: {total}\nDone: {done}/{total}\n"
                            f"✅ {success}  ❌ {failed}"
                        )
                    except FloodWait as fw:
                        await asyncio.sleep(fw.value)
                    except Exception:
                        pass
            except Exception as e:
                logger.error(f"Broadcast user error: {e}")
                failed += 1; done += 1

        elapsed = timedelta(seconds=int(time.time() - start_time))
        try:
            await sts_msg.edit(
                f"✅ Broadcast Complete!\nTime: {elapsed}\n"
                f"Total: {total} | Done: {done}\n✅ {success}  ❌ {failed}"
            )
        except Exception:
            await m.reply_text(f"✅ Done. ✅ {success}  ❌ {failed}")

    except Exception as e:
        logger.error(f"broadcast_handler fatal: {e}")
        await m.reply_text(f"<b>❌ Error: {e}</b>")


async def send_msg(user_id, message):
    try:
        await message.copy(chat_id=int(user_id))
        return 200
    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await send_msg(user_id, message)
    except (InputUserDeactivated, UserIsBlocked, PeerIdInvalid):
        return 400
    except RPCError as e:
        logger.error(f"RPC {user_id}: {e}")
        return 500
    except Exception as e:
        logger.error(f"send_msg {user_id}: {e}")
        return 500
