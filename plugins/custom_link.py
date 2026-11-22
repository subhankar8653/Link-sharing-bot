"""
plugins/custom_link.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SHORT LINK — koi bhi Telegram link do, bot apna link bana ke dega (bilkul /genlink jaisa)

Kab kaam aata hai: jahan channel mein bot ko admin nahi bana sakte, wahan bas channel ka
private link hota hai. Wo link yahan do → bot ek link dega:

  A link: https://t.me/BOT?start=<id>     → normal (A) settings se chalega
  B link: https://t.me/BOT?start=b_<id>   → B mode ki settings se chalega

Us link par user ke saath bilkul wahi hoga jo /genlink links par hota hai
(FSub / Mini App ads / Shortener / Free Time / Premium skip) — aakhri step mein
admin ka diya hua link user ko mil jata hai. Bot ko admin banane ki zaroorat nahi.

USE:
  /link_mode b → /settings → "🔗 Short Link"   (B mode settings mein button)
  /shortlink <telegram link> [title]            (seedha command)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import datetime
import logging
import re

from pyrogram import StopPropagation, filters
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot import Bot
from config import OWNER_ID
from database.database import Seishiro
from helper_func import encode

logger = logging.getLogger(__name__)

# Asli channel ids -100xxxxxxxxxx (≈ -1.0e12) hote hain; custom links ke ids usse bahut door (negative) rakhe hain,
# taaki kabhi takrao na ho aur decode/“id < 0” checks bhi pass hon.
BASE = 9_000_000_000_000
MAX_LIST = 20


def is_custom_id(cid) -> bool:
    return isinstance(cid, int) and cid <= -BASE


def _col():
    return Seishiro.database["custom_links"]


async def get_custom(cid: int):
    if not is_custom_id(cid):
        return None
    try:
        return await _col().find_one({"_id": int(cid)})
    except Exception as e:
        logger.error(f"get_custom error: {e}")
        return None


def normalize_tg_link(text: str):
    """Telegram link ko https://t.me/... mein badlo. Galat ho toh None."""
    t = (text or "").strip()
    if not t:
        return None
    if t.startswith("@"):
        t = "https://t.me/" + t[1:]
    m = re.match(r"^tg://join\?invite=([\w-]+)$", t, re.I)
    if m:
        t = "https://t.me/+" + m.group(1)
    t = re.sub(r"^(https?://)?(www\.)?(telegram\.me|t\.me)/", "https://t.me/", t, flags=re.I)
    if re.fullmatch(r"https://t\.me/(\+[\w-]{6,}|joinchat/[\w-]{6,}|[A-Za-z][\w]{3,}(/\d+)?)", t):
        return t
    return None


async def create_custom(url: str, title: str = "") -> int:
    """Link save karo, id return karo. Same link dobara do toh wahi purani id (same bot link)."""
    old = await _col().find_one({"url": url})
    if old:
        if title and title != old.get("title"):
            await _col().update_one({"_id": old["_id"]}, {"$set": {"title": title}})
        return int(old["_id"])
    last = await _col().find_one({}, sort=[("_id", 1)])          # sabse negative id
    nid = (int(last["_id"]) - 1) if last else -(BASE + 1)
    await _col().insert_one({
        "_id": nid, "url": url, "title": title or "Private Link",
        "created_at": datetime.datetime.now(),
    })
    return nid


async def _links_for(client, cid: int):
    b64 = await encode(str(cid))
    return (f"https://t.me/{client.username}?start={b64}",
            f"https://t.me/{client.username}?start=b_{b64}")


def _result_text(url: str, title: str, a_link: str, b_link: str) -> str:
    return (
        "<b>✅ Short Link ready</b>\n\n"
        f"<b>Title:</b> {title}\n"
        f"<b>Original:</b> <code>{url}</code>\n\n"
        f"<b>Normal link (A):</b>\n<code>{a_link}</code>\n\n"
        f"<b>🅱️ B link:</b>\n<code>{b_link}</code>\n\n"
        "<i>Is link par FSub / Mini App ads / Shortener / Free Time bilkul /genlink wale links jaise chalega; "
        "aakhir mein aapka diya hua link milega. Bot ko admin banane ki zaroorat nahi.</i>"
    )


async def _is_admin(uid: int) -> bool:
    return uid == OWNER_ID or await Seishiro.is_admin(uid)


def _menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ New Short Link", callback_data="cl_new")],
        [InlineKeyboardButton("📋 My Short Links", callback_data="cl_list")],
        [InlineKeyboardButton("back", callback_data="settings_main")],
    ])


_MENU_TEXT = (
    "<b>🔗 Short Link</b>\n\n"
    "<blockquote>Koi bhi Telegram link do (private channel/group invite link bhi) — bot uska apna link bana dega, "
    "jaise <code>/genlink</code> karta hai. Us link par FSub / ads / shortener / free time wahi lagega, "
    "aur bot ko channel mein admin nahi banana padega.</blockquote>\n\n"
    "Command: <code>/shortlink https://t.me/+AbCdEf... [title]</code>"
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# /shortlink
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@Bot.on_message(filters.command("shortlink") & filters.private)
async def cmd_shortlink(client: Bot, msg: Message):
    if not await _is_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    if len(msg.command) < 2:
        return await msg.reply(_MENU_TEXT, reply_markup=_menu_kb())
    url = normalize_tg_link(msg.command[1])
    if not url:
        return await msg.reply("❌ Valid Telegram link bhejo, jaise <code>https://t.me/+AbCdEfGh</code> "
                               "ya <code>https://t.me/channelname</code>")
    title = " ".join(msg.command[2:])[:60]
    cid = await create_custom(url, title)
    doc = await get_custom(cid)
    a_link, b_link = await _links_for(client, cid)
    await msg.reply(_result_text(url, doc.get("title", ""), a_link, b_link), disable_web_page_preview=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SETTINGS BUTTONS  (cl_menu / cl_new / cl_list / cl_del)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _short_name(d: dict) -> str:
    u = (d.get("url") or "").replace("https://t.me/", "")
    return f"{(d.get('title') or 'Link')[:18]} · {u[:14]}"


async def _list_view():
    docs = await _col().find({}).sort("_id", -1).to_list(length=MAX_LIST)
    rows = [[InlineKeyboardButton(f"🗑 {_short_name(d)}", callback_data=f"cl_del:{d['_id']}")] for d in docs]
    rows.append([InlineKeyboardButton("back", callback_data="cl_menu")])
    text = ("<b>📋 My Short Links</b>\n\nButton dabane par link delete ho jata hai "
            "(uska bot link kaam karna band kar dega).\n\n" if docs else
            "<b>📋 My Short Links</b>\n\n<i>Abhi koi short link nahi bana.</i>")
    return text, InlineKeyboardMarkup(rows)


@Bot.on_callback_query(filters.regex(r"^(cl_menu|cl_new|cl_list|cl_del:-?\d+)$"), group=-1)
async def cl_callbacks(client: Bot, cq: CallbackQuery):
    if not await _is_admin(cq.from_user.id):
        await cq.answer("⛔ Admins only", show_alert=True)
        raise StopPropagation
    d = cq.data
    try:
        if d == "cl_menu":
            await cq.message.edit_text(_MENU_TEXT, reply_markup=_menu_kb())

        elif d == "cl_list":
            text, kb = await _list_view()
            await cq.message.edit_text(text, reply_markup=kb)

        elif d.startswith("cl_del:"):
            await _col().delete_one({"_id": int(d.split(":", 1)[1])})
            await cq.answer("🗑 Deleted")
            text, kb = await _list_view()
            await cq.message.edit_text(text, reply_markup=kb)

        elif d == "cl_new":
            await cq.message.edit_text(
                "<b>➕ New Short Link</b>\n\nTelegram link bhejo (optional: link ke baad title bhi likh sakte ho).\n"
                "Example: <code>https://t.me/+AbCdEfGh Naruto Channel</code>\n\n<i>/cancel — cancel karne ke liye</i>",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("back", callback_data="cl_menu")]]))
            try:
                resp = await client.listen(chat_id=cq.message.chat.id, timeout=300)
            except Exception:
                resp = None
            text = ""
            if resp is not None:
                try:
                    await resp.delete()
                except Exception:
                    pass
                text = (resp.text or "").strip()
            if not text or text.lower() == "/cancel":
                await cq.message.edit_text(_MENU_TEXT, reply_markup=_menu_kb())
            else:
                bits = text.split(None, 1)
                url = normalize_tg_link(bits[0])
                if not url:
                    await cq.message.reply("❌ Valid Telegram link bhejo, jaise <code>https://t.me/+AbCdEfGh</code>")
                    await cq.message.edit_text(_MENU_TEXT, reply_markup=_menu_kb())
                else:
                    cid = await create_custom(url, (bits[1] if len(bits) > 1 else "")[:60])
                    doc = await get_custom(cid)
                    a_link, b_link = await _links_for(client, cid)
                    await cq.message.edit_text(
                        _result_text(url, doc.get("title", ""), a_link, b_link),
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("➕ Another", callback_data="cl_new")],
                            [InlineKeyboardButton("back", callback_data="cl_menu")]]),
                        disable_web_page_preview=True)
    except Exception as e:
        if "MESSAGE_NOT_MODIFIED" not in str(e):
            logger.error(f"custom link cb error ({d}): {e}", exc_info=True)
            await cq.answer("Error — logs check karo", show_alert=True)
    raise StopPropagation
