"""
plugins/link_mode.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LINK MODE — bot ek hi hai, settings ke do set (mode A = purana, mode B = alag)

  /link_mode        → abhi kaunsa mode + A/B buttons
  /link_mode b      → B mode ki POORI settings khulti hain (Link/Fsub/Mini App/Shortener/Ban... sab)
  /link_mode a      → wapas normal (A) mode

Jab tak B mode ON hai (aapke liye), jo bhi settings/commands use karoge
(/settings, /miniapp, /addminiad, /setshortener, /setverifytime, FSub menu...) woh SIRF B mode pe lagenge.

Links:
  A: ?start=<b64>   ?start=req_<b64>        (purane — A ki settings se, kuch nahi badla)
  B: ?start=b_<b64> ?start=breq_<b64>       (B ki settings se: apne ads, FSub, shortener, flow, free time...)

B mode mein alag: Mini App ads/flow/goal/free time/per-session, shortener, verify time, FSub channels
(+ fake links, layout, tutorials) aur user ka flow-state (ads-free time, link position, daily goal).
Shared: channels list, users, admins, bans, paid premium, premium plans, Senpai Sync, auto-delete.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import logging
import time

from pyrogram import filters
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import Bot
from config import OWNER_ID
from database.database import Seishiro
from modectx import set_mode

logger = logging.getLogger(__name__)

ADMIN_TTL = 3 * 3600          # B mode session (admin) is tarah tak chalta hai (har activity pe badhta hai)
USER_TTL = 3600               # user ne jo link kholi uska mode itni der yaad rahe (callbacks ke liye)

ADMIN_SESSION: dict = {}      # uid -> expiry timestamp  (admin ne /link_mode b kiya)
USER_MODE: dict = {}          # uid -> (mode, ts)        (aakhri link A thi ya B)


def _admin_b(uid: int) -> bool:
    exp = ADMIN_SESSION.get(uid)
    if exp and exp > time.time():
        ADMIN_SESSION[uid] = time.time() + ADMIN_TTL
        return True
    ADMIN_SESSION.pop(uid, None)
    return False


def _recent_user_mode(uid: int):
    v = USER_MODE.get(uid)
    if v and time.time() - v[1] < USER_TTL:
        return v[0]
    USER_MODE.pop(uid, None)
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MODE DETECTION  (har update se pehle, group -10)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@Bot.on_message(group=-10)
async def _mode_for_message(client: Bot, message: Message):
    try:
        uid = message.from_user.id if message.from_user else 0
        text = message.text or ""
        parts = text.split(None, 1)
        is_start = bool(parts) and parts[0].split("@")[0].lower() == "/start"
        mode = "a"

        if is_start and len(parts) > 1:
            p = parts[1].strip()
            if p.startswith(("b_", "breq_")):
                mode = "b"
                newp = p[2:] if p.startswith("b_") else "req_" + p[5:]
                # B link → normal flow ko A jaisa payload do; mode B hone se saari settings B ki padhi jayengi
                message.text = f"/start {newp}"
                message.command = ["start", newp]
            elif p.startswith("vfy_"):
                try:
                    mode = (await Seishiro.get_verify_token(p[4:])).get("mode", "a")
                except Exception:
                    mode = "a"
            USER_MODE[uid] = (mode, time.time())
        elif is_start:
            USER_MODE.pop(uid, None)
        elif _admin_b(uid):
            USER_MODE.pop(uid, None)         # admin settings kar raha hai — purani link ka mode ignore
            mode = "b"
        else:
            mode = _recent_user_mode(uid) or "a"
        set_mode(mode)
    except Exception as e:
        logger.error(f"mode detect (message) error: {e}")
        set_mode("a")


@Bot.on_callback_query(group=-10)
async def _mode_for_callback(client: Bot, cq: CallbackQuery):
    try:
        uid = cq.from_user.id
        mode = _recent_user_mode(uid) or ("b" if _admin_b(uid) else "a")
        set_mode(mode)
    except Exception as e:
        logger.error(f"mode detect (callback) error: {e}")
        set_mode("a")


# Baaki update types (join request, member update, payment) hamesha A / shared — leak na ho
@Bot.on_chat_join_request(group=-10)
async def _mode_reset_join(client, update):
    set_mode("a")


@Bot.on_chat_member_updated(group=-10)
async def _mode_reset_member(client, update):
    set_mode("a")


@Bot.on_pre_checkout_query(group=-10)
async def _mode_reset_checkout(client, update):
    set_mode("a")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# /link_mode
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _is_admin(uid: int) -> bool:
    return uid == OWNER_ID or await Seishiro.is_admin(uid)


def _status_kb(mode: str):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(("• " if mode == "a" else "") + "A (Normal)", callback_data="lm_a"),
        InlineKeyboardButton(("• " if mode == "b" else "") + "🅱️ B Mode", callback_data="lm_b"),
    ]])


async def _open_b(client: Bot, message: Message):
    ADMIN_SESSION[message.from_user.id] = time.time() + ADMIN_TTL
    USER_MODE.pop(message.from_user.id, None)
    set_mode("b")
    await message.reply(
        "🅱️ <b>B MODE ON</b>\n\n"
        "Ab jo bhi settings / commands use karoge (<code>/settings</code>, <code>/miniapp</code>, "
        "<code>/setshortener</code>, FSub menu...) woh <b>sirf B mode</b> pe lagenge.\n"
        "A mode (purane links) pe koi asar nahi.\n\n"
        "B link format: <code>https://t.me/BOT?start=b_&lt;id&gt;</code> (<code>/genlink</code> se milta hai)\n"
        "Bot admin nahi hai? Settings → <b>🔗 Short Link</b> (ya <code>/shortlink</code>) mein koi bhi Telegram link do, bot link bana dega.\n"
        "Wapas jaane ke liye: <code>/link_mode a</code>")
    from plugins.settings import settings_command
    await settings_command(client, message)


@Bot.on_message(filters.command("link_mode") & filters.private)
async def cmd_link_mode(client: Bot, message: Message):
    if not await _is_admin(message.from_user.id):
        return await message.reply("⛔ Sirf admins ke liye!")
    arg = message.command[1].lower() if len(message.command) > 1 else ""
    uid = message.from_user.id
    if arg == "b":
        return await _open_b(client, message)
    if arg == "a":
        ADMIN_SESSION.pop(uid, None)
        return await message.reply("✅ <b>A (Normal) mode</b> — ab saari settings purane links ki hain.\n"
                                   "B mode kholne ke liye: <code>/link_mode b</code>")
    mode = "b" if _admin_b(uid) else "a"
    await message.reply(
        f"<b>🔀 Link Mode</b>\n\nAbhi aapke liye: <b>{'🅱️ B' if mode == 'b' else 'A (Normal)'}</b>\n\n"
        "<code>/link_mode a</code> — normal links ki settings\n"
        "<code>/link_mode b</code> — B links ki poori alag settings",
        reply_markup=_status_kb(mode))


@Bot.on_callback_query(filters.regex(r"^lm_(a|b)$"), group=-1)
async def link_mode_cb(client: Bot, cq: CallbackQuery):
    if not await _is_admin(cq.from_user.id):
        return await cq.answer("Only admins!", show_alert=True)
    uid = cq.from_user.id
    if cq.data == "lm_b":
        ADMIN_SESSION[uid] = time.time() + ADMIN_TTL
        USER_MODE.pop(uid, None)
        await cq.answer("B mode ON")
        await cq.message.edit_text(
            "🅱️ <b>B MODE ON</b>\n\nAb /settings aur saare commands B mode pe lagenge.\n"
            "Settings kholo: <code>/settings</code> | Wapas: <code>/link_mode a</code>",
            reply_markup=_status_kb("b"))
    else:
        ADMIN_SESSION.pop(uid, None)
        await cq.answer("A mode ON")
        await cq.message.edit_text(
            "✅ <b>A (Normal) mode</b> — saari settings purane links ki.",
            reply_markup=_status_kb("a"))
