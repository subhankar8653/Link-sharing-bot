"""
plugins/premium.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Premium + Shortener — payment sirf Telegram Stars se

STAR PLAN COMMANDS (Admin):
  /setplan 99 1month        → ⭐ plan (stars, duration)
  /removeplan 99
  /plans
  /setlifetime 500          → Lifetime plan ki price (stars). Ek baar pay = hamesha ke liye premium
  /removelifetime           → Lifetime plan band

PREMIUM MANAGEMENT (Admin):
  /add_premium <id> <n> <unit>   |   /add_premium <id> lifetime
  /remove_premium <id>
  /get_premium <id>
  /premium_users

OTHER ADMIN:
  /shortener | /setshortener | /removeshortener | /toggleshortener
  /setpremiumlogs | /setcontact | /setsubimg | /setverifytime

USER COMMANDS:
  /plan   → plans + buy
  /myplan → apna plan status
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import datetime
import re
import logging
import os

import pytz
from pyrogram import filters
from pyrogram.errors import MessageTooLong
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from config import OWNER_ID
from database.database import Seishiro
from bot import Bot

logger = logging.getLogger(__name__)
IST    = pytz.timezone("Asia/Kolkata")






# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DB HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _get_bot_config() -> dict:
    doc = await Seishiro.database['bot_config'].find_one({"_id": "main"})
    return doc or {}

async def _set_bot_config(key: str, value) -> None:
    await Seishiro.database['bot_config'].update_one(
        {"_id": "main"}, {"$set": {key: value}}, upsert=True
    )

async def get_shortener_settings() -> dict:
    cfg = await _get_bot_config()
    return {
        "enabled":        cfg.get("shortener_enabled", False),
        "api":            cfg.get("shortener_api", ""),
        "website":        cfg.get("shortener_website", ""),
        "bypass_premium": cfg.get("shortener_bypass_premium", True),
    }

async def get_premium_ui() -> dict:
    cfg = await _get_bot_config()
    return {
        "logs_channel": cfg.get("premium_logs", None),
        "contact_link": cfg.get("contact_link", ""),
        "sub_img":      cfg.get("subscription_img",
                            "https://graph.org/file/242b7f1b52743938d81f1.jpg"),
    }


LIFETIME_YEARS   = 100
LIFETIME_SECONDS = LIFETIME_YEARS * 365 * 86400


def is_lifetime(expiry) -> bool:
    """Expiry 2100 ke baad ki ho toh Lifetime premium."""
    return isinstance(expiry, datetime.datetime) and expiry.year >= 2100


async def get_lifetime_stars() -> int:
    cfg = await _get_bot_config()
    try:
        return max(0, int(cfg.get("lifetime_stars", 0) or 0))
    except Exception:
        return 0


async def get_star_plans() -> dict:
    cfg = await _get_bot_config()
    raw = cfg.get("star_plans", {})
    if not raw:
        return {10: "7day", 20: "15day", 40: "1month", 75: "60day"}
    return {int(k): v for k, v in raw.items()}



# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# UTILITY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def get_seconds(time_str: str) -> int:
    ts = time_str.strip()
    val, i = "", 0
    while i < len(ts) and ts[i].isdigit():
        val += ts[i]; i += 1
    unit = ts[i:].strip()
    if not val:
        return 0
    v = int(val)
    return v * {"s":1,"sec":1,"min":60,"hour":3600,
                "day":86400,"month":86400*30,"year":86400*365}.get(unit, 0)

def fmt_expiry(dt: datetime.datetime) -> str:
    if is_lifetime(dt):
        return "Lifetime ♾"
    try:
        return dt.astimezone(IST).strftime("%d-%m-%Y  %I:%M %p IST")
    except Exception:
        return str(dt)

def time_left_str(expiry: datetime.datetime) -> str:
    if is_lifetime(expiry):
        return "Lifetime ♾"
    try:
        left = expiry.astimezone(IST) - datetime.datetime.now(IST)
    except Exception:
        left = expiry - datetime.datetime.now()
    if left.total_seconds() <= 0:
        return "Expired"
    d = left.days
    h, rem = divmod(left.seconds, 3600)
    m, _ = divmod(rem, 60)
    return f"{d}d {h}h {m}m"

async def is_owner_or_admin(user_id: int) -> bool:
    return user_id == OWNER_ID or await Seishiro.is_admin(user_id)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SHORTENER CORE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def shorten_link(long_url: str) -> str:
    s = await get_shortener_settings()
    if not s["enabled"] or not s["api"] or not s["website"]:
        return long_url
    try:
        from shortzy import Shortzy
        sz = Shortzy(api_key=s["api"], base_site=s["website"])
        try:
            return await sz.convert(long_url)
        except Exception:
            return await sz.get_quick_link(long_url)
    except ImportError:
        logger.warning("shortzy not installed → pip install shortzy")
        return long_url
    except Exception as e:
        logger.error(f"Shortener error: {e}")
        return long_url

async def get_invite_link_with_ads(client, user_id: int, raw_link: str) -> str:
    s = await get_shortener_settings()
    if s["bypass_premium"] and await Seishiro.has_premium_access(user_id):
        return raw_link
    return await shorten_link(raw_link)





async def _build_plans_ui():
    """Returns (caption, buttons, ui) for the /plan menu. Payment sirf Telegram Stars."""
    plans = await get_star_plans()
    life  = await get_lifetime_stars()
    ui    = await get_premium_ui()

    lines = [f"• ⭐ <b>{s} Stars</b> → {d}" for s, d in sorted(plans.items())]
    if life:
        lines.append(f"• ♾ <b>Lifetime</b> → ⭐ <b>{life} Stars</b> (ek baar pay, hamesha ke liye)")
    plans_section = ("<b>⭐ Telegram Stars:</b>\n" + "\n".join(lines) + "\n\n") if lines \
        else "<i>Koi plan set nahi — owner se contact karo.</i>\n\n"

    caption = (
        f"<b>💎 Premium Membership</b>\n\n"
        f"<blockquote>"
        f"✅ No Ads on Invite Links\n"
        f"✅ Direct Channel Access\n"
        f"✅ FSub Bypass\n"
        f"✅ Priority Support"
        f"</blockquote>\n\n"
        f"<b>📋 Plans:</b>\n{plans_section}"
    )

    btns = [[InlineKeyboardButton(f"⭐ {stars} Stars → {dur}", callback_data=f"prem_buy_{stars}")]
            for stars, dur in sorted(plans.items())]
    if life:
        btns.append([InlineKeyboardButton(f"♾ Lifetime → {life} Stars", callback_data="prem_life")])
    if ui.get("contact_link"):
        btns.append([InlineKeyboardButton("📩 Contact Admin", url=ui["contact_link"])])
    btns.append([InlineKeyboardButton("❌ Close", callback_data="prem_close")])
    return caption, InlineKeyboardMarkup(btns), ui


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SHORTENER MANAGEMENT (Admin)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@Bot.on_message(filters.command("shortener") & filters.private)
async def cmd_shortener_status(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    s      = await get_shortener_settings()
    status = "✅ ON" if s["enabled"] else "❌ OFF"
    api    = s["api"][:8] + "..." if s["api"] else "Not set"
    site   = s["website"] or "Not set"
    await msg.reply(
        f"<b>🔗 Shortener Settings</b>\n\n"
        f"• Status: <b>{status}</b>\n"
        f"• API Key: <code>{api}</code>\n"
        f"• Website: <code>{site}</code>\n"
        f"• Premium Bypass: {'✅' if s['bypass_premium'] else '❌'}\n\n"
        f"<code>/setshortener API_KEY website.com</code>\n"
        f"<code>/removeshortener</code> | <code>/toggleshortener</code>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "🔴 Turn OFF" if s["enabled"] else "🟢 Turn ON",
                callback_data="toggle_shortener"
            )],
            [InlineKeyboardButton("🗑 Remove", callback_data="confirm_remove_shortener")],
        ])
    )

@Bot.on_message(filters.command("setshortener") & filters.private)
async def cmd_set_shortener(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    parts = msg.command
    if len(parts) < 3:
        return await msg.reply(
            "<b>Usage:</b> <code>/setshortener API_KEY website.com</code>\n"
            "<b>Example:</b> <code>/setshortener a7ac9b3012c6 omegalinks.in</code>"
        )
    api_key = parts[1]
    website = parts[2].strip().lower().replace("https://","").replace("http://","").rstrip("/")
    await _set_bot_config("shortener_api", api_key)
    await _set_bot_config("shortener_website", website)
    await _set_bot_config("shortener_enabled", True)
    await _set_bot_config("shortener_bypass_premium", True)
    await msg.reply(
        f"✅ <b>Shortener Set!</b>\n\n"
        f"• API: <code>{api_key[:8]}...</code>\n"
        f"• Site: <code>{website}</code>\n"
        f"• Status: ON | Premium Bypass: ON"
    )

@Bot.on_message(filters.command("removeshortener") & filters.private)
async def cmd_remove_shortener(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    await _set_bot_config("shortener_api", "")
    await _set_bot_config("shortener_website", "")
    await _set_bot_config("shortener_enabled", False)
    await msg.reply("🗑 Shortener removed. Ab direct links milenge.")

@Bot.on_message(filters.command("toggleshortener") & filters.private)
async def cmd_toggle_shortener(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    s = await get_shortener_settings()
    if not s["api"] and not s["enabled"]:
        return await msg.reply("⚠️ Pehle /setshortener se API set karo!")
    new = not s["enabled"]
    await _set_bot_config("shortener_enabled", new)
    await msg.reply(f"{'✅ Shortener ON' if new else '❌ Shortener OFF'}")







# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PREMIUM UI SETTINGS (Admin)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@Bot.on_message(filters.command("setpremiumlogs") & filters.private)
async def cmd_set_premium_logs(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    if len(msg.command) < 2:
        return await msg.reply("<code>/setpremiumlogs -100xxxxxxxxx</code>")
    try:
        ch_id = int(msg.command[1])
    except ValueError:
        return await msg.reply("❌ Invalid channel ID!")
    await _set_bot_config("premium_logs", ch_id)
    await msg.reply(f"✅ Premium logs channel: <code>{ch_id}</code>")



@Bot.on_message(filters.command("setcontact") & filters.private)
async def cmd_set_contact(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    if len(msg.command) < 2:
        return await msg.reply("<code>/setcontact @username</code>  ya  <code>/setcontact https://t.me/username</code>")
    raw = msg.command[1].strip()
    if raw.startswith("@"):
        raw = "https://t.me/" + raw[1:]
    elif raw.lower().startswith(("t.me/", "telegram.me/")):
        raw = "https://" + raw
    if not re.match(r"^https://(t|telegram)\.me/[A-Za-z0-9_]{4,}$", raw):
        return await msg.reply("❌ Valid username/link bhejo, jaise <code>@Suhani_Og</code>")
    await _set_bot_config("contact_link", raw)
    await msg.reply(f"✅ Contact link set: {raw}")

@Bot.on_message(filters.command("setsubimg") & filters.private)
async def cmd_set_sub_img(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    if len(msg.command) < 2:
        return await msg.reply("<code>/setsubimg https://image.jpg</code>")
    await _set_bot_config("subscription_img", msg.command[1])
    await msg.reply("✅ Subscription image set!")

@Bot.on_message(filters.command("setverifytime") & filters.private)
async def cmd_set_verify_time(client: Bot, msg: Message):
    """
    /setverifytime 12 hour
    /setverifytime 24 hour
    /setverifytime 6 hour
    """
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    parts = msg.command
    if len(parts) < 3:
        cur     = await _get_bot_config()
        cur_sec = cur.get("verify_premium_seconds", 86400)
        cur_hr  = cur_sec // 3600
        return await msg.reply(
            f"<b>⏰ Current Verify Time: <code>{cur_hr}h</code></b>\n\n"
            f"<code>/setverifytime 6 hour</code>\n"
            f"<code>/setverifytime 12 hour</code>\n"
            f"<code>/setverifytime 24 hour</code>\n"
            f"<code>/setverifytime 1 day</code>"
        )
    time_str = parts[1] + parts[2]
    seconds  = await get_seconds(time_str)
    if seconds <= 0:
        return await msg.reply("❌ Invalid time! Use: <code>6 hour / 12 hour / 1 day</code>")
    await _set_bot_config("verify_premium_seconds", seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    await msg.reply(f"✅ Verify time set: <b>{h}h {m}m</b>")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STAR PLAN COMMANDS (Admin)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@Bot.on_message(filters.command("setplan") & filters.private)
async def cmd_set_plan(client: Bot, msg: Message):
    """
    /setplan 99 1month
    /setplan 999 365day
    """
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    if len(msg.command) < 3:
        return await msg.reply(
            "<b>Usage:</b> <code>/setplan stars duration</code>\n"
            "<b>Examples:</b>\n"
            "<code>/setplan 99 1month</code>\n"
            "<code>/setplan 999 365day</code>"
        )
    try:
        stars = int(msg.command[1])
    except ValueError:
        return await msg.reply("❌ Stars must be a number!")
    duration = msg.command[2]
    if await get_seconds(duration) <= 0:
        return await msg.reply("❌ Invalid duration! Use: <code>7day / 1month / 1year</code>")
    plans        = await get_star_plans()
    plans[stars] = duration
    await _set_bot_config("star_plans", {str(k): v for k, v in plans.items()})
    await msg.reply(f"✅ Plan set: ⭐ <b>{stars} Stars</b> → <b>{duration}</b>\nTotal: {len(plans)}")

@Bot.on_message(filters.command("removeplan") & filters.private)
async def cmd_remove_plan(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    if len(msg.command) < 2:
        return await msg.reply("<code>/removeplan stars</code>")
    try:
        stars = int(msg.command[1])
    except ValueError:
        return await msg.reply("❌ Stars must be a number!")
    plans = await get_star_plans()
    if stars not in plans:
        return await msg.reply(f"❌ {stars} Stars ka plan nahi mila.")
    del plans[stars]
    await _set_bot_config("star_plans", {str(k): v for k, v in plans.items()})
    await msg.reply(f"🗑 Plan removed: ⭐ {stars} Stars")

@Bot.on_message(filters.command("setlifetime") & filters.private)
async def cmd_set_lifetime(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    if len(msg.command) < 2 or not msg.command[1].isdigit() or int(msg.command[1]) < 1:
        return await msg.reply("<b>Usage:</b> <code>/setlifetime 500</code>\n"
                               "Lifetime premium ke liye user ko kitne ⭐ Stars dene honge.")
    stars = int(msg.command[1])
    await _set_bot_config("lifetime_stars", stars)
    await msg.reply(f"✅ Lifetime plan set: ♾ <b>{stars} Stars</b>\nUser ek baar pay karega toh hamesha ke liye premium.")

@Bot.on_message(filters.command("removelifetime") & filters.private)
async def cmd_remove_lifetime(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    await _set_bot_config("lifetime_stars", 0)
    await msg.reply("🗑 Lifetime plan band kar diya.")

@Bot.on_message(filters.command("plans") & filters.private)
async def cmd_list_plans(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    plans = await get_star_plans()
    life = await get_lifetime_stars()
    if not plans and not life:
        return await msg.reply("📭 Koi star plan set nahi.\n<code>/setplan 99 1month</code>")
    lines = [f"• ⭐ <b>{s} Stars</b> → {d}" for s, d in sorted(plans.items())]
    if life:
        lines.append(f"• ♾ <b>Lifetime</b> → ⭐ <b>{life} Stars</b>")
    await msg.reply("<b>⭐ Star Plans:</b>\n\n" + "\n".join(lines))







# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PREMIUM MANAGEMENT (Admin)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@Bot.on_message(filters.command("add_premium") & filters.private)
async def cmd_add_premium(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    parts = msg.command
    is_life = len(parts) == 3 and parts[2].lower() in ("lifetime", "life")
    if len(parts) < 4 and not is_life:
        return await msg.reply(
            "<b>Usage:</b> <code>/add_premium user_id amount unit</code>\n"
            "<b>Example:</b> <code>/add_premium 123456 1 month</code>\n"
            "<b>Lifetime:</b> <code>/add_premium 123456 lifetime</code>"
        )
    try:
        user_id = int(parts[1])
    except ValueError:
        return await msg.reply("❌ Invalid user ID!")
    dur_txt  = "Lifetime ♾" if is_life else f"{dur_txt}"
    seconds  = LIFETIME_SECONDS if is_life else await get_seconds(parts[2] + parts[3])
    if seconds <= 0:
        return await msg.reply("❌ Invalid time. Use: <code>1 day / 1 month</code>")
    ok = await Seishiro.add_premium(user_id, seconds)
    if not ok:
        return await msg.reply("❌ DB error.")
    expiry  = await Seishiro.get_premium_expiry(user_id)
    exp_str = fmt_expiry(expiry) if expiry else "N/A"
    now_str = datetime.datetime.now(IST).strftime("%d-%m-%Y %I:%M %p IST")
    try:
        u = await client.get_users(user_id); mention = u.mention
    except Exception:
        mention = f"<code>{user_id}</code>"
    await msg.reply(
        f"✅ <b>Premium Added!</b>\n\n"
        f"👤 {mention} | 🆔 <code>{user_id}</code>\n"
        f"⏰ {dur_txt}\n⌛ Expiry: {exp_str}"
    )
    try:
        await client.send_message(user_id,
            f"🎉 <b>Premium Activated!</b>\n\nHey {mention}!\n"
            f"⏰ {dur_txt}\n⌛ Expiry: {exp_str}\n\n"
            f"✅ Shortener ads bypass ho gaye!\nCheck: /myplan"
        )
    except Exception:
        pass
    ui = await get_premium_ui()
    if ui["logs_channel"]:
        try:
            await client.send_message(ui["logs_channel"],
                f"#Premium_Added\n\n👤 {mention}\n🆔 <code>{user_id}</code>\n"
                f"⏰ {dur_txt}\n📅 {now_str}\n⌛ {exp_str}"
            )
        except Exception:
            pass

@Bot.on_message(filters.command("remove_premium") & filters.private)
async def cmd_remove_premium(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    if len(msg.command) < 2:
        return await msg.reply("<code>/remove_premium user_id</code>")
    try:
        user_id = int(msg.command[1])
    except ValueError:
        return await msg.reply("❌ Invalid user ID!")
    ok = await Seishiro.remove_premium(user_id)
    if ok:
        await msg.reply(f"✅ Premium removed: <code>{user_id}</code>")
        try:
            u = await client.get_users(user_id)
            await client.send_message(user_id,
                f"😔 {u.mention}, premium plan remove ho gaya.\nDobara lene ke liye: /plan")
        except Exception:
            pass
    else:
        await msg.reply("❌ User premium mein nahi tha ya DB error.")

@Bot.on_message(filters.command("get_premium") & filters.private)
async def cmd_get_premium(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    if len(msg.command) < 2:
        return await msg.reply("<code>/get_premium user_id</code>")
    try:
        user_id = int(msg.command[1])
    except ValueError:
        return await msg.reply("❌ Invalid user ID!")
    expiry  = await Seishiro.get_premium_expiry(user_id)
    is_prem = await Seishiro.has_premium_access(user_id)
    try:
        u = await client.get_users(user_id); mention = u.mention
    except Exception:
        mention = f"<code>{user_id}</code>"
    if is_prem and expiry:
        await msg.reply(
            f"⚜️ <b>Premium Active</b>\n\n"
            f"👤 {mention}\n🆔 <code>{user_id}</code>\n"
            f"⏰ Left: {time_left_str(expiry)}\n⌛ Expiry: {fmt_expiry(expiry)}"
        )
    else:
        await msg.reply(f"❌ {mention} ka koi active premium nahi.")

@Bot.on_message(filters.command("premium_users") & filters.private)
async def cmd_premium_users(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    wait  = await msg.reply("<i>Fetching...</i>")
    users = await Seishiro.get_all_premium_users()
    if not users:
        return await wait.edit_text("📭 Koi active premium user nahi.")
    lines = [f"<b>⚜️ Premium Users ({len(users)}):</b>\n"]
    for i, u in enumerate(users, 1):
        uid    = u.get("_id", "?")
        expiry = u.get("expiry_time")
        try:
            obj = await client.get_users(uid); name = obj.mention
        except Exception:
            name = f"<code>{uid}</code>"
        lines.append(
            f"{i}. {name} | {uid}\n"
            f"   Left: {time_left_str(expiry) if expiry else '?'} | "
            f"Expiry: {fmt_expiry(expiry) if expiry else 'N/A'}\n"
        )
    text = "\n".join(lines)
    try:
        await wait.edit_text(text)
    except MessageTooLong:
        with open("pm_users.txt", "w") as f:
            f.write(text)
        await msg.reply_document("pm_users.txt", caption="Premium Users")
        os.remove("pm_users.txt")
        await wait.delete()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# USER COMMANDS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@Bot.on_message(filters.command("myplan") & filters.private)
async def cmd_myplan(client: Bot, msg: Message):
    uid     = msg.from_user.id
    mention = msg.from_user.mention
    expiry  = await Seishiro.get_premium_expiry(uid)
    is_prem = await Seishiro.has_premium_access(uid)
    ui      = await get_premium_ui()

    if is_prem and expiry:
        caption = (
            f"⚜️ <b>Premium Active</b>\n\n"
            f"👤 {mention}\n🆔 <code>{uid}</code>\n"
            f"⏰ Time Left: {time_left_str(expiry)}\n"
            f"⌛ Expiry: {fmt_expiry(expiry)}\n\n"
            f"✅ <i>Ads Bypass | FSub Bypass</i>"
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔥 Extend Plan", callback_data="prem_plans")
        ]])
    else:
        caption = (
            f"<b>Hey {mention},\n\n"
            f"Aapka koi active premium plan nahi hai.\n\n"
            f"⚡ Free users ko invite links mein ads dekhne padte hain.\n"
            f"💎 Premium users ko direct link milta hai — no ads!</b>"
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("💎 View Plans", callback_data="prem_plans")
        ]])
    try:
        await msg.reply_photo(photo=ui["sub_img"], caption=caption, reply_markup=kb)
    except Exception:
        await msg.reply(caption, reply_markup=kb)

@Bot.on_message(filters.command("plan") & filters.private)
async def cmd_plan(client: Bot, msg: Message):
    caption, kb, ui = await _build_plans_ui()
    try:
        await msg.reply_photo(photo=ui["sub_img"], caption=caption, reply_markup=kb)
    except Exception:
        await msg.reply(caption, reply_markup=kb)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CALLBACKS — group=-1 (settings.py se pehle)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _send_plans(client: Bot, chat_id: int):
    """Plans menu ko naye message ki tarah bhejo (photo ke saath, na chale toh text)."""
    caption, kb, ui = await _build_plans_ui()
    try:
        await client.send_photo(chat_id, photo=ui["sub_img"], caption=caption, reply_markup=kb)
    except Exception:
        await client.send_message(chat_id, caption, reply_markup=kb)


def _is_invoice_msg(m) -> bool:
    """Invoice message ka text/caption edit nahi ho sakta (Pay button chipak jaata hai) → delete + naya bhejna padta hai."""
    try:
        return bool(getattr(m, "invoice", None)) or "INVOICE" in str(getattr(m, "media", "")).upper()
    except Exception:
        return False


@Bot.on_callback_query(filters.regex("^prem_plans$"), group=-1)
async def cb_plans(client: Bot, cq: CallbackQuery):
    if _is_invoice_msg(cq.message):
        # Invoice se "Back to Plans": invoice hatao, plans menu dobara bhejo (dead end nahi)
        try:
            await cq.message.delete()
        except Exception:
            pass
        await _send_plans(client, cq.message.chat.id)
        return await cq.answer()
    caption, kb, ui = await _build_plans_ui()
    try:
        if cq.message.photo:
            await cq.message.edit_caption(caption=caption, reply_markup=kb)
        else:
            await cq.message.edit_text(caption, reply_markup=kb)
    except Exception:
        try:
            await cq.message.delete()
        except Exception:
            pass
        try:
            await client.send_photo(cq.message.chat.id, photo=ui["sub_img"],
                                    caption=caption, reply_markup=kb)
        except Exception:
            await client.send_message(cq.message.chat.id, caption, reply_markup=kb)
    await cq.answer()


@Bot.on_callback_query(filters.regex(r"^prem_buy_\d+$"), group=-1)
async def cb_buy(client: Bot, cq: CallbackQuery):
    try:
        stars = int(cq.data.split("_")[-1])
        plans = await get_star_plans()
        if stars not in plans:
            return await cq.answer("⚠️ Plan exist nahi karta.", show_alert=True)
        dur = plans[stars]
        if is_lifetime(await Seishiro.get_premium_expiry(cq.from_user.id)):
            return await cq.answer("♾ Aapke paas pehle se Lifetime premium hai.", show_alert=True)
        await client.send_invoice(
            chat_id=cq.message.chat.id,
            title="Premium Subscription",
            description=f"Pay {stars} Stars → Premium for {dur}",
            payload=f"premium_{stars}",
            currency="XTR",
            prices=[LabeledPrice(label="Premium Subscription", amount=stars)],
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back to Plans", callback_data="prem_plans")],
                [InlineKeyboardButton("❌ Cancel", callback_data="prem_close")],
            ])
        )
        try:
            await cq.message.delete()          # purana plans menu hatao: invoice hi ek message rahe
        except Exception:
            pass
        await cq.answer()
    except Exception as e:
        logger.error(f"Invoice error: {e}")
        await cq.answer(f"❌ Error. Try again.", show_alert=True)












@Bot.on_callback_query(filters.regex("^prem_life$"), group=-1)
async def cb_buy_lifetime(client: Bot, cq: CallbackQuery):
    try:
        life = await get_lifetime_stars()
        if life <= 0:
            return await cq.answer("⚠️ Lifetime plan abhi available nahi.", show_alert=True)
        if is_lifetime(await Seishiro.get_premium_expiry(cq.from_user.id)):
            return await cq.answer("♾ Aapke paas pehle se Lifetime premium hai.", show_alert=True)
        await client.send_invoice(
            chat_id=cq.message.chat.id,
            title="Premium Lifetime",
            description=f"Pay {life} Stars once → Premium forever",
            payload="premium_life",
            currency="XTR",
            prices=[LabeledPrice(label="Premium Lifetime", amount=life)],
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back to Plans", callback_data="prem_plans")],
                [InlineKeyboardButton("❌ Cancel", callback_data="prem_close")],
            ])
        )
        try:
            await cq.message.delete()
        except Exception:
            pass
        await cq.answer()
    except Exception as e:
        logger.error(f"Lifetime invoice error: {e}")
        await cq.answer("❌ Error. Try again.", show_alert=True)


@Bot.on_callback_query(filters.regex("^prem_close$"), group=-1)
async def cb_close(client: Bot, cq: CallbackQuery):
    try:
        await cq.message.delete()
    except Exception:
        pass
    await cq.answer()


@Bot.on_callback_query(filters.regex("^toggle_shortener$"), group=-1)
async def cb_toggle_shortener(client: Bot, cq: CallbackQuery):
    if not await is_owner_or_admin(cq.from_user.id):
        return await cq.answer("⛔ Permission denied!", show_alert=True)
    s = await get_shortener_settings()
    if not s["api"] and not s["enabled"]:
        return await cq.answer("⚠️ Pehle /setshortener se API set karo!", show_alert=True)
    new = not s["enabled"]
    await _set_bot_config("shortener_enabled", new)
    await cq.answer(f"{'✅ Shortener ON' if new else '❌ Shortener OFF'}", show_alert=True)
    try:
        await cq.message.delete()
    except Exception:
        pass

@Bot.on_callback_query(filters.regex("^confirm_remove_shortener$"), group=-1)
async def cb_confirm_remove(client: Bot, cq: CallbackQuery):
    if not await is_owner_or_admin(cq.from_user.id):
        return await cq.answer("⛔ Permission denied!", show_alert=True)
    await _set_bot_config("shortener_api", "")
    await _set_bot_config("shortener_website", "")
    await _set_bot_config("shortener_enabled", False)
    await cq.answer("🗑 Shortener removed!", show_alert=True)
    try:
        await cq.message.delete()
    except Exception:
        pass

# Keep old aliases



# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TELEGRAM STAR PAYMENT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@Bot.on_pre_checkout_query()
async def pre_checkout(client: Bot, query: PreCheckoutQuery):
    if query.payload.startswith("premium_"):
        await query.answer(success=True)
    else:
        await query.answer(success=False, error_message="⚠️ Invalid payment.")

@Bot.on_message(filters.successful_payment & filters.private)
async def on_successful_payment(client: Bot, msg: Message):
    try:
        amount  = int(msg.successful_payment.total_amount)
        user_id = msg.from_user.id
        mention = msg.from_user.mention
        plans   = await get_star_plans()
        payload = getattr(msg.successful_payment, "invoice_payload", "") or ""
        now_str = datetime.datetime.now(IST).strftime("%d-%m-%Y %I:%M %p IST")

        if payload == "premium_life":
            ok = await Seishiro.add_premium(user_id, LIFETIME_SECONDS)
            if not ok:
                return await msg.reply("✅ Payment received! Contact support for manual activation.")
            await msg.reply(
                f"🎉 <b>Payment Successful!</b>\n\n"
                f"⭐ Stars: <b>{amount}</b>\n"
                f"♾ Plan: <b>Lifetime</b>\n\n"
                f"✅ Ads bypass!\n✅ FSub bypass!\nCheck: /myplan"
            )
            ui = await get_premium_ui()
            if ui["logs_channel"]:
                try:
                    await client.send_message(ui["logs_channel"],
                        f"#Star_Payment #Lifetime\n\n👤 {mention}\n🆔 <code>{user_id}</code>\n"
                        f"⭐ {amount} Stars → Lifetime ♾\n📅 {now_str}")
                except Exception:
                    pass
            return

        if is_lifetime(await Seishiro.get_premium_expiry(user_id)):
            return await msg.reply("✅ Payment received! Aapke paas pehle se Lifetime hai — support se contact karo.")

        if amount not in plans:
            return await msg.reply("✅ Payment received! Contact support for activation.")

        dur     = plans[amount]
        seconds = await get_seconds(dur)
        if seconds <= 0:
            return await msg.reply("✅ Payment received! Contact support.")

        ok = await Seishiro.add_premium(user_id, seconds)
        if not ok:
            return await msg.reply("✅ Payment received! Contact support for manual activation.")

        expiry  = await Seishiro.get_premium_expiry(user_id)
        exp_str = fmt_expiry(expiry) if expiry else "N/A"
        now_str = datetime.datetime.now(IST).strftime("%d-%m-%Y %I:%M %p IST")

        await msg.reply(
            f"🎉 <b>Payment Successful!</b>\n\n"
            f"⭐ Stars: <b>{amount}</b>\n"
            f"⏰ Plan: <b>{dur}</b>\n"
            f"⌛ Expiry: {exp_str}\n\n"
            f"✅ Ads bypass!\n✅ FSub bypass!\nCheck: /myplan"
        )
        ui = await get_premium_ui()
        if ui["logs_channel"]:
            try:
                await client.send_message(ui["logs_channel"],
                    f"#Star_Payment\n\n👤 {mention}\n🆔 <code>{user_id}</code>\n"
                    f"⭐ {amount} Stars → {dur}\n📅 {now_str}\n⌛ {exp_str}"
                )
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Payment error: {e}")
        await msg.reply("✅ Payment received! Contact support if plan not activated.")
