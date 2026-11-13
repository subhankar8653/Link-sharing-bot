"""
plugins/miniapp.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Telegram Mini App (Ad Watch) System — Shortener ka replacement

FLOW:
  User channel link kholta hai → bot "🎬 Watch Video Ad" button deta hai
  → button Telegram Mini App kholta hai → ads ek ek karke (admin ke
  set kiye order mein) dikhte hain → sab complete hone par bot khud
  user ko channel link bhej deta hai.

ADMIN COMMANDS:
  /miniapp                         → status + ON/OFF button
  /addminiad <provider> <id>       → ad add karo  (provider: monetag | adsgram | gigapub)
  /delminiad <number>              → ad hatao
  /miniadorder 2 1 3               → ads ka order badlo
  /setminiurl https://xxx.up.railway.app   → Mini App ka public URL
  /setminiwait <seconds>           → har ad ke liye minimum dekhne ka time

Provider ID kya daalna hai:
  monetag → Zone ID (number, e.g. 1234567)
  adsgram → Block ID (e.g. 12345  ya  int-12345)
  gigapub → Project ID (number)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import hashlib
import hmac
import json
import logging
import time
from urllib.parse import parse_qsl

from pyrogram import filters
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot import Bot
from config import MINIAPP_URL, TG_BOT_TOKEN
from plugins.premium import _get_bot_config, _set_bot_config, is_owner_or_admin

logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS = ("monetag", "adsgram", "gigapub")
DEFAULT_MIN_SECONDS = 5


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONFIG HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def get_miniapp_settings() -> dict:
    cfg = await _get_bot_config()
    url = (cfg.get("miniapp_url") or MINIAPP_URL or "").rstrip("/")
    return {
        "enabled": bool(cfg.get("miniapp_enabled", False)),
        "url": url,
        "ads": list(cfg.get("miniapp_ads", [])),
        "min_seconds": int(cfg.get("miniapp_min_seconds", DEFAULT_MIN_SECONDS)),
    }


async def miniapp_ready() -> bool:
    """Mini app tabhi use hoga jab ON ho, URL ho (https) aur kam se kam 1 ad ho."""
    s = await get_miniapp_settings()
    return bool(s["enabled"] and s["url"].startswith("https://") and s["ads"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TELEGRAM initData VALIDATION
# https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def validate_init_data(init_data: str, max_age: int = 86400) -> dict | None:
    """
    Mini App se aaya initData verify karo.
    Valid ho toh user dict ({"id":..., ...}) return karo, warna None.
    Isse koi bhi fake user_id bhej kar dusre ka token use nahi kar sakta.
    """
    try:
        if not init_data:
            return None
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = pairs.pop("hash", None)
        if not received_hash:
            return None

        data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
        secret_key = hmac.new(b"WebAppData", TG_BOT_TOKEN.encode(), hashlib.sha256).digest()
        calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc_hash, received_hash):
            return None

        auth_date = int(pairs.get("auth_date", "0"))
        if auth_date <= 0 or time.time() - auth_date > max_age:
            return None

        user = json.loads(pairs.get("user", "{}"))
        if not user.get("id"):
            return None
        return user
    except Exception as e:
        logger.warning(f"initData validation error: {e}")
        return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ADMIN PANEL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _panel_text(s: dict) -> str:
    status = "✅ ON" if s["enabled"] else "❌ OFF"
    url = s["url"] or "Not set"
    if s["ads"]:
        ads = "\n".join(
            f"  {i}. <b>{a['provider']}</b> → <code>{a['id']}</code>"
            for i, a in enumerate(s["ads"], 1)
        )
    else:
        ads = "  (koi ad add nahi hai)"
    return (
        "<b>🎬 Mini App Ads Settings</b>\n\n"
        f"• Status: <b>{status}</b>\n"
        f"• URL: <code>{url}</code>\n"
        f"• Min watch time / ad: <b>{s['min_seconds']}s</b>\n\n"
        f"<b>Ads (is order mein dikhenge):</b>\n{ads}\n\n"
        "<code>/addminiad monetag 1234567</code>\n"
        "<code>/addminiad adsgram 12345</code>\n"
        "<code>/addminiad gigapub 1234</code>\n"
        "<code>/delminiad 2</code>  |  <code>/miniadorder 2 1 3</code>\n"
        "<code>/setminiurl https://your-app.up.railway.app</code>\n"
        "<code>/setminiwait 5</code>\n\n"
        "ℹ️ Mini App ON hone par free users ko shortener ki jagah "
        "<b>Watch Video Ad</b> button milega."
    )


@Bot.on_message(filters.command("miniapp") & filters.private)
async def cmd_miniapp(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    s = await get_miniapp_settings()
    await msg.reply(
        _panel_text(s),
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "🔴 Turn OFF" if s["enabled"] else "🟢 Turn ON",
                callback_data="toggle_miniapp",
            )
        ]]),
    )


@Bot.on_callback_query(filters.regex("^toggle_miniapp$"), group=-1)
async def cb_toggle_miniapp(client: Bot, cq: CallbackQuery):
    if not await is_owner_or_admin(cq.from_user.id):
        return await cq.answer("⛔ Admins only", show_alert=True)
    s = await get_miniapp_settings()
    new = not s["enabled"]
    if new:
        if not s["ads"]:
            return await cq.answer("⚠️ Pehle /addminiad se ad add karo!", show_alert=True)
        if not s["url"].startswith("https://"):
            return await cq.answer("⚠️ Pehle /setminiurl se https URL set karo!", show_alert=True)
    await _set_bot_config("miniapp_enabled", new)
    s["enabled"] = new
    await cq.answer("✅ Mini App ON" if new else "❌ Mini App OFF", show_alert=True)
    try:
        await cq.message.edit_text(
            _panel_text(s),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "🔴 Turn OFF" if new else "🟢 Turn ON",
                    callback_data="toggle_miniapp",
                )
            ]]),
        )
    except Exception:
        pass


@Bot.on_message(filters.command("addminiad") & filters.private)
async def cmd_add_miniad(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    if len(msg.command) < 3:
        return await msg.reply(
            "<b>Usage:</b> <code>/addminiad provider id</code>\n"
            f"<b>Providers:</b> {', '.join(SUPPORTED_PROVIDERS)}\n"
            "<b>Example:</b> <code>/addminiad monetag 1234567</code>"
        )
    provider = msg.command[1].lower().strip()
    ad_id = msg.command[2].strip()
    if provider not in SUPPORTED_PROVIDERS:
        return await msg.reply(f"❌ Provider galat hai. Use: {', '.join(SUPPORTED_PROVIDERS)}")
    if not ad_id.replace("-", "").replace("_", "").isalnum():
        return await msg.reply("❌ ID mein sirf letters/numbers/-/_ allowed hain.")
    s = await get_miniapp_settings()
    ads = s["ads"]
    ads.append({"provider": provider, "id": ad_id})
    await _set_bot_config("miniapp_ads", ads)
    await msg.reply(f"✅ Ad add hua: <b>{provider}</b> → <code>{ad_id}</code>\nTotal ads: {len(ads)}\n\n/miniapp se dekho.")


@Bot.on_message(filters.command("delminiad") & filters.private)
async def cmd_del_miniad(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    if len(msg.command) < 2 or not msg.command[1].isdigit():
        return await msg.reply("<b>Usage:</b> <code>/delminiad 2</code> (number /miniapp mein dekho)")
    idx = int(msg.command[1])
    s = await get_miniapp_settings()
    ads = s["ads"]
    if idx < 1 or idx > len(ads):
        return await msg.reply("❌ Galat number.")
    removed = ads.pop(idx - 1)
    await _set_bot_config("miniapp_ads", ads)
    extra = ""
    if not ads and s["enabled"]:
        await _set_bot_config("miniapp_enabled", False)
        extra = "\n⚠️ Koi ad bacha nahi, isliye Mini App OFF kar diya."
    await msg.reply(f"🗑 Removed: <b>{removed['provider']}</b> → <code>{removed['id']}</code>{extra}")


@Bot.on_message(filters.command("miniadorder") & filters.private)
async def cmd_miniad_order(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    s = await get_miniapp_settings()
    ads = s["ads"]
    try:
        order = [int(x) for x in msg.command[1:]]
    except ValueError:
        order = []
    if sorted(order) != list(range(1, len(ads) + 1)):
        return await msg.reply(
            "<b>Usage:</b> <code>/miniadorder 2 1 3</code>\n"
            f"Saare {len(ads)} numbers ek baar likhne hain (1 se {len(ads)} tak)."
        )
    new_ads = [ads[i - 1] for i in order]
    await _set_bot_config("miniapp_ads", new_ads)
    s["ads"] = new_ads
    await msg.reply("✅ Order update ho gaya.\n\n" + _panel_text(s))


@Bot.on_message(filters.command("setminiurl") & filters.private)
async def cmd_set_miniurl(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    if len(msg.command) < 2:
        return await msg.reply("<b>Usage:</b> <code>/setminiurl https://your-app.up.railway.app</code>")
    url = msg.command[1].strip().rstrip("/")
    if not url.startswith("https://"):
        return await msg.reply("❌ URL <b>https://</b> se shuru hona chahiye (Telegram ki requirement).")
    await _set_bot_config("miniapp_url", url)
    await msg.reply(f"✅ Mini App URL set: <code>{url}</code>")


@Bot.on_message(filters.command("setminiwait") & filters.private)
async def cmd_set_miniwait(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    if len(msg.command) < 2 or not msg.command[1].isdigit():
        return await msg.reply("<b>Usage:</b> <code>/setminiwait 5</code> (seconds, 0-60)")
    sec = int(msg.command[1])
    if sec > 60:
        return await msg.reply("❌ Max 60 seconds.")
    await _set_bot_config("miniapp_min_seconds", sec)
    await msg.reply(f"✅ Har ad ke liye minimum <b>{sec}s</b> set.")
