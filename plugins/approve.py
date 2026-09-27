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
    - Registered normal channels (jo /getlink se add ki gayi hain): Auto-approve karo
    - Koi bhi random/unregistered channel (bot sirf admin hai, /getlink se add
      nahi ki gayi): Bot kuchh nahi karega, request untouched chhod dega
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

        if is_fsub_channel:
            await Seishiro.req_user(chat.id, user.id)
            await Seishiro.increment_fsub_request_count(chat.id)
            print(f"✅ FSUB: Added {user.id} to request database (NO auto-approve)")
            # Real-time: agar is user ka koi /auto_check stepwise session chal raha
            # hai, to turant agla step dikha do — poll ka wait nahi karna.
            try:
                from plugins.start import notify_fsub_event
                asyncio.create_task(notify_fsub_event(client, user.id))
            except Exception as e:
                print(f"⚠️ notify_fsub_event trigger error: {e}")
            return

        # ── Registered channel check ───────────────────────────────────
        # Sirf un channels mein auto-approve karo jo /getlink (Add Channel)
        # se bot ke system mein register ki gayi hain. Koi aur channel
        # jaha bot sirf admin hai (registered nahi), use ignore karo.
        registered_channels = await Seishiro.get_channels()
        if chat.id not in registered_channels:
            print(f"⏭️ {chat.title} ({chat.id}) is not a registered channel — ignoring join request")
            return

        print(f"✅ This is a registered NORMAL channel")

        # ── Bot ke apne link se aayi request? ──────────────────────────
        # Agar is user+channel ke liye pehle se ek invite-link doc saved
        # hai (save_user_request_link se, jab bot ne file/link diya tha),
        # to ye request definitely bot ke flow se aayi hai — isko
        # "Auto Request Accept" toggle se independent hamesha approve
        # karna hai. Toggle sirf organic/random requests ko control kare.
        own_link_doc = await Seishiro.get_user_request_doc(user.id, chat.id)
        came_from_bot_link = bool(own_link_doc)

        if came_from_bot_link:
            print(f"🔗 {user.id} bot ke apne link se aaya hai — toggle ignore, force approve")
        else:
            # ── Auto Request Accept setting check ─────────────────────
            # Ye sirf organic requests (bina bot link ke) pe apply hoga.
            auto_accept_on = await Seishiro.get_auto_accept()
            if not auto_accept_on:
                print(f"⏸️ Auto Request Accept OFF hai — skipping auto-approve for {user.id} in {chat.title}")
                return

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

        if new_status in ["member", "administrator", "creator"] and old_status not in ["member", "administrator", "creator"]:
            # Real-time: agar is user ka koi /auto_check stepwise session chal raha
            # hai, to turant agla step dikha do — poll ka wait nahi karna.
            try:
                from plugins.start import notify_fsub_event
                asyncio.create_task(notify_fsub_event(client, user.id))
            except Exception as e:
                print(f"⚠️ notify_fsub_event trigger error: {e}")

            try:
                # ── Fsub stats: is channel ke fsub se hi yeh join hua? Tabhi count karo ──
                fsub_channels = await Seishiro.get_fsub_channels()
                if chat.id in fsub_channels:
                    await Seishiro.increment_fsub_join_count(chat.id)
                    print(f"📊 Fsub join_count +1 for {chat.title} ({chat.id})")

                exists = await Seishiro.req_user_exist(chat.id, user.id)
                if exists:
                    await Seishiro.del_req_user(chat.id, user.id)
                    print(f"✅ User {user.id} approved in {chat.title} - Removed from request DB")
                    await _send_approve_notification(client, user, chat)
            except Exception as e:
                print(f"⚠️ Error cleaning request for {user.id}: {e}")

    except Exception as e:
        print(f"Error in on_member_approved: {e}")
