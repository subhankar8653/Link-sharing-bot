import os
import asyncio
from bot import Bot
from config import *
from pyrogram import Client, filters, raw
from pyrogram.types import Message, User, ChatJoinRequest, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, ChatAdminRequired, UserNotParticipant, UserAlreadyParticipant
from helper_func import *


async def _get_last_message_link(client: Bot, chat_id: int) -> str | None:
    """
    Private channel ka last message link banao.
    Format: https://t.me/c/CHANNEL_ID_WITHOUT_MINUS100/MSG_ID
    
    Raw API use karta hai — get_chat_history se zyada reliable.
    """
    try:
        # -100XXXXXXXXXX → XXXXXXXXXX
        raw_id = str(chat_id)
        if raw_id.startswith("-100"):
            raw_id = raw_id[4:]

        # Raw API: GetHistory se sirf 1 message fetch karo
        peer = await client.resolve_peer(chat_id)
        history = await client.invoke(
            raw.functions.messages.GetHistory(
                peer=peer,
                offset_id=0,
                offset_date=0,
                add_offset=0,
                limit=1,
                max_id=0,
                min_id=0,
                hash=0
            )
        )

        # messages list mein pehla item last message hai
        if history.messages:
            last_id = history.messages[0].id
            return f"https://t.me/c/{raw_id}/{last_id}"

        return None

    except Exception as e:
        print(f"⚠️ _get_last_message_link error for {chat_id}: {e}")
        return None

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
        # 🔥 Check: Yeh channel FSub channel hai ya normal channel?
        is_fsub_channel = False
        
        # Check in fsub channels
        fsub_channels = await Seishiro.get_fsub_channels()
        if chat.id in fsub_channels:
            is_fsub_channel = True
            print(f"✅ This is a FSUB channel")
        else:
            print(f"✅ This is a NORMAL channel")
        
        if is_fsub_channel:
            # 🔥 FSub Channel: Sirf database mein add karo, approve NAHI karo
            await Seishiro.req_user(chat.id, user.id)
            print(f"✅ FSUB: Added {user.id} to request database (NO auto-approve)")
            
        else:
            # 🔥 Normal Channel: Auto-approve karo
            await asyncio.sleep(1)
            
            # Check if already member
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
            
            # Auto-approve the request
            try:
                await client.approve_chat_join_request(chat_id=chat.id, user_id=user.id)
                print(f"✅ NORMAL: Auto-approved {user.first_name} ({user.id})")
                
                # ── Approve Notification DM ──────────────────────────────
                await _send_approve_notification(client, user, chat)
                
            except UserAlreadyParticipant:
                print(f"User {user.id} is already a participant")
            except Exception as e:
                print(f"❌ Error approving: {e}")
        
    except Exception as e:
        print(f"❌ Error in on_join_request: {e}")


async def _send_approve_notification(client: Bot, user, chat):
    """
    Jab user approve ho jaye, usse DM bhejo:
    - Channel ka last message ka direct link (private channel link format)
    - Purana 'HERE IS YOUR LINK' message delete karo
    - Notification message bhi 5 min baad auto-delete
    """
    from database.database import Seishiro

    try:
        # ── Purana link_msg delete karo ───────────────────────────────
        doc = await Seishiro.get_user_request_doc(user.id, chat.id)
        if doc:
            old_msg_id   = doc.get("link_msg_id")
            old_chat_id  = doc.get("link_chat_id")
            if old_msg_id and old_chat_id:
                try:
                    await client.delete_messages(old_chat_id, old_msg_id)
                    print(f"🗑️ Deleted old link_msg {old_msg_id} for user {user.id}")
                except Exception as e:
                    print(f"⚠️ Could not delete old link_msg: {e}")

        # ── Channel ka last message link fetch karo ───────────────────
        join_url = await _get_last_message_link(client, chat.id)

        # Fallback: agar kisi wajah se link na mile
        if not join_url:
            try:
                if chat.username:
                    join_url = f"https://t.me/{chat.username}"
            except Exception:
                pass

        # ── Approve notification DM bhejo ─────────────────────────────
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

        # ── Cleanup: 5 min baad delete + DB entry hata do ─────────────
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
        
        # Agar user approved ho gaya (member ban gaya)
        if new_status in ["member", "administrator", "creator"] and old_status != new_status:
            try:
                # Database se request remove karo
                exists = await Seishiro.req_user_exist(chat.id, user.id)
                if exists:
                    await Seishiro.del_req_user(chat.id, user.id)
                    print(f"✅ User {user.id} approved in {chat.title} - Removed from request DB")
                    
                    # ── Notification bhejo (manually approved users ke liye bhi) ──
                    await _send_approve_notification(client, user, chat)
                    
            except Exception as e:
                print(f"⚠️ Error cleaning request for {user.id}: {e}")
                
    except Exception as e:
        print(f"Error in on_member_approved: {e}")
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
        # 🔥 Check: Yeh channel FSub channel hai ya normal channel?
        is_fsub_channel = False
        
        # Check in fsub channels
        fsub_channels = await Seishiro.get_fsub_channels()
        if chat.id in fsub_channels:
            is_fsub_channel = True
            print(f"✅ This is a FSUB channel")
        else:
            print(f"✅ This is a NORMAL channel")
        
        if is_fsub_channel:
            # 🔥 FSub Channel: Sirf database mein add karo, approve NAHI karo
            await Seishiro.req_user(chat.id, user.id)
            print(f"✅ FSUB: Added {user.id} to request database (NO auto-approve)")
            
        else:
            # 🔥 Normal Channel: Auto-approve karo
            await asyncio.sleep(1)
            
            # Check if already member
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
            
            # Auto-approve the request
            try:
                await client.approve_chat_join_request(chat_id=chat.id, user_id=user.id)
                print(f"✅ NORMAL: Auto-approved {user.first_name} ({user.id})")
            except UserAlreadyParticipant:
                print(f"User {user.id} is already a participant")
            except Exception as e:
                print(f"❌ Error approving: {e}")
        
    except Exception as e:
        print(f"❌ Error in on_join_request: {e}")


@Client.on_chat_member_updated((filters.group | filters.channel))
async def on_member_approved(client: Bot, update):
    """
    Jab admin manually approve kar deta hai (fsub channel), database se cleanup karo
    """
    try:
        from database.database import Seishiro
        
        if not update.new_chat_member:
            return
            
        user = update.new_chat_member.user
        chat = update.chat
        
        old_status = update.old_chat_member.status if update.old_chat_member else None
        new_status = update.new_chat_member.status
        
        # Agar user approved ho gaya (member ban gaya)
        if new_status in ["member", "administrator", "creator"] and old_status != new_status:
            try:
                # Database se request remove karo
                exists = await Seishiro.req_user_exist(chat.id, user.id)
                if exists:
                    await Seishiro.del_req_user(chat.id, user.id)
                    print(f"✅ User {user.id} approved in {chat.title} - Removed from request DB")
            except Exception as e:
                print(f"⚠️ Error cleaning request for {user.id}: {e}")
                
    except Exception as e:
        print(f"Error in on_member_approved: {e}")
