"""
plugins/premium.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Premium Membership + Link Shortener — fully DB driven
Koi ENV VAR nahi chahiye — sab bot commands se manage karo

OWNER / ADMIN COMMANDS:
  /shortener               → shortener ka current status dekho
  /setshortener <api> <site> → shortener set karo
  /removeshortener         → shortener hata do (ads band)
  /toggleshortener         → on/off toggle
  /setpremiumlogs <id>     → premium log channel set karo
  /setupi <upi_id>         → UPI ID set karo
  /setqr <image_url>       → QR code image set karo
  /setcontact <link>       → contact link set karo
  /setsubimg <image_url>   → subscription page image set karo
  /setplan <stars> <dur>   → plan add/update karo  e.g. /setplan 40 1month
  /removeplan <stars>      → plan hata do
  /plans                   → sabhi plans dekho

  /add_premium <id> <n> <unit>   → user ko premium do
  /remove_premium <id>           → premium hata do
  /get_premium <id>              → kisi ka plan dekho
  /premium_users                 → sabhi premium users

USER COMMANDS:
  /myplan  → apna plan dekho
  /plan    → plans aur buy options

SHORTENER — kaise kaam karta hai:
  get_invite_link_with_ads(client, user_id, raw_link) call karo start.py mein.
  Premium users ko direct link milega (no ads).
  Free users ka link shortener se pass hoga → tumhe earnings milegi.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import datetime
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
IST = pytz.timezone("Asia/Kolkata")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DB HELPERS — sab settings MongoDB mein
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _get_bot_config() -> dict:
    """bot_config collection se saari settings fetch karo."""
    doc = await Seishiro.database['bot_config'].find_one({"_id": "main"})
    return doc or {}

async def _set_bot_config(key: str, value) -> None:
    """Ek setting save karo."""
    await Seishiro.database['bot_config'].update_one(
        {"_id": "main"},
        {"$set": {key: value}},
        upsert=True
    )

async def get_shortener_settings() -> dict:
    cfg = await _get_bot_config()
    return {
        "enabled":  cfg.get("shortener_enabled", False),
        "api":      cfg.get("shortener_api", ""),
        "website":  cfg.get("shortener_website", ""),
        "bypass_premium": cfg.get("shortener_bypass_premium", True),
    }

async def get_premium_ui() -> dict:
    """Premium page ke liye UI settings — sab DB se."""
    cfg = await _get_bot_config()
    return {
        "logs_channel": cfg.get("premium_logs", None),
        "upi_id":       cfg.get("owner_upi_id", "Not set"),
        "qr_code":      cfg.get("qr_code", ""),
        "contact_link": cfg.get("contact_link", ""),
        "sub_img":      cfg.get("subscription_img",
                            "https://graph.org/file/242b7f1b52743938d81f1.jpg"),
    }

async def get_star_plans() -> dict:
    """{stars(int): duration_str} — DB se ya default."""
    cfg = await _get_bot_config()
    raw = cfg.get("star_plans", {})
    if not raw:
        # Default plans
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
    try:
        return dt.astimezone(IST).strftime("%d-%m-%Y  %I:%M %p IST")
    except Exception:
        return str(dt)

def time_left_str(expiry: datetime.datetime) -> str:
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
    """
    Link ko shortener se pass karo.
    Settings DB se read hoti hain — koi hardcode nahi.
    """
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
    """
    start.py mein yahan se import karo:
        from plugins.premium import get_invite_link_with_ads
        invite = await get_invite_link_with_ads(client, user_id, raw_invite)

    Premium user → direct link (no ads)
    Free user    → shortener link (ads → earnings)
    """
    s = await get_shortener_settings()
    if s["bypass_premium"] and await Seishiro.has_premium_access(user_id):
        return raw_link
    return await shorten_link(raw_link)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SHORTENER MANAGEMENT COMMANDS (Admin)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@Bot.on_message(filters.command("shortener") & filters.private)
async def cmd_shortener_status(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")

    s = await get_shortener_settings()
    status = "✅ ON" if s["enabled"] else "❌ OFF"
    api    = s["api"][:8] + "..." if s["api"] else "Not set"
    site   = s["website"] or "Not set"

    await msg.reply(
        f"<b>🔗 Shortener Settings</b>\n\n"
        f"• Status: <b>{status}</b>\n"
        f"• API Key: <code>{api}</code>\n"
        f"• Website: <code>{site}</code>\n"
        f"• Premium Bypass: {'✅ Yes' if s['bypass_premium'] else '❌ No'}\n\n"
        f"<b>Commands:</b>\n"
        f"<code>/setshortener API_KEY website.com</code> — set karo\n"
        f"<code>/removeshortener</code> — hata do\n"
        f"<code>/toggleshortener</code> — on/off karo",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "🔴 Turn OFF" if s["enabled"] else "🟢 Turn ON",
                callback_data="toggle_shortener"
            )],
            [InlineKeyboardButton("🗑 Remove Shortener", callback_data="confirm_remove_shortener")],
        ])
    )


@Bot.on_message(filters.command("setshortener") & filters.private)
async def cmd_set_shortener(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")

    parts = msg.command
    if len(parts) < 3:
        return await msg.reply(
            "<b>📌 Usage:</b>\n"
            "<code>/setshortener YOUR_API_KEY website.com</code>\n\n"
            "<b>Example:</b>\n"
            "<code>/setshortener a7ac9b3012c6 omegalinks.in</code>\n\n"
            "API key shortener website ke dashboard se milegi."
        )

    api_key = parts[1]
    website = parts[2].strip().lower().replace("https://", "").replace("http://", "").rstrip("/")

    await _set_bot_config("shortener_api", api_key)
    await _set_bot_config("shortener_website", website)
    await _set_bot_config("shortener_enabled", True)
    await _set_bot_config("shortener_bypass_premium", True)

    await msg.reply(
        f"✅ <b>Shortener Set!</b>\n\n"
        f"• API Key: <code>{api_key[:8]}...</code>\n"
        f"• Website: <code>{website}</code>\n"
        f"• Status: <b>ON</b>\n"
        f"• Premium Bypass: <b>ON</b>\n\n"
        f"Ab free users ko invite links shortener se milenge (ads).\n"
        f"Premium users ko direct link milega."
    )


@Bot.on_message(filters.command("removeshortener") & filters.private)
async def cmd_remove_shortener(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")

    await _set_bot_config("shortener_api", "")
    await _set_bot_config("shortener_website", "")
    await _set_bot_config("shortener_enabled", False)

    await msg.reply(
        "🗑 <b>Shortener Removed!</b>\n\n"
        "Ab users ko direct invite links milenge (koi ads nahi).\n"
        "Dobara lagane ke liye: <code>/setshortener API WEBSITE</code>"
    )


@Bot.on_message(filters.command("toggleshortener") & filters.private)
async def cmd_toggle_shortener(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")

    s       = await get_shortener_settings()
    new_val = not s["enabled"]
    await _set_bot_config("shortener_enabled", new_val)

    if new_val and not s["api"]:
        return await msg.reply(
            "⚠️ Shortener ON kiya lekin API key set nahi hai!\n"
            "Pehle: <code>/setshortener API_KEY website.com</code>"
        )
    await msg.reply(
        f"{'✅ Shortener ON' if new_val else '❌ Shortener OFF'}\n\n"
        f"{'Ab free users ko ads ke saath links milenge.' if new_val else 'Ab sabko direct links milenge.'}"
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PREMIUM UI SETTINGS COMMANDS (Admin)
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
        return await msg.reply("❌ Invalid channel ID! Negative number hona chahiye.")
    await _set_bot_config("premium_logs", ch_id)
    await msg.reply(f"✅ Premium logs channel set: <code>{ch_id}</code>")


@Bot.on_message(filters.command("setupi") & filters.private)
async def cmd_set_upi(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    if len(msg.command) < 2:
        return await msg.reply("<code>/setupi yourname@upi</code>")
    upi = msg.command[1]
    await _set_bot_config("owner_upi_id", upi)
    await msg.reply(f"✅ UPI ID set: <code>{upi}</code>")


@Bot.on_message(filters.command("setqr") & filters.private)
async def cmd_set_qr(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    if len(msg.command) < 2:
        return await msg.reply("<code>/setqr https://image-url.jpg</code>")
    url = msg.command[1]
    await _set_bot_config("qr_code", url)
    await msg.reply(f"✅ QR code image set!")


@Bot.on_message(filters.command("setcontact") & filters.private)
async def cmd_set_contact(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    if len(msg.command) < 2:
        return await msg.reply("<code>/setcontact https://t.me/yourhandle</code>")
    link = msg.command[1]
    await _set_bot_config("contact_link", link)
    await msg.reply(f"✅ Contact link set: {link}")


@Bot.on_message(filters.command("setsubimg") & filters.private)
async def cmd_set_sub_img(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    if len(msg.command) < 2:
        return await msg.reply("<code>/setsubimg https://image-url.jpg</code>")
    url = msg.command[1]
    await _set_bot_config("subscription_img", url)
    await msg.reply("✅ Subscription image set!")


@Bot.on_message(filters.command("setverifytime") & filters.private)
async def cmd_set_verify_time(client: Bot, msg: Message):
    """
    /setverifytime 12 hour
    /setverifytime 24 hour
    /setverifytime 6 hour

    Shortener complete karne ke baad kitne time ka temp premium milega.
    Is time mein user ko direct links milenge (no shortener, no FSub).
    Time khatam → phir shortener complete karna padega.
    """
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")

    parts = msg.command
    if len(parts) < 3:
        cur = await _get_bot_config()
        cur_sec = cur.get("verify_premium_seconds", 86400)
        cur_hr  = cur_sec // 3600
        return await msg.reply(
            f"<b>⏰ Current Verify Time: <code>{cur_hr} hours</code></b>\n\n"
            f"<b>Usage:</b> <code>/setverifytime amount unit</code>\n\n"
            f"<b>Examples:</b>\n"
            f"<code>/setverifytime 6 hour</code>\n"
            f"<code>/setverifytime 12 hour</code>\n"
            f"<code>/setverifytime 24 hour</code>\n"
            f"<code>/setverifytime 1 day</code>\n\n"
            f"<i>Shortener complete karne ke baad user ko is time tak "
            f"direct links milenge — koi ads nahi, koi FSub nahi.</i>"
        )

    time_str = parts[1] + parts[2]
    seconds  = await get_seconds(time_str)
    if seconds <= 0:
        return await msg.reply(
            "❌ Invalid time!\nUse: <code>6 hour / 12 hour / 24 hour / 1 day</code>"
        )

    await _set_bot_config("verify_premium_seconds", seconds)
    hours = seconds // 3600
    mins  = (seconds % 3600) // 60

    display = f"{hours}h" if mins == 0 else f"{hours}h {mins}m"
    await msg.reply(
        f"✅ <b>Verify Time Set!</b>\n\n"
        f"⏰ Duration: <b>{display}</b>\n\n"
        f"Ab shortener complete karne wale users ko "
        f"<b>{display}</b> tak direct links milenge."
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PLANS MANAGEMENT COMMANDS (Admin)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@Bot.on_message(filters.command("setplan") & filters.private)
async def cmd_set_plan(client: Bot, msg: Message):
    """
    /setplan 40 1month
    /setplan 75 60day
    """
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    if len(msg.command) < 3:
        return await msg.reply(
            "<b>📌 Usage:</b> <code>/setplan stars duration</code>\n\n"
            "<b>Examples:</b>\n"
            "<code>/setplan 10 7day</code>\n"
            "<code>/setplan 40 1month</code>\n"
            "<code>/setplan 75 60day</code>\n\n"
            "Duration formats: <code>7day / 1month / 1year / 30min / 6hour</code>"
        )
    try:
        stars = int(msg.command[1])
    except ValueError:
        return await msg.reply("❌ Stars must be a number!")

    duration = msg.command[2]
    if await get_seconds(duration) <= 0:
        return await msg.reply(
            "❌ Invalid duration!\n"
            "Use: <code>7day / 1month / 1year / 30min</code>"
        )

    plans = await get_star_plans()
    plans[stars] = duration
    await _set_bot_config("star_plans", {str(k): v for k, v in plans.items()})
    await msg.reply(
        f"✅ <b>Plan Set!</b>\n\n"
        f"⭐ <b>{stars} Stars</b> → <b>{duration}</b>\n\n"
        f"Total plans: {len(plans)}"
    )


@Bot.on_message(filters.command("removeplan") & filters.private)
async def cmd_remove_plan(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    if len(msg.command) < 2:
        return await msg.reply("<code>/removeplan stars</code>\nExample: <code>/removeplan 40</code>")
    try:
        stars = int(msg.command[1])
    except ValueError:
        return await msg.reply("❌ Stars must be a number!")

    plans = await get_star_plans()
    if stars not in plans:
        return await msg.reply(f"❌ {stars} Stars ka koi plan nahi hai!")

    del plans[stars]
    await _set_bot_config("star_plans", {str(k): v for k, v in plans.items()})
    await msg.reply(f"🗑 Plan removed: ⭐ {stars} Stars")


@Bot.on_message(filters.command("plans") & filters.private)
async def cmd_list_plans(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    plans = await get_star_plans()
    if not plans:
        return await msg.reply("📭 Koi plan set nahi hai.\n<code>/setplan 40 1month</code>")

    lines = ["<b>⭐ Current Premium Plans:</b>\n"]
    for stars, dur in sorted(plans.items()):
        lines.append(f"• <b>{stars} Stars</b> → {dur}")
    lines.append(f"\n<i>Add: /setplan &lt;stars&gt; &lt;duration&gt;</i>")
    lines.append(f"<i>Remove: /removeplan &lt;stars&gt;</i>")
    await msg.reply("\n".join(lines))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PREMIUM MANAGEMENT COMMANDS (Admin)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@Bot.on_message(filters.command("add_premium") & filters.private)
async def cmd_add_premium(client: Bot, msg: Message):
    """
    /add_premium 123456 1 month
    /add_premium 123456 7 day
    """
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")

    parts = msg.command
    if len(parts) < 4:
        return await msg.reply(
            "<b>📌 Usage:</b> <code>/add_premium user_id amount unit</code>\n"
            "<b>Example:</b> <code>/add_premium 123456 1 month</code>\n"
            "Units: <code>min / hour / day / month / year</code>"
        )
    try:
        user_id = int(parts[1])
    except ValueError:
        return await msg.reply("❌ Invalid user ID!")

    time_str = parts[2] + parts[3]
    seconds  = await get_seconds(time_str)
    if seconds <= 0:
        return await msg.reply("❌ Invalid time. Example: <code>1 month</code>")

    ok = await Seishiro.add_premium(user_id, seconds)
    if not ok:
        return await msg.reply("❌ DB error. Try again.")

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
        f"⏰ {parts[2]} {parts[3]}\n⌛ Expiry: {exp_str}"
    )
    try:
        await client.send_message(user_id,
            f"🎉 <b>Premium Activated!</b>\n\nHey {mention}!\n"
            f"⏰ {parts[2]} {parts[3]}\n⌛ Expiry: {exp_str}\n\n"
            f"✅ Ab invite links mein koi ads nahi aayenge!\nCheck: /myplan"
        )
    except Exception:
        pass

    ui = await get_premium_ui()
    if ui["logs_channel"]:
        try:
            await client.send_message(ui["logs_channel"],
                f"#Premium_Added\n\n👤 {mention}\n🆔 <code>{user_id}</code>\n"
                f"⏰ {parts[2]} {parts[3]}\n📅 {now_str}\n⌛ {exp_str}"
            )
        except Exception as e:
            logger.warning(f"Log failed: {e}")


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
                f"😔 {u.mention}, aapka premium plan remove ho gaya.\n/plan se dobara le sakte ho.")
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
        await msg.reply(f"❌ {mention} ka koi active premium nahi hai.")


@Bot.on_message(filters.command("premium_users") & filters.private)
async def cmd_premium_users(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")

    wait  = await msg.reply("<i>Fetching...</i>")
    users = await Seishiro.get_all_premium_users()
    if not users:
        return await wait.edit_text("📭 Koi active premium user nahi hai.")

    lines = [f"<b>⚜️ Premium Users ({len(users)} total):</b>\n"]
    for i, u in enumerate(users, 1):
        uid    = u.get("_id", "?")
        expiry = u.get("expiry_time")
        try:
            obj = await client.get_users(uid); name = obj.mention
        except Exception:
            name = f"<code>{uid}</code>"
        lines.append(
            f"{i}. {name} | ID: {uid}\n"
            f"   Left: {time_left_str(expiry) if expiry else '?'} | "
            f"Expiry: {fmt_expiry(expiry) if expiry else 'N/A'}\n"
        )
    text = "\n".join(lines)
    try:
        await wait.edit_text(text)
    except MessageTooLong:
        with open("pm_users.txt", "w") as f:
            f.write(text)
        await msg.reply_document("pm_users.txt", caption="Premium Users List")
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
            f"✅ <i>Link Shortener Ads Bypassed</i>"
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
    plans = await get_star_plans()
    ui    = await get_premium_ui()

    plans_text = "\n".join(
        f"• ⭐ <b>{s} Stars</b> → {d}" for s, d in sorted(plans.items())
    ) if plans else "<i>Koi plan set nahi — owner se contact karo.</i>"

    btns = []
    for stars, dur in sorted(plans.items()):
        btns.append([InlineKeyboardButton(
            f"⭐ {stars} Stars → {dur}", callback_data=f"prem_buy_{stars}"
        )])
    if ui["upi_id"] != "Not set" or ui["contact_link"]:
        btns.append([InlineKeyboardButton("💰 Pay via UPI", callback_data="prem_upi")])
    btns.append([InlineKeyboardButton("❌ Close", callback_data="prem_close")])

    caption = (
        f"<b>💎 Premium Membership</b>\n\n"
        f"<blockquote>✅ No Ads on Invite Links\n"
        f"✅ Direct Channel Access\n"
        f"✅ Priority Support</blockquote>\n\n"
        f"<b>📋 Plans:</b>\n{plans_text}"
    )
    try:
        await msg.reply_photo(
            photo=ui["sub_img"], caption=caption,
            reply_markup=InlineKeyboardMarkup(btns)
        )
    except Exception:
        await msg.reply(caption, reply_markup=InlineKeyboardMarkup(btns))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CALLBACKS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@Bot.on_callback_query(filters.regex("^prem_plans$"), group=-1)
async def cb_plans(client: Bot, cq: CallbackQuery):
    plans = await get_star_plans()
    ui    = await get_premium_ui()

    btns = [
        [InlineKeyboardButton(f"⭐ {s} Stars → {d}", callback_data=f"prem_buy_{s}")]
        for s, d in sorted(plans.items())
    ]
    if ui["upi_id"] != "Not set" or ui["contact_link"]:
        btns.append([InlineKeyboardButton("💰 Pay via UPI", callback_data="prem_upi")])
    btns.append([InlineKeyboardButton("❌ Close", callback_data="prem_close")])

    plans_text = (
        "\n".join(f"• ⭐ <b>{s} Stars</b> → {d}" for s, d in sorted(plans.items()))
        if plans else "<i>Koi plan set nahi. Owner se contact karo.</i>"
    )
    caption = f"<b>💎 Premium Plans</b>\n\n{plans_text}\n\n<i>⭐ Star payment — instant & secure!</i>"
    kb      = InlineKeyboardMarkup(btns)

    # Message type ke hisaab se edit karo
    try:
        if cq.message.photo:
            await cq.message.edit_caption(caption=caption, reply_markup=kb)
        else:
            await cq.message.edit_text(caption, reply_markup=kb)
    except Exception:
        # Edit nahi hua — naya message bhejo (purana delete)
        try:
            await cq.message.delete()
        except Exception:
            pass
        try:
            await client.send_photo(
                cq.message.chat.id,
                photo=ui["sub_img"],
                caption=caption,
                reply_markup=kb
            )
        except Exception:
            await client.send_message(cq.message.chat.id, caption, reply_markup=kb)

    await cq.answer()


@Bot.on_callback_query(filters.regex(r"^prem_buy_\d+$"), group=-1)
async def cb_buy(client: Bot, cq: CallbackQuery):
    try:
        # prem_buy_40 → split("_") = ["prem","buy","40"] → index -1
        stars = int(cq.data.split("_")[-1])
        plans = await get_star_plans()
        if stars not in plans:
            return await cq.answer("⚠️ Yeh plan exist nahi karta.", show_alert=True)

        dur = plans[stars]
        await client.send_invoice(
            chat_id=cq.message.chat.id,
            title="Premium Subscription",
            description=f"Pay {stars} Stars → Premium for {dur}",
            payload=f"premium_{stars}",
            currency="XTR",
            prices=[LabeledPrice(label="Premium Subscription", amount=stars)],
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="prem_close")
            ]])
        )
        await cq.answer()
    except Exception as e:
        logger.error(f"Invoice error: {e}")
        await cq.answer(f"❌ Error processing. Try again.\n{str(e)[:60]}", show_alert=True)


@Bot.on_callback_query(filters.regex("^prem_upi$"), group=-1)
async def cb_upi(client: Bot, cq: CallbackQuery):
    ui    = await get_premium_ui()
    plans = await get_star_plans()

    plans_text = "\n".join(f"• ⭐ {s} Stars ({d})" for s, d in sorted(plans.items()))
    text = (
        f"<b>💰 Pay via UPI</b>\n\n"
        f"<b>UPI ID:</b> <code>{ui['upi_id']}</code>\n\n"
        f"<b>Plans:</b>\n{plans_text}\n\n"
        f"Payment ke baad screenshot bhejo.\n"
        f"<i>Manual activation mein thoda time lag sakta hai.</i>"
    )
    btns = []
    if ui["contact_link"]:
        btns.append([InlineKeyboardButton("📩 Contact Owner", url=ui["contact_link"])])
    btns.append([InlineKeyboardButton("⬅️ Back to Plans", callback_data="prem_plans")])
    kb = InlineKeyboardMarkup(btns)

    # QR code photo ke saath bhejo
    if ui["qr_code"]:
        try:
            await cq.message.reply_photo(photo=ui["qr_code"], caption=text, reply_markup=kb)
            return await cq.answer()
        except Exception as e:
            logger.warning(f"QR photo failed: {e}")

    # Photo nahi gaya — text message
    try:
        await cq.message.reply_text(text, reply_markup=kb)
    except Exception as e:
        logger.error(f"UPI reply failed: {e}")
        await cq.answer("Error showing UPI info.", show_alert=True)
    await cq.answer()


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
    new_val = not s["enabled"]
    await _set_bot_config("shortener_enabled", new_val)
    await cq.answer(f"{'✅ Shortener ON' if new_val else '❌ Shortener OFF'}", show_alert=True)
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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TELEGRAM STAR PAYMENT HANDLERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@Bot.on_pre_checkout_query()
async def pre_checkout(client: Bot, query: PreCheckoutQuery):
    if query.payload.startswith("premium_"):
        await query.answer(success=True)
    else:
        await query.answer(success=False, error_message="⚠️ Invalid payment type.")


@Bot.on_message(filters.successful_payment & filters.private)
async def on_successful_payment(client: Bot, msg: Message):
    try:
        amount  = int(msg.successful_payment.total_amount)
        user_id = msg.from_user.id
        mention = msg.from_user.mention
        plans   = await get_star_plans()

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
            f"✅ Invite links mein ab ads nahi aayenge!\nCheck: /myplan"
        )
        ui = await get_premium_ui()
        if ui["logs_channel"]:
            try:
                await client.send_message(ui["logs_channel"],
                    f"#Star_Payment\n\n👤 {mention}\n🆔 <code>{user_id}</code>\n"
                    f"⭐ {amount} Stars → {dur}\n📅 {now_str}\n⌛ {exp_str}"
                )
            except Exception as e:
                logger.warning(f"Log failed: {e}")

    except Exception as e:
        logger.error(f"Payment error: {e}")
        await msg.reply("✅ Payment received! Contact support if plan not activated.")
