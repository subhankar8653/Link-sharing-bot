"""
Tutorial Plugin
===============
Commands:
  /set_tutorial_fsub         — FSub tutorial video set karo
  /set_tutorial_linkshortner — LinkShortner tutorial video set karo
  /fsub_tutorial on/off      — FSub tutorial enable/disable karo
  /linkshortner_tutorial on/off — LinkShortner tutorial enable/disable karo

Flow:
  - Jab user FSub join nahi karta → 30s wait
  - 30s mein join kar liya → video nahi jaata
  - 30s baad bhi nahi joya → tutorial video bheja jaata hai (10 min baad auto-delete)
  - LinkShortner ke liye same flow (shortener page pe aaya, ad complete nahi kiya)
"""

import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import Message
from database.database import Seishiro
from bot import Bot
from config import OWNER_ID

logger = logging.getLogger(__name__)


# ── Admin Filter ──────────────────────────────────────────────────────────────

async def _is_admin(user_id: int) -> bool:
    return user_id == OWNER_ID or await Seishiro.is_admin(user_id)

async def admin_filter(_, __, message: Message):
    try:
        return await _is_admin(message.from_user.id)
    except Exception:
        return False

is_admin = filters.create(admin_filter)


# ═══════════════════════════════════════════
# /set_tutorial_fsub
# ═══════════════════════════════════════════

@Bot.on_message(filters.command("set_tutorial_fsub") & filters.private & is_admin)
async def set_tutorial_fsub(client: Bot, message: Message):
    """FSub tutorial video set karo."""
    prompt = await message.reply_text(
        "<b>📹 FSub Tutorial Set</b>\n\n"
        "<blockquote>Ab mujhe woh video bhejo jo FSub join nahi karne wale "
        "users ko dikhana hai.\n\n"
        "⏳ 5 minute ka wait hai.</blockquote>"
    )

    try:
        response: Message = await client.listen(
            chat_id=message.chat.id, timeout=300
        )
    except asyncio.TimeoutError:
        await prompt.edit("<b>⏰ Timeout! Dobara /set_tutorial_fsub try karo.</b>")
        return

    # Video/document check
    file_id = None
    if response.video:
        file_id = response.video.file_id
    elif response.document:
        file_id = response.document.file_id
    elif response.animation:
        file_id = response.animation.file_id

    if not file_id:
        await prompt.edit(
            "<b>❌ Sirf video ya document bhejo!</b>\n"
            "Dobara /set_tutorial_fsub try karo."
        )
        return

    success = await Seishiro.set_tutorial("fsub", file_id)

    try:
        await response.delete()
    except Exception:
        pass

    if success:
        await prompt.edit(
            "<b>✅ FSub Tutorial Video Set Ho Gaya!</b>\n\n"
            "<blockquote>"
            "Ab jo user 30 second mein FSub join nahi karega,\n"
            "usse yeh video jaegi aur 10 min baad delete ho jaegi.\n\n"
            "📌 Tutorial abhi <b>ON</b> hai.\n"
            "Band karne ke liye: <code>/fsub_tutorial off</code>"
            "</blockquote>"
        )
    else:
        await prompt.edit("<b>❌ Save karne mein error. Dobara try karo.</b>")


# ═══════════════════════════════════════════
# /set_tutorial_linkshortner
# ═══════════════════════════════════════════

@Bot.on_message(filters.command("set_tutorial_linkshortner") & filters.private & is_admin)
async def set_tutorial_linkshortner(client: Bot, message: Message):
    """LinkShortner tutorial video set karo."""
    prompt = await message.reply_text(
        "<b>📹 LinkShortner Tutorial Set</b>\n\n"
        "<blockquote>Ab mujhe woh video bhejo jo link shortner "
        "complete nahi karne wale users ko dikhana hai.\n\n"
        "⏳ 5 minute ka wait hai.</blockquote>"
    )

    try:
        response: Message = await client.listen(
            chat_id=message.chat.id, timeout=300
        )
    except asyncio.TimeoutError:
        await prompt.edit("<b>⏰ Timeout! Dobara /set_tutorial_linkshortner try karo.</b>")
        return

    file_id = None
    if response.video:
        file_id = response.video.file_id
    elif response.document:
        file_id = response.document.file_id
    elif response.animation:
        file_id = response.animation.file_id

    if not file_id:
        await prompt.edit(
            "<b>❌ Sirf video ya document bhejo!</b>\n"
            "Dobara /set_tutorial_linkshortner try karo."
        )
        return

    success = await Seishiro.set_tutorial("linkshortner", file_id)

    try:
        await response.delete()
    except Exception:
        pass

    if success:
        await prompt.edit(
            "<b>✅ LinkShortner Tutorial Video Set Ho Gaya!</b>\n\n"
            "<blockquote>"
            "Ab jo user shortener complete nahi karega,\n"
            "usse yeh video jaegi aur 10 min baad delete ho jaegi.\n\n"
            "📌 Tutorial abhi <b>ON</b> hai.\n"
            "Band karne ke liye: <code>/linkshortner_tutorial off</code>"
            "</blockquote>"
        )
    else:
        await prompt.edit("<b>❌ Save karne mein error. Dobara try karo.</b>")


# ═══════════════════════════════════════════
# /fsub_tutorial on/off
# ═══════════════════════════════════════════

@Bot.on_message(filters.command("fsub_tutorial") & filters.private & is_admin)
async def toggle_fsub_tutorial(client: Bot, message: Message):
    """FSub tutorial on ya off karo."""
    args = message.command
    if len(args) < 2 or args[1].lower() not in ("on", "off"):
        status = await Seishiro.get_tutorial_status("fsub")
        current = "✅ ON" if status["enabled"] else "❌ OFF"
        set_info = "✅ Set hai" if status["exists"] else "❌ Set nahi hai"
        await message.reply_text(
            f"<b>📹 FSub Tutorial Status</b>\n\n"
            f"<blockquote>"
            f"Video: {set_info}\n"
            f"Status: {current}\n\n"
            f"Usage: <code>/fsub_tutorial on</code>\n"
            f"       <code>/fsub_tutorial off</code>"
            f"</blockquote>"
        )
        return

    action = args[1].lower()
    enabled = (action == "on")

    status = await Seishiro.get_tutorial_status("fsub")
    if enabled and not status["exists"]:
        await message.reply_text(
            "<b>❌ Pehle tutorial video set karo!</b>\n"
            "Command: <code>/set_tutorial_fsub</code>"
        )
        return

    ok = await Seishiro.toggle_tutorial("fsub", enabled)
    if ok:
        emoji = "✅" if enabled else "❌"
        await message.reply_text(
            f"<b>{emoji} FSub Tutorial {'ON' if enabled else 'OFF'} Ho Gaya!</b>"
        )
    else:
        await message.reply_text(
            "<b>❌ Update nahi hua. Pehle /set_tutorial_fsub se video set karo.</b>"
        )


# ═══════════════════════════════════════════
# /linkshortner_tutorial on/off
# ═══════════════════════════════════════════

@Bot.on_message(filters.command("linkshortner_tutorial") & filters.private & is_admin)
async def toggle_linkshortner_tutorial(client: Bot, message: Message):
    """LinkShortner tutorial on ya off karo."""
    args = message.command
    if len(args) < 2 or args[1].lower() not in ("on", "off"):
        status = await Seishiro.get_tutorial_status("linkshortner")
        current = "✅ ON" if status["enabled"] else "❌ OFF"
        set_info = "✅ Set hai" if status["exists"] else "❌ Set nahi hai"
        await message.reply_text(
            f"<b>📹 LinkShortner Tutorial Status</b>\n\n"
            f"<blockquote>"
            f"Video: {set_info}\n"
            f"Status: {current}\n\n"
            f"Usage: <code>/linkshortner_tutorial on</code>\n"
            f"       <code>/linkshortner_tutorial off</code>"
            f"</blockquote>"
        )
        return

    action = args[1].lower()
    enabled = (action == "on")

    status = await Seishiro.get_tutorial_status("linkshortner")
    if enabled and not status["exists"]:
        await message.reply_text(
            "<b>❌ Pehle tutorial video set karo!</b>\n"
            "Command: <code>/set_tutorial_linkshortner</code>"
        )
        return

    ok = await Seishiro.toggle_tutorial("linkshortner", enabled)
    if ok:
        emoji = "✅" if enabled else "❌"
        await message.reply_text(
            f"<b>{emoji} LinkShortner Tutorial {'ON' if enabled else 'OFF'} Ho Gaya!</b>"
        )
    else:
        await message.reply_text(
            "<b>❌ Update nahi hua. Pehle /set_tutorial_linkshortner se video set karo.</b>"
        )


# ═══════════════════════════════════════════
# CORE TUTORIAL SENDER FUNCTIONS
# (start.py se import karke use karo)
# ═══════════════════════════════════════════

async def send_fsub_tutorial_if_not_joined(client: Bot, user_id: int, check_func):
    """
    30 second wait karo.
    Agar user join kar leta hai → kuch mat karo.
    Agar nahi kiya → tutorial video bhejo (10 min baad delete).

    check_func: async function jo user_id leke True/False return kare
                (True = user ne join kar liya)
    """
    tutorial = await Seishiro.get_tutorial("fsub")
    if not tutorial:
        return  # Tutorial set nahi ya disabled

    await asyncio.sleep(30)

    # Check karo user ne join kiya ya nahi
    try:
        joined = await check_func(user_id)
    except Exception as e:
        logger.error(f"fsub tutorial check_func error: {e}")
        return

    if joined:
        return  # Join kar liya, tutorial ki zarurat nahi

    # Tutorial video bhejo
    try:
        sent = await client.send_video(
            chat_id=user_id,
            video=tutorial["file_id"],
            caption=(
                "<b>📹 FSub Join Kaise Karein?</b>\n\n"
                "<blockquote>"
                "Lagta hai aapko channel join karne mein problem aa rahi hai.\n"
                "Upar diya gaya tutorial dekho aur step follow karo! 👆\n\n"
                "⏰ Yeh message 10 minute mein delete ho jaega."
                "</blockquote>"
            )
        )
        # 10 min baad delete
        asyncio.create_task(_delete_after(sent, 600))
        logger.info(f"FSub tutorial sent to user {user_id}")
    except Exception as e:
        logger.error(f"send_fsub_tutorial error for {user_id}: {e}")


async def send_linkshortner_tutorial_if_not_verified(client: Bot, user_id: int, token: str):
    """
    30 second wait karo.
    Agar user ne verify kar liya (token used) → kuch mat karo.
    Agar nahi → tutorial video bhejo (10 min baad delete).
    """
    tutorial = await Seishiro.get_tutorial("linkshortner")
    if not tutorial:
        return

    await asyncio.sleep(30)

    # Token used hua kya check karo
    try:
        doc = await Seishiro.get_verify_token(token)
        if doc and doc.get("used"):
            return  # User ne complete kar liya
    except Exception as e:
        logger.error(f"linkshortner tutorial token check error: {e}")
        return

    # Tutorial video bhejo
    try:
        sent = await client.send_video(
            chat_id=user_id,
            video=tutorial["file_id"],
            caption=(
                "<b>📹 Link Shortner Kaise Complete Karein?</b>\n\n"
                "<blockquote>"
                "Lagta hai aapko link shortener complete karne mein problem aa rahi hai.\n"
                "Upar diya gaya tutorial dekho aur step follow karo! 👆\n\n"
                "⏰ Yeh message 10 minute mein delete ho jaega."
                "</blockquote>"
            )
        )
        asyncio.create_task(_delete_after(sent, 600))
        logger.info(f"LinkShortner tutorial sent to user {user_id}")
    except Exception as e:
        logger.error(f"send_linkshortner_tutorial error for {user_id}: {e}")


async def _delete_after(msg, delay: int):
    """delay seconds baad message delete karo."""
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except Exception:
        pass
