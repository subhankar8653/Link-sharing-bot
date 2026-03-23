"""
plugins/premium.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Premium + Shortener + Wallet Payment System

WALLET COMMANDS (Admin):
  /setwallet rs <upi_id>            → Indian Rupees (UPI)
  /setwallet ton <address>          → TON Coin (TON Network)
  /setwallet usdt_ton <address>     → USDT (TON Network)
  /setwallet usdt_trc <address>     → USDT (TRC20 Network)
  /setwallet usdt_erc <address>     → USDT (ERC20 Network)
  /wallets                          → saare wallets dekho

CUSTOM PLAN COMMANDS (Admin):
  /setcustomplan rs 99 1month ₹99 → 1 Month
  /setcustomplan ton 1 1month 1 TON → 1 Month
  /setcustomplan usdt_ton 2 1month 2 USDT (TON) → 1 Month
  /removecustomplan rs 99
  /customplans

STAR PLAN COMMANDS (Admin):
  /setplan 99 1month
  /removeplan 99
  /plans

PREMIUM MANAGEMENT (Admin):
  /add_premium <id> <n> <unit>
  /remove_premium <id>
  /get_premium <id>
  /premium_users

OTHER ADMIN:
  /shortener | /setshortener | /removeshortener | /toggleshortener
  /setpremiumlogs | /setupi (alias) | /setqr | /setcontact | /setsubimg
  /setverifytime

USER COMMANDS:
  /plan   → plans + buy
  /myplan → apna plan status
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
IST    = pytz.timezone("Asia/Kolkata")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# WALLET / CURRENCY META
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

WALLET_META = {
    "rs":        {"name": "Indian Rupees",  "network": "UPI",         "symbol": "₹",    "db_key": "wallet_rs",        "qr_key": "qr_rs"},
    "ton":       {"name": "TON Coin",       "network": "TON Network", "symbol": "TON",  "db_key": "wallet_ton",       "qr_key": "qr_ton"},
    "usdt_ton":  {"name": "USDT",           "network": "TON Network", "symbol": "USDT", "db_key": "wallet_usdt_ton",  "qr_key": "qr_usdt_ton"},
    "usdt_trc":  {"name": "USDT",           "network": "TRC20",       "symbol": "USDT", "db_key": "wallet_usdt_trc",  "qr_key": "qr_usdt_trc"},
    "usdt_erc":  {"name": "USDT",           "network": "ERC20",       "symbol": "USDT", "db_key": "wallet_usdt_erc",  "qr_key": "qr_usdt_erc"},
}

def wallet_display_name(key: str) -> str:
    m = WALLET_META.get(key, {})
    if not m:
        return key.upper()
    return f"{m['name']} ({m['network']})"

def wallet_label_short(key: str) -> str:
    m = WALLET_META.get(key, {})
    if not m:
        return key.upper()
    return f"{m['symbol']} · {m['network']}"


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

async def get_wallets() -> dict:
    """Sabhi set wallets return karo {key: address}."""
    cfg  = await _get_bot_config()
    out  = {}
    for key, meta in WALLET_META.items():
        val = cfg.get(meta["db_key"], "")
        if val:
            out[key] = val
    return out

async def get_star_plans() -> dict:
    cfg = await _get_bot_config()
    raw = cfg.get("star_plans", {})
    if not raw:
        return {10: "7day", 20: "15day", 40: "1month", 75: "60day"}
    return {int(k): v for k, v in raw.items()}

async def get_custom_plans() -> list:
    cfg = await _get_bot_config()
    return cfg.get("custom_plans", [])


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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HELPER — plans UI builder
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _build_plans_ui():
    """
    Returns (caption, buttons) for the /plan menu.
    """
    plans        = await get_star_plans()
    custom_plans = await get_custom_plans()
    wallets      = await get_wallets()
    ui           = await get_premium_ui()

    # Caption sections
    star_text = (
        "\n".join(f"• ⭐ <b>{s} Stars</b> → {d}" for s, d in sorted(plans.items()))
        if plans else ""
    )

    # Custom plans text — wallet ke saath match karke dikhao
    custom_lines = []
    for p in custom_plans:
        custom_lines.append(f"• <b>{p['label']}</b> → {p['duration']}")
    # Agar wallet set hai but koi custom plan nahi — phir bhi dikhao
    custom_plan_keys = {p.get("currency_key") for p in custom_plans}
    for key, address in wallets.items():
        if key not in custom_plan_keys:
            meta = WALLET_META.get(key, {})
            if key == "rs":
                custom_lines.append(f"• <b>Indian Rupees (UPI)</b> — Contact for pricing")
            else:
                custom_lines.append(
                    f"• <b>{meta.get('name','?')} ({meta.get('network','?')})</b> — Contact for pricing"
                )
    custom_text = "\n".join(custom_lines)

    plans_section = ""
    if star_text:
        plans_section += f"<b>⭐ Telegram Stars:</b>\n{star_text}\n\n"
    if custom_text:
        plans_section += f"<b>💳 Other Payment:</b>\n{custom_text}\n\n"
    if not plans_section:
        plans_section = "<i>Koi plan set nahi — owner se contact karo.</i>\n\n"

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

    # Buttons — Star plans
    btns = []
    for stars, dur in sorted(plans.items()):
        btns.append([InlineKeyboardButton(
            f"⭐ {stars} Stars → {dur}", callback_data=f"prem_buy_{stars}"
        )])

    # Custom payment buttons
    # Strategy: sabse pehle custom_plans ke currency_keys se buttons banao
    # Phir jo wallets set hain unke buttons banao (agar already nahi bane)
    shown_keys = set()

    # 1. Custom plans se buttons (ek currency per button)
    for p in custom_plans:
        key = p.get("currency_key", "")
        if not key or key in shown_keys:
            continue
        shown_keys.add(key)
        meta = WALLET_META.get(key, {})
        if key == "rs":
            btn_label = f"💰 Pay via Indian Rupees (UPI)"
        else:
            symbol  = meta.get("symbol", key.upper())
            network = meta.get("network", key.upper())
            btn_label = f"💳 Pay via {symbol} · {network}"
        btns.append([InlineKeyboardButton(btn_label, callback_data=f"prem_pay_{key}")])

    # 2. Wallets se buttons (jo upar se nahi aaye)
    for key, address in wallets.items():
        if key in shown_keys:
            continue
        shown_keys.add(key)
        meta = WALLET_META.get(key, {})
        if not meta:
            continue
        if key == "rs":
            btn_label = f"💰 Pay via Indian Rupees (UPI)"
        else:
            symbol  = meta.get("symbol", key.upper())
            network = meta.get("network", key.upper())
            btn_label = f"💳 Pay via {symbol} · {network}"
        btns.append([InlineKeyboardButton(btn_label, callback_data=f"prem_pay_{key}")])

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
# WALLET COMMANDS (Admin)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@Bot.on_message(filters.command("setwallet") & filters.private)
async def cmd_set_wallet(client: Bot, msg: Message):
    """
    /setwallet rs <upi_id>
    /setwallet ton <address>
    /setwallet usdt_ton <address>
    /setwallet usdt_trc <address>
    /setwallet usdt_erc <address>
    """
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")

    parts = msg.command
    if len(parts) < 3:
        lines = ["<b>💳 Wallet Setup Commands:</b>\n"]
        for key, meta in WALLET_META.items():
            lines.append(
                f"<code>/setwallet {key} &lt;address&gt;</code>\n"
                f"  → {meta['name']} ({meta['network']})"
            )
        lines.append("\n<b>Example:</b>")
        lines.append("<code>/setwallet rs myname@upi</code>")
        lines.append("<code>/setwallet ton UQxxxxxxxx</code>")
        lines.append("<code>/setwallet usdt_ton UQxxxxxxxx</code>")
        return await msg.reply("\n".join(lines))

    key     = parts[1].lower()
    address = parts[2]

    if key not in WALLET_META:
        valid = " | ".join(WALLET_META.keys())
        return await msg.reply(
            f"❌ Invalid wallet type: <code>{key}</code>\n\n"
            f"Valid types: <code>{valid}</code>"
        )

    meta = WALLET_META[key]
    await _set_bot_config(meta["db_key"], address)

    label = "UPI ID" if key == "rs" else "Wallet Address"
    await msg.reply(
        f"✅ <b>{meta['name']} ({meta['network']}) Set!</b>\n\n"
        f"• {label}: <code>{address}</code>\n\n"
        f"<i>Ab users /plan se is currency mein payment kar sakte hain.</i>"
    )


@Bot.on_message(filters.command("wallets") & filters.private)
async def cmd_wallets(client: Bot, msg: Message):
    """Saare set wallets + QR status dekho."""
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")

    cfg     = await _get_bot_config()
    wallets = await get_wallets()

    if not wallets:
        return await msg.reply(
            "📭 Koi wallet set nahi hai.\n\n"
            "<code>/setwallet rs myname@upi</code>\n"
            "<code>/setwallet ton UQxxxxxxxxx</code>"
        )

    lines = ["<b>💳 Set Wallets:</b>\n"]
    for key, address in wallets.items():
        meta      = WALLET_META[key]
        label     = "UPI ID" if key == "rs" else "Address"
        qr_set    = "✅" if cfg.get(meta["qr_key"]) else "❌"
        lines.append(
            f"• <b>{meta['name']}</b> ({meta['network']})\n"
            f"  {label}: <code>{address}</code>\n"
            f"  QR: {qr_set}"
        )

    lines.append(
        "\n<b>Commands:</b>\n"
        "<code>/setwallet &lt;key&gt; &lt;address&gt;</code>\n"
        "<code>/setqr &lt;key&gt; &lt;image_url&gt;</code>\n\n"
        "<b>Keys:</b> rs | ton | usdt_ton | usdt_trc | usdt_erc"
    )
    await msg.reply("\n".join(lines))


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

@Bot.on_message(filters.command("setupi") & filters.private)
async def cmd_set_upi(client: Bot, msg: Message):
    """Alias for /setwallet rs"""
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    if len(msg.command) < 2:
        return await msg.reply("<code>/setupi yourname@upi</code>")
    upi = msg.command[1]
    await _set_bot_config("wallet_rs", upi)
    await _set_bot_config("owner_upi_id", upi)  # backward compat
    await msg.reply(f"✅ UPI ID set: <code>{upi}</code>")

@Bot.on_message(filters.command("setqr") & filters.private)
async def cmd_set_qr(client: Bot, msg: Message):
    """
    /setqr <currency_key> <image_url>   → specific currency ka QR set karo
    /setqr <image_url>                  → sirf UPI/RS ka QR set karo (purana style)

    Examples:
      /setqr rs https://image.jpg       → Indian Rupees QR
      /setqr ton https://image.jpg      → TON QR
      /setqr usdt_ton https://image.jpg → USDT (TON) QR
      /setqr usdt_trc https://image.jpg → USDT (TRC20) QR
    """
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")

    parts = msg.command
    if len(parts) < 2:
        valid = " | ".join(WALLET_META.keys())
        return await msg.reply(
            "<b>📌 Usage:</b>\n"
            "<code>/setqr &lt;currency_key&gt; &lt;image_url&gt;</code>\n\n"
            f"<b>Currency keys:</b> <code>{valid}</code>\n\n"
            "<b>Examples:</b>\n"
            "<code>/setqr rs https://image.jpg</code>\n"
            "<code>/setqr ton https://image.jpg</code>\n"
            "<code>/setqr usdt_ton https://image.jpg</code>\n"
            "<code>/setqr usdt_trc https://image.jpg</code>"
        )

    # Agar sirf URL diya (purana style) — rs ka QR set karo
    if len(parts) == 2:
        url = parts[1]
        await _set_bot_config("qr_rs", url)
        await _set_bot_config("qr_code", url)  # backward compat
        return await msg.reply(
            f"✅ <b>Indian Rupees (UPI) QR set!</b>\n\n"
            f"<i>Tip: Doosri currencies ke liye:\n"
            f"/setqr ton &lt;url&gt;\n"
            f"/setqr usdt_ton &lt;url&gt;</i>"
        )

    key = parts[1].lower()
    url = parts[2]

    if key not in WALLET_META:
        valid = " | ".join(WALLET_META.keys())
        return await msg.reply(
            f"❌ Invalid key: <code>{key}</code>\n"
            f"Valid: <code>{valid}</code>"
        )

    meta    = WALLET_META[key]
    qr_key  = meta["qr_key"]
    await _set_bot_config(qr_key, url)
    if key == "rs":
        await _set_bot_config("qr_code", url)  # backward compat

    await msg.reply(
        f"✅ <b>{meta['name']} ({meta['network']}) QR Set!</b>\n\n"
        f"Ab jab user is currency se payment karna chahega,\n"
        f"toh yeh QR dikhega."
    )

@Bot.on_message(filters.command("setcontact") & filters.private)
async def cmd_set_contact(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    if len(msg.command) < 2:
        return await msg.reply("<code>/setcontact https://t.me/yourhandle</code>")
    await _set_bot_config("contact_link", msg.command[1])
    await msg.reply(f"✅ Contact link set: {msg.command[1]}")

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

@Bot.on_message(filters.command("plans") & filters.private)
async def cmd_list_plans(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    plans = await get_star_plans()
    if not plans:
        return await msg.reply("📭 Koi star plan set nahi.\n<code>/setplan 99 1month</code>")
    lines = [f"• ⭐ <b>{s} Stars</b> → {d}" for s, d in sorted(plans.items())]
    await msg.reply("<b>⭐ Star Plans:</b>\n\n" + "\n".join(lines))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CUSTOM PLAN COMMANDS (Admin)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@Bot.on_message(filters.command("setcustomplan") & filters.private)
async def cmd_set_custom_plan(client: Bot, msg: Message):
    """
    /setcustomplan <currency_key> <amount> <duration> <label...>

    currency_key: rs / ton / usdt_ton / usdt_trc / usdt_erc

    Examples:
      /setcustomplan rs 99 1month ₹99 → 1 Month
      /setcustomplan rs 499 1year ₹499 → 1 Year
      /setcustomplan ton 1 1month 1 TON → 1 Month
      /setcustomplan usdt_ton 2 30day 2 USDT → 30 Days
      /setcustomplan usdt_trc 5 1year 5 USDT → 1 Year
    """
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")

    parts = msg.command
    if len(parts) < 5:
        valid = " | ".join(WALLET_META.keys())
        return await msg.reply(
            "<b>Usage:</b>\n"
            "<code>/setcustomplan currency_key amount duration label</code>\n\n"
            f"<b>Currency keys:</b> <code>{valid}</code>\n\n"
            "<b>Examples:</b>\n"
            "<code>/setcustomplan rs 99 1month ₹99 → 1 Month</code>\n"
            "<code>/setcustomplan ton 1 1month 1 TON → 1 Month</code>\n"
            "<code>/setcustomplan usdt_ton 2 30day 2 USDT → 30 Days</code>"
        )

    currency_key = parts[1].lower()
    amount       = parts[2]
    duration     = parts[3]
    label        = " ".join(parts[4:])

    if currency_key not in WALLET_META:
        valid = " | ".join(WALLET_META.keys())
        return await msg.reply(
            f"❌ Invalid currency key: <code>{currency_key}</code>\n"
            f"Valid: <code>{valid}</code>"
        )
    if await get_seconds(duration) <= 0:
        return await msg.reply("❌ Invalid duration! Use: <code>7day / 1month / 1year</code>")

    new_plan = {
        "currency_key": currency_key,
        "currency":     WALLET_META[currency_key]["name"],
        "network":      WALLET_META[currency_key]["network"],
        "amount":       amount,
        "duration":     duration,
        "label":        label,
    }

    plans = await get_custom_plans()
    # Remove duplicate (same currency_key + amount)
    plans = [p for p in plans if not (p.get("currency_key") == currency_key and p.get("amount") == amount)]
    plans.append(new_plan)
    await _set_bot_config("custom_plans", plans)

    meta = WALLET_META[currency_key]
    await msg.reply(
        f"✅ <b>Custom Plan Added!</b>\n\n"
        f"💳 <b>{meta['name']} ({meta['network']})</b>\n"
        f"💰 Amount: <code>{amount}</code>\n"
        f"⏰ Duration: <code>{duration}</code>\n"
        f"🏷 Label: {label}\n\n"
        f"<i>User payment karke /plan mein button dekhega.\n"
        f"Payment ke baad admin ko notification aayega.</i>"
    )

@Bot.on_message(filters.command("removecustomplan") & filters.private)
async def cmd_remove_custom_plan(client: Bot, msg: Message):
    """
    /removecustomplan <currency_key> <amount>
    Example: /removecustomplan rs 99
    """
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")

    parts = msg.command
    if len(parts) < 3:
        plans = await get_custom_plans()
        if not plans:
            return await msg.reply("📭 Koi custom plan nahi.\n<code>/setcustomplan ...</code>")
        lines = [
            f"{i+1}. {p['label']} [{p.get('currency_key','?')} {p['amount']}]"
            for i, p in enumerate(plans)
        ]
        return await msg.reply(
            "<b>Custom Plans:</b>\n\n" + "\n".join(lines) +
            "\n\n<b>Remove:</b> <code>/removecustomplan currency_key amount</code>"
        )

    currency_key = parts[1].lower()
    amount       = parts[2]
    plans        = await get_custom_plans()
    new          = [p for p in plans if not (p.get("currency_key") == currency_key and p.get("amount") == amount)]

    if len(new) == len(plans):
        return await msg.reply(f"❌ Plan nahi mila: {currency_key} {amount}")

    await _set_bot_config("custom_plans", new)
    await msg.reply(f"🗑 Removed: <code>{currency_key} {amount}</code> | Remaining: {len(new)}")

@Bot.on_message(filters.command("customplans") & filters.private)
async def cmd_list_custom_plans(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    plans = await get_custom_plans()
    if not plans:
        return await msg.reply("📭 Koi custom plan nahi.\n<code>/setcustomplan ...</code>")
    lines = [
        f"{i+1}. <b>{p['label']}</b> → {p['duration']}\n"
        f"   {p.get('currency','?')} ({p.get('network','?')}) | Amount: {p.get('amount','?')}"
        for i, p in enumerate(plans)
    ]
    await msg.reply("<b>💳 Custom Plans:</b>\n\n" + "\n\n".join(lines))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PREMIUM MANAGEMENT (Admin)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@Bot.on_message(filters.command("add_premium") & filters.private)
async def cmd_add_premium(client: Bot, msg: Message):
    if not await is_owner_or_admin(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    parts = msg.command
    if len(parts) < 4:
        return await msg.reply(
            "<b>Usage:</b> <code>/add_premium user_id amount unit</code>\n"
            "<b>Example:</b> <code>/add_premium 123456 1 month</code>"
        )
    try:
        user_id = int(parts[1])
    except ValueError:
        return await msg.reply("❌ Invalid user ID!")
    time_str = parts[2] + parts[3]
    seconds  = await get_seconds(time_str)
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
        f"⏰ {parts[2]} {parts[3]}\n⌛ Expiry: {exp_str}"
    )
    try:
        await client.send_message(user_id,
            f"🎉 <b>Premium Activated!</b>\n\nHey {mention}!\n"
            f"⏰ {parts[2]} {parts[3]}\n⌛ Expiry: {exp_str}\n\n"
            f"✅ Shortener ads bypass ho gaye!\nCheck: /myplan"
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

@Bot.on_callback_query(filters.regex("^prem_plans$"), group=-1)
async def cb_plans(client: Bot, cq: CallbackQuery):
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
        await cq.answer()
    except Exception as e:
        logger.error(f"Invoice error: {e}")
        await cq.answer(f"❌ Error. Try again.", show_alert=True)


@Bot.on_callback_query(filters.regex(r"^prem_pay_(\w+)$"), group=-1)
async def cb_pay_currency(client: Bot, cq: CallbackQuery):
    import re
    m   = re.match(r"^prem_pay_(\w+)$", cq.data)
    key = m.group(1) if m else ""

    if key not in WALLET_META:
        return await cq.answer("⚠️ Invalid currency.", show_alert=True)

    meta          = WALLET_META[key]
    wallets       = await get_wallets()
    address       = wallets.get(key, "")
    custom_plans  = await get_custom_plans()
    currency_plans = [p for p in custom_plans if p.get("currency_key") == key]
    ui            = await get_premium_ui()
    cfg           = await _get_bot_config()
    # Currency-specific QR dhundo, fallback global qr_code pe
    qr_code = cfg.get(meta["qr_key"], "") or cfg.get("qr_code", "")

    # Plans text
    if currency_plans:
        plan_lines = "\n".join(
            f"• <b>{p['label']}</b> → {p['duration']}" for p in currency_plans
        )
    else:
        plan_lines = "<i>Kisi plan ke liye admin se contact karo.</i>"

    # Address section
    addr_label = "UPI ID" if key == "rs" else f"Wallet Address"
    if address:
        addr_section = (
            f"<b>{addr_label} ({meta['network']}):</b>\n"
            f"<code>{address}</code>\n\n"
            f"<b>Steps:</b>\n"
            f"1. Upar diye address pe payment karo\n"
            f"2. Niche button se admin ko notify karo\n"
            f"3. Admin verify karke premium activate karega\n\n"
            f"<i>⚠️ Sirf <b>{meta['network']}</b> network use karo!</i>"
        )
    else:
        addr_section = (
            f"<i>Payment address ke liye admin se contact karo.</i>"
        )

    text = (
        f"<b>💳 {meta['name']} ({meta['network']})</b>\n\n"
        f"<b>📋 Plans:</b>\n{plan_lines}\n\n"
        f"{addr_section}"
    )

    # Confirmation buttons
    plan_btns = []
    for p in currency_plans:
        plan_btns.append([InlineKeyboardButton(
            f"✅ Maine {p['label']} Pay Kiya",
            callback_data=f"prem_confirm_{key}_{p['amount']}_{p['duration']}"
        )])

    if not plan_btns:
        plan_btns.append([InlineKeyboardButton(
            "✅ Maine Payment Kar Di", callback_data=f"prem_confirm_{key}_custom_custom"
        )])

    btns = plan_btns + [
        [InlineKeyboardButton("⬅️ Back to Plans", callback_data="prem_plans")],
        [InlineKeyboardButton("❌ Close", callback_data="prem_close")],
    ]

    if ui.get("contact_link"):
        btns.insert(-2, [InlineKeyboardButton("📩 Contact Admin", url=ui["contact_link"])])

    kb = InlineKeyboardMarkup(btns)

    # QR code — har currency ke liye dikhao agar set hai
    if qr_code:
        try:
            await cq.message.reply_photo(photo=qr_code, caption=text, reply_markup=kb)
            return await cq.answer()
        except Exception:
            pass

    try:
        await cq.message.reply_text(text, reply_markup=kb)
    except Exception as e:
        logger.error(f"cb_pay_currency reply failed: {e}")
    await cq.answer()
    await cq.answer()


@Bot.on_callback_query(filters.regex(r"^prem_confirm_"), group=-1)
async def cb_payment_confirm(client: Bot, cq: CallbackQuery):
    """
    User ne "Maine Payment Kar Di" dabaya.
    Format: prem_confirm_<currency_key>_<amount>_<duration>
    → Admin ko notification bhejo with Approve button.
    """
    import re
    m = re.match(r"^prem_confirm_(\w+)_(.+)_(.+)$", cq.data)
    if not m:
        return await cq.answer("⚠️ Invalid data.", show_alert=True)

    currency_key = m.group(1)
    amount       = m.group(2)
    duration     = m.group(3)
    user_id      = cq.from_user.id
    mention      = cq.from_user.mention
    username     = f"@{cq.from_user.username}" if cq.from_user.username else "No username"

    meta = WALLET_META.get(currency_key, {})
    cur_name = f"{meta.get('name','?')} ({meta.get('network','?')})" if meta else currency_key

    # User ko pending message
    await cq.message.reply_text(
        f"⏳ <b>Payment Verification Pending</b>\n\n"
        f"💳 {cur_name}\n"
        f"💰 Amount: {amount}\n"
        f"⏰ Plan: {duration}\n\n"
        f"Admin jald hi verify karega aur premium activate karega.\n"
        f"<i>Agar 24 hours mein activate na ho toh contact karo.</i>",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📩 Contact Admin", url=await _get_contact_link())
        ]]) if await _get_contact_link() else None
    )
    await cq.answer("✅ Request bhej di! Admin jald verify karega.", show_alert=True)

    # Admin ko notification
    ui = await get_premium_ui()
    logs_ch = ui.get("logs_channel") or OWNER_ID

    approve_data = f"prem_approve_{user_id}_{duration}"
    reject_data  = f"prem_reject_{user_id}"

    try:
        await client.send_message(
            logs_ch,
            f"#Payment_Request\n\n"
            f"👤 {mention}\n"
            f"🆔 <code>{user_id}</code>\n"
            f"👤 Username: {username}\n\n"
            f"💳 <b>Currency:</b> {cur_name}\n"
            f"💰 <b>Amount:</b> {amount}\n"
            f"⏰ <b>Plan:</b> {duration}\n\n"
            f"<i>Screenshot check karo aur approve/reject karo.</i>",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Approve", callback_data=approve_data),
                    InlineKeyboardButton("❌ Reject",  callback_data=reject_data),
                ]
            ])
        )
    except Exception as e:
        logger.error(f"Admin notification failed: {e}")
        # Fallback — OWNER ko directly bhejo
        try:
            await client.send_message(
                OWNER_ID,
                f"#Payment_Request\n\n👤 {mention}\n🆔 <code>{user_id}</code>\n"
                f"💳 {cur_name} | 💰 {amount} | ⏰ {duration}",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ Approve", callback_data=approve_data),
                        InlineKeyboardButton("❌ Reject",  callback_data=reject_data),
                    ]
                ])
            )
        except Exception:
            pass


async def _get_contact_link() -> str:
    ui = await get_premium_ui()
    return ui.get("contact_link", "")


@Bot.on_callback_query(filters.regex(r"^prem_approve_"), group=-1)
async def cb_approve_payment(client: Bot, cq: CallbackQuery):
    """Admin ne Approve dabaya → premium activate karo."""
    if not await is_owner_or_admin(cq.from_user.id):
        return await cq.answer("⛔ Permission denied!", show_alert=True)

    import re
    m = re.match(r"^prem_approve_(\d+)_(.+)$", cq.data)
    if not m:
        return await cq.answer("⚠️ Invalid data.", show_alert=True)

    user_id  = int(m.group(1))
    duration = m.group(2)
    seconds  = await get_seconds(duration)

    if seconds <= 0:
        return await cq.answer("❌ Invalid duration in data.", show_alert=True)

    ok = await Seishiro.add_premium(user_id, seconds)
    if not ok:
        return await cq.answer("❌ DB error. Manual add karo: /add_premium", show_alert=True)

    expiry  = await Seishiro.get_premium_expiry(user_id)
    exp_str = fmt_expiry(expiry) if expiry else "N/A"

    # Edit admin message
    try:
        await cq.message.edit_text(
            cq.message.text + f"\n\n✅ <b>APPROVED by {cq.from_user.mention}</b>\n⌛ {exp_str}"
        )
    except Exception:
        pass
    await cq.answer(f"✅ Premium activated for {user_id}!", show_alert=True)

    # User ko notify
    try:
        try:
            u = await client.get_users(user_id); mention = u.mention
        except Exception:
            mention = f"<code>{user_id}</code>"

        await client.send_message(
            user_id,
            f"🎉 <b>Premium Activated!</b>\n\n"
            f"Hey {mention}, aapki payment verify ho gayi!\n\n"
            f"⏰ Plan: <b>{duration}</b>\n"
            f"⌛ Expiry: {exp_str}\n\n"
            f"✅ Shortener ads bypass!\n✅ FSub bypass!\nCheck: /myplan"
        )
    except Exception as e:
        logger.warning(f"User notify failed: {e}")


@Bot.on_callback_query(filters.regex(r"^prem_reject_"), group=-1)
async def cb_reject_payment(client: Bot, cq: CallbackQuery):
    """Admin ne Reject dabaya."""
    if not await is_owner_or_admin(cq.from_user.id):
        return await cq.answer("⛔ Permission denied!", show_alert=True)

    import re
    m = re.match(r"^prem_reject_(\d+)$", cq.data)
    if not m:
        return await cq.answer("⚠️ Invalid data.", show_alert=True)

    user_id = int(m.group(1))

    try:
        await cq.message.edit_text(
            cq.message.text + f"\n\n❌ <b>REJECTED by {cq.from_user.mention}</b>"
        )
    except Exception:
        pass
    await cq.answer("❌ Payment rejected.", show_alert=True)

    try:
        ui = await get_premium_ui()
        contact = ui.get("contact_link", "")
        await client.send_message(
            user_id,
            f"❌ <b>Payment Rejected</b>\n\n"
            f"Aapki payment verify nahi ho saki.\n"
            f"Agar galti lagi hai toh admin se contact karo." +
            (f"\n\n📩 {contact}" if contact else "")
        )
    except Exception as e:
        logger.warning(f"User reject notify failed: {e}")


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
@Bot.on_callback_query(filters.regex("^prem_upi$"), group=-1)
async def cb_upi_alias(client: Bot, cq: CallbackQuery):
    wallets = await get_wallets()
    if "rs" in wallets:
        cq.data = "prem_pay_rs"
        await cb_pay_currency(client, cq)
    else:
        await cq.answer("UPI set nahi hai.", show_alert=True)

@Bot.on_callback_query(filters.regex("^prem_other$"), group=-1)
async def cb_other_alias(client: Bot, cq: CallbackQuery):
    # Show all available currencies
    wallets = await get_wallets()
    if not wallets:
        return await cq.answer("Koi wallet set nahi.", show_alert=True)
    # Show first available
    key    = list(wallets.keys())[0]
    cq.data = f"prem_pay_{key}"
    await cb_pay_currency(client, cq)


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
