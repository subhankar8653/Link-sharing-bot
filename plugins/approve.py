import os
import asyncio
from bot import Bot
from config import *
from pyrogram import Client, filters
from pyrogram.types import Message, User, ChatJoinRequest, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, ChatAdminRequired, UserNotParticipant, UserAlreadyParticipant
from helper_func import *


async def _send_approve_notification(client: Bot, user, chat):
    """
    Jab user approve ho jaye:
    1. Purana 'HERE IS YOUR LINK' message delete karo
    2. Wahi invite link button mein do jo pehle generate hua tha (DB se)
    3. Notification 5 min baad auto-delete
    """
    from database.database import Seishiro

    try:
        doc = await Seishiro.get_user_request_doc(user.id, chat.id)

        # ── Purana link_msg delete karo ───────────────────────────────
        if doc:
            old_msg_id  = doc.get("link_msg_id")
            old_chat_id = doc.get("link_chat_id")
            if old_msg_id and old_chat_id:
                try:
                    await client.delete_messages(old_chat_id, old_msg_id)
                    print(f"🗑️ Deleted old link_msg {old_msg_id} for user {user.id}")
                except Exception as e:
                    print(f"⚠️ Could not delete old link_msg: {e}")

        # ── Saved invite link use karo (wahi jo pehle diya tha) ───────
        join_url = doc.get("invite_link") if doc else None

        # Approve notification DM
        text = (
            f"<b>✅ Aapki request accept kar li gayi!</b>\n\n"
            f"<blockquote>"
            f"<b>Channel:</b> {chat.title}\n\n"
            f"Niche button pe click karke channel join karein.\n"
            f"<i>⚠️ Yeh message 5 minute mein auto-delete ho jayega.</i>"
            f"</blockquote>"
        )

        buttons = []
        if join_url:
            buttons.append([InlineKeyboardButton("• ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ •", url=join_url)])

        sent_msg = await client.send_message(
            chat_id=user.id,
            text=text,
            reply_markup=InlineKeyboardMarkup(buttons) if buttons else None
        )

        # 5 min baad cleanup
        async def cleanup():
            await asyncio.sleep(300)
            try:
                await sent_msg.delete()
            except Exception:
                pass
            try:
                await Seishiro.delete_user_request_link(user.id, chat.id)
            except Exception:
                pass

        asyncio.create_task(cleanup())
        print(f"✅ Approve notification sent to {user.id} for {chat.title}")

    except Exception as e:
        print(f"⚠️ Could not send approve notification to {user.id}: {e}")


@Client.on_chat_join_request((filters.group | filters.channel))
async def on_join_request(client: Bot, message: ChatJoinRequest):
    """
    🔥 SMART LOGIC:
    - FSub channels: Sirf detect karo, auto-approve NAHI
    - Normal channels: Auto-approve karo
    """
    from database.database import Seishiro

    chat = message.chat
    user = message.from_user

    print(f"📥 Join request from {user.first_name} ({user.id}) for {chat.title} ({chat.id})")

    try:
        is_fsub_channel = False
        fsub_channels = await Seishiro.get_fsub_channels()
        if chat.id in fsub_channels:
            is_fsub_channel = True
            print(f"✅ This is a FSUB channel")
        else:
            print(f"✅ This is a NORMAL channel")

        if is_fsub_channel:
            await Seishiro.req_user(chat.id, user.id)
            print(f"✅ FSUB: Added {user.id} to request database (NO auto-approve)")

        else:
            await asyncio.sleep(1)

            try:
                member = await client.get_chat_member(chat.id, user.id)
                if member.status in ["member", "administrator", "creator"]:
                    print(f"User {user.id} is already a member, skipping")
                    return
            except UserNotParticipant:
                pass
            except Exception as e:
                print(f"Error checking membership: {e}")
                return

            try:
                await client.approve_chat_join_request(chat_id=chat.id, user_id=user.id)
                print(f"✅ NORMAL: Auto-approved {user.first_name} ({user.id})")
                await _send_approve_notification(client, user, chat)
            except UserAlreadyParticipant:
                print(f"User {user.id} is already a participant")
            except Exception as e:
                print(f"❌ Error approving: {e}")

    except Exception as e:
        print(f"❌ Error in on_join_request: {e}")


@Client.on_chat_member_updated((filters.group | filters.channel))
async def on_member_approved(client: Bot, update):
    """
    Jab admin manually approve kar deta hai (fsub channel),
    database se cleanup karo + notification bhejo
    """
    try:
        from database.database import Seishiro

        if not update.new_chat_member:
            return

        user = update.new_chat_member.user
        chat = update.chat

        old_status = update.old_chat_member.status if update.old_chat_member else None
        new_status = update.new_chat_member.status

        if new_status in ["member", "administrator", "creator"] and old_status != new_status:
            try:
                exists = await Seishiro.req_user_exist(chat.id, user.id)
                if exists:
                    await Seishiro.del_req_user(chat.id, user.id)
                    print(f"✅ User {user.id} approved in {chat.title} - Removed from request DB")
                    await _send_approve_notification(client, user, chat)
            except Exception as e:
                print(f"⚠️ Error cleaning request for {user.id}: {e}")

    except Exception as e:
        print(f"Error in on_member_approved: {e}")
