"""
plugins/premium.py
══════════════════════════════════════════════════════════
Premium Membership Management + Link Shortener Ads
DreamXBotz ke Premium.py se inspired, is bot ke liye adapt kiya

FEATURES:
  • Admin: /add_premium  /remove_premium  /premium_users  /get_premium
  • User:  /myplan  /plan
  • Telegram Star auto-payment
  • UPI/QR manual payment info
  • shorten_link() — invite link ko ads ke saath wrap karta hai
  • get_invite_link_with_ads() — start.py mein import karke use karo

ENV VARS (Railway / .env):
  PREMIUM_LOGS             = -100xxxxx
  SUBSCRIPTION_IMG         = https://...
  QR_CODE                  = https://...  (optional)
  OWNER_UPI_ID             = upi@bank
  OWNER_LNK                = https://t.me/yourhandle
  IS_SHORTENER_ON          = true
  SHORTENER_API            = <api key from shortener site>
  SHORTENER_WEBSITE        = omegalinks.in
  PREMIUM_BYPASS_SHORTENER = true
══════════════════════════════════════════════════════════
"""

import asyncio
import datetime
import logging
import os

import pytz
from pyrogram import Client, filters
from pyrogram.errors import MessageTooLong
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from config import (
    OWNER_ID,
    OWNER_LNK,
    OWNER_UPI_ID,
    PREMIUM_BYPASS_SHORTENER,
    PREMIUM_LOGS,
    QR_CODE,
    SHORTENER_API,
    SHORTENER_WEBSITE,
    IS_SHORTENER_ON,
    STAR_PREMIUM_PLANS,
    SUBSCRIPTION_IMG,
)
from database.database import Seishiro
from bot import Bot

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


# ══════════════════════════════════════════
# UTILITY FUNCTIONS
# ══════════════════════════════════════════

async def get_seconds(time_string: str) -> int:
    """'1month' / '7day' / '30min' → seconds. DreamXBotz se liya."""
    ts = time_string.strip()
    value, i = "", 0
    while i < len(ts) and ts[i].isdigit():
        value += ts[i]; i += 1
    unit = ts[i:].strip()
    if not value:
        return 0
    v = int(value)
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


async def check_is_admin(user_id: int) -> bool:
    return user_id == OWNER_ID or await Seishiro.is_admin(user_id)


# ══════════════════════════════════════════
# LINK SHORTENER  (DreamXBotz se inspired)
# ══════════════════════════════════════════

async def shorten_link(long_url: str) -> str:
    """
    Shortener API se link shorten karo.
    Agar shortener off hai ya API key missing → original return karo.
    """
    if not IS_SHORTENER_ON or not SHORTENER_API or not SHORTENER_WEBSITE:
        return long_url
    try:
        from shortzy import Shortzy
        shortzy = Shortzy(api_key=SHORTENER_API, base_site=SHORTENER_WEBSITE)
        try:
            return await shortzy.convert(long_url)
        except Exception:
            return await shortzy.get_quick_link(long_url)
    except ImportError:
        logger.warning("shortzy not installed. Run: pip install shortzy")
        return long_url
    except Exception as e:
        logger.error(f"Shortener error: {e}")
        return long_url


async def get_invite_link_with_ads(
    client: Bot,
    user_id: int,
    raw_invite_link: str,
) -> str:
    """
    Invite link ko shortener se pass karo (free users ke liye ads).
    Premium users ko direct link milta hai.

    Usage in start.py:
        from plugins.premium import get_invite_link_with_ads
        invite_link = await get_invite_link_with_ads(client, user_id, raw_link)
    """
    is_premium = await Seishiro.has_premium_access(user_id)
    if is_premium and PREMIUM_BYPASS_SHORTENER:
        logger.info(f"User {user_id} premium → shortener bypassed")
        return raw_invite_link
    return await shorten_link(raw_invite_link)


# ══════════════════════════════════════════
# USER COMMANDS
# ══════════════════════════════════════════

@Bot.on_message(filters.command("myplan") & filters.private)
async def myplan_cmd(client: Bot, message: Message):
    uid     = message.from_user.id
    mention = message.from_user.mention
    expiry  = await Seishiro.get_premium_expiry(uid)
    is_prem = await Seishiro.has_premium_access(uid)

    if is_prem and expiry:
        await message.reply_photo(
            photo=SUBSCRIPTION_IMG,
            caption=(
                f"⚜️ <b>Premium Active</b>\n\n"
                f"👤 {mention}\n"
                f"🆔 <code>{uid}</code>\n"
                f"⏰ Time Left: {time_left_str(expiry)}\n"
                f"⌛ Expiry: {fmt_expiry(expiry)}\n\n"
                f"✅ <i>Shortener Ads Bypassed</i>"
            ),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔥 Extend Plan", callback_data="premium_info")
            ]])
        )
    else:
        await message.reply_photo(
            photo=SUBSCRIPTION_IMG,
            caption=(
                f"<b>Hey {mention},\n\n"
                f"Aapka koi active premium plan nahi hai.\n\n"
                f"⚡ Free users ko link shortener ke ads dekhne padte hain.\n"
                f"💎 Premium users directly channel access karte hain!</b>"
            ),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💎 View Plans", callback_data="premium_info")
            ]])
        )


@Bot.on_message(filters.command("plan") & filters.private)
async def plan_cmd(client: Bot, message: Message):
    plans_text = "\n".join(
        f"• ⭐ <b>{s} Stars</b> → {d}" for s, d in STAR_PREMIUM_PLANS.items()
    )
    await message.reply_photo(
        photo=SUBSCRIPTION_IMG,
        caption=(
            f"<b>💎 Premium Membership</b>\n\n"
            f"<blockquote>"
            f"✅ No Link Shortener Ads\n"
            f"✅ Direct Channel Access\n"
            f"✅ Priority Support\n"
            f"</blockquote>\n\n"
            f"<b>📋 Plans:</b>\n{plans_text}"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⭐ Pay with Stars", callback_data="premium_info")],
            [InlineKeyboardButton("💰 Pay via UPI", callback_data="pay_upi")],
            [InlineKeyboardButton("❌ Close", callback_data="close_plan")],
        ])
    )


# ══════════════════════════════════════════
# ADMIN COMMANDS
# ══════════════════════════════════════════

@Bot.on_message(filters.command("add_premium") & filters.private)
async def add_premium_cmd(client: Bot, message: Message):
    """
    /add_premium <user_id> <amount> <unit>
    Example: /add_premium 123456 1 month
    """
    if not await check_is_admin(message.from_user.id):
        return await message.reply_text("⛔ Sirf admins use kar sakte hain!")

    parts = message.command
    if len(parts) < 4:
        return await message.reply_text(
            "📌 <b>Usage:</b> <code>/add_premium user_id amount unit</code>\n"
            "Example: <code>/add_premium 123456 1 month</code>\n"
            "Units: <code>min / hour / day / month / year</code>"
        )

    try:
        user_id = int(parts[1])
    except ValueError:
        return await message.reply_text("❌ Invalid user ID!")

    time_str = parts[2] + parts[3]
    seconds  = await get_seconds(time_str)
    if seconds <= 0:
        return await message.reply_text("❌ Invalid time. Use: <code>1 day</code>, <code>1 month</code> etc.")

    ok = await Seishiro.add_premium(user_id, seconds)
    if not ok:
        return await message.reply_text("❌ DB error. Try again.")

    expiry  = await Seishiro.get_premium_expiry(user_id)
    exp_str = fmt_expiry(expiry) if expiry else "N/A"
    now_str = datetime.datetime.now(IST).strftime("%d-%m-%Y %I:%M %p IST")

    try:
        u = await client.get_users(user_id); mention = u.mention
    except Exception:
        mention = f"<code>{user_id}</code>"

    await message.reply_text(
        f"✅ <b>Premium Added!</b>\n\n"
        f"👤 {mention} | 🆔 <code>{user_id}</code>\n"
        f"⏰ {parts[2]} {parts[3]}\n⌛ Expiry: {exp_str}"
    )
    try:
        await client.send_message(
            user_id,
            f"🎉 <b>Premium Activated!</b>\n\n"
            f"Hey {mention}, aapka premium activate ho gaya!\n"
            f"⏰ {parts[2]} {parts[3]}\n⌛ Expiry: {exp_str}\n\n"
            f"✅ Shortener ads bypass ho jayenge!\nCheck: /myplan"
        )
    except Exception:
        pass
    try:
        await client.send_message(
            PREMIUM_LOGS,
            f"#Premium_Added\n\n👤 {mention}\n🆔 <code>{user_id}</code>\n"
            f"⏰ {parts[2]} {parts[3]}\n📅 {now_str}\n⌛ Expiry: {exp_str}"
        )
    except Exception as e:
        logger.warning(f"Log failed: {e}")


@Bot.on_message(filters.command("remove_premium") & filters.private)
async def remove_premium_cmd(client: Bot, message: Message):
    if not await check_is_admin(message.from_user.id):
        return await message.reply_text("⛔ Sirf admins use kar sakte hain!")
    if len(message.command) < 2:
        return await message.reply_text("📌 Usage: <code>/remove_premium user_id</code>")
    try:
        user_id = int(message.command[1])
    except ValueError:
        return await message.reply_text("❌ Invalid user ID!")

    ok = await Seishiro.remove_premium(user_id)
    if ok:
        await message.reply_text(f"✅ Premium removed: <code>{user_id}</code>")
        try:
            u = await client.get_users(user_id)
            await client.send_message(user_id,
                f"😔 {u.mention}, aapka premium plan remove ho gaya.\n"
                f"Dobara lene ke liye: /plan")
        except Exception:
            pass
        try:
            await client.send_message(PREMIUM_LOGS, f"#Premium_Removed\n🆔 <code>{user_id}</code>")
        except Exception:
            pass
    else:
        await message.reply_text("❌ User premium mein nahi tha ya DB error.")


@Bot.on_message(filters.command("get_premium") & filters.private)
async def get_premium_cmd(client: Bot, message: Message):
    if not await check_is_admin(message.from_user.id):
        return await message.reply_text("⛔ Sirf admins use kar sakte hain!")
    if len(message.command) < 2:
        return await message.reply_text("📌 Usage: <code>/get_premium user_id</code>")
    try:
        user_id = int(message.command[1])
    except ValueError:
        return await message.reply_text("❌ Invalid user ID!")

    expiry  = await Seishiro.get_premium_expiry(user_id)
    is_prem = await Seishiro.has_premium_access(user_id)
    try:
        u = await client.get_users(user_id); mention = u.mention
    except Exception:
        mention = f"<code>{user_id}</code>"

    if is_prem and expiry:
        await message.reply_text(
            f"⚜️ <b>Premium Data</b>\n\n"
            f"👤 {mention}\n🆔 <code>{user_id}</code>\n"
            f"⏰ Left: {time_left_str(expiry)}\n⌛ Expiry: {fmt_expiry(expiry)}"
        )
    else:
        await message.reply_text(f"❌ {mention} ka koi active premium nahi hai.")


@Bot.on_message(filters.command("premium_users") & filters.private)
async def premium_users_cmd(client: Bot, message: Message):
    if not await check_is_admin(message.from_user.id):
        return await message.reply_text("⛔ Sirf admins use kar sakte hain!")

    wait  = await message.reply_text("<i>Fetching...</i>")
    users = await Seishiro.get_all_premium_users()
    if not users:
        return await wait.edit_text("📭 Koi active premium user nahi hai.")

    lines = ["<b>⚜️ Premium Users List:</b>\n"]
    for i, u in enumerate(users, 1):
        uid    = u.get("_id", "?")
        expiry = u.get("expiry_time")
        try:
            obj = await client.get_users(uid); name = obj.mention
        except Exception:
            name = f"<code>{uid}</code>"
        lines.append(
            f"{i}. {name}\n"
            f"   ID: {uid} | Expiry: {fmt_expiry(expiry) if expiry else 'N/A'} | Left: {time_left_str(expiry) if expiry else '?'}\n"
        )

    text = "\n".join(lines)
    try:
        await wait.edit_text(text)
    except MessageTooLong:
        with open("pm_users.txt", "w") as f:
            f.write(text)
        await message.reply_document("pm_users.txt", caption="Premium Users")
        os.remove("pm_users.txt")


# ══════════════════════════════════════════
# CALLBACKS
# ══════════════════════════════════════════

@Bot.on_callback_query(filters.regex("^premium_info$"))
async def cb_premium_info(client: Bot, cq: CallbackQuery):
    btns = [
        [InlineKeyboardButton(f"⭐ {s} Stars → {d}", callback_data=f"buy_{s}")]
        for s, d in STAR_PREMIUM_PLANS.items()
    ]
    btns += [
        [InlineKeyboardButton("💰 Pay via UPI", callback_data="pay_upi")],
        [InlineKeyboardButton("❌ Close", callback_data="close_plan")],
    ]
    plans_text = "\n".join(f"• ⭐ <b>{s} Stars</b> → {d}" for s, d in STAR_PREMIUM_PLANS.items())
    try:
        await cq.message.edit_caption(
            caption=f"<b>💎 Premium Plans</b>\n\n{plans_text}\n\n<i>Star payment instant & secure hai!</i>",
            reply_markup=InlineKeyboardMarkup(btns)
        )
    except Exception:
        await cq.message.reply_text(
            f"<b>💎 Premium Plans</b>\n\n{plans_text}",
            reply_markup=InlineKeyboardMarkup(btns)
        )
    await cq.answer()


@Bot.on_callback_query(filters.regex(r"^buy_\d+$"))
async def cb_buy_stars(client: Bot, cq: CallbackQuery):
    try:
        amount = int(cq.data.split("_")[1])
        if amount not in STAR_PREMIUM_PLANS:
            return await cq.answer("⚠️ Invalid plan.", show_alert=True)
        dur = STAR_PREMIUM_PLANS[amount]
        await client.send_invoice(
            chat_id=cq.message.chat.id,
            title="Premium Subscription",
            description=f"Pay {amount} Stars → Premium for {dur}",
            payload=f"premium_{amount}",
            currency="XTR",
            prices=[LabeledPrice(label="Premium", amount=amount)],
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="close_plan")
            ]])
        )
        await cq.answer()
    except Exception as e:
        logger.error(f"Invoice error: {e}")
        await cq.answer("❌ Error. Try again.", show_alert=True)


@Bot.on_callback_query(filters.regex("^pay_upi$"))
async def cb_pay_upi(client: Bot, cq: CallbackQuery):
    plans_text = "\n".join(f"• ⭐ {s} Stars ({d})" for s, d in STAR_PREMIUM_PLANS.items())
    text = (
        f"<b>💰 Pay via UPI</b>\n\n"
        f"<b>UPI ID:</b> <code>{OWNER_UPI_ID}</code>\n\n"
        f"<b>Plans:</b>\n{plans_text}\n\n"
        f"Payment ke baad screenshot bhejo: {OWNER_LNK}\n\n"
        f"<i>Manual activation mein 1-6 hours lag sakte hain.</i>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 Contact Owner", url=OWNER_LNK)],
        [InlineKeyboardButton("⬅️ Back", callback_data="premium_info")],
    ])
    if QR_CODE:
        try:
            await cq.message.reply_photo(photo=QR_CODE, caption=text, reply_markup=kb)
            return await cq.answer()
        except Exception:
            pass
    await cq.message.reply_text(text, reply_markup=kb)
    await cq.answer()


@Bot.on_callback_query(filters.regex("^close_plan$"))
async def cb_close_plan(client: Bot, cq: CallbackQuery):
    try:
        await cq.message.delete()
    except Exception:
        pass
    await cq.answer()


# ══════════════════════════════════════════
# TELEGRAM STAR PAYMENT
# ══════════════════════════════════════════

@Bot.on_pre_checkout_query()
async def pre_checkout(client: Bot, query: PreCheckoutQuery):
    if query.payload.startswith("premium_"):
        await query.answer(success=True)
    else:
        await query.answer(success=False, error_message="⚠️ Invalid payment.")


@Bot.on_message(filters.successful_payment & filters.private)
async def on_successful_payment(client: Bot, message: Message):
    try:
        payment = message.successful_payment
        amount  = int(payment.total_amount)
        user_id = message.from_user.id
        mention = message.from_user.mention

        if amount not in STAR_PREMIUM_PLANS:
            return await message.reply("✅ Payment received. Contact support for activation.")

        dur     = STAR_PREMIUM_PLANS[amount]
        seconds = await get_seconds(dur)
        if seconds <= 0:
            return await message.reply("✅ Payment received. Contact support.")

        ok = await Seishiro.add_premium(user_id, seconds)
        if not ok:
            return await message.reply("✅ Payment received! Contact support for manual activation.")

        expiry  = await Seishiro.get_premium_expiry(user_id)
        exp_str = fmt_expiry(expiry) if expiry else "N/A"
        now_str = datetime.datetime.now(IST).strftime("%d-%m-%Y %I:%M %p IST")

        await message.reply(
            f"🎉 <b>Payment Successful!</b>\n\n"
            f"⭐ Stars: <b>{amount}</b>\n"
            f"⏰ Plan: <b>{dur}</b>\n"
            f"⌛ Expiry: {exp_str}\n\n"
            f"✅ Shortener ads ab nahi aayenge!\nCheck: /myplan"
        )
        try:
            await client.send_message(
                PREMIUM_LOGS,
                f"#Star_Payment\n\n👤 {mention}\n🆔 <code>{user_id}</code>\n"
                f"⭐ {amount} Stars → {dur}\n📅 {now_str}\n⌛ {exp_str}"
            )
        except Exception as e:
            logger.warning(f"Log failed: {e}")

    except Exception as e:
        logger.error(f"Payment error: {e}")
        await message.reply("✅ Payment received! Contact support if plan not activated.")
