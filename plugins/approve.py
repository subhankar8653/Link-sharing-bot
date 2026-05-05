import os
import asyncio
from bot import Bot
from config import *
from pyrogram import Client, filters
from pyrogram.types import Message, User, ChatJoinRequest, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, ChatAdminRequired, UserNotParticipant, UserAlreadyParticipant
from helper_func import *

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
    - Congratulations message
    - Original request link (taaki woh join kar sake)
    - Auto-delete 5 min baad
    """
    from database.database import Seishiro
    
    try:
        # User ka stored request link fetch karo
        req_encoded = await Seishiro.get_user_request_link(user.id, chat.id)
        
        if req_encoded:
            # Original request link reconstruct karo
            join_link = f"https://t.me/{BOT_USERNAME}?start=req_{req_encoded}"
        else:
            # Fallback: fresh invite link banao
            try:
                from datetime import datetime, timedelta
                inv = await client.create_chat_invite_link(
                    chat_id=chat.id,
                    expire_date=datetime.now() + timedelta(minutes=5),
                    creates_join_request=False  # Direct join link
                )
                join_link = inv.invite_link
            except Exception as e:
                print(f"Fallback invite link error: {e}")
                join_link = None
        
        # DM bhejo
        text = (
            f"<b>✅ Aapki request accept kar li gayi!</b>\n\n"
            f"<blockquote>"
            f"<b>Channel:</b> {chat.title}\n\n"
            f"Niche button pe click karke channel join karein.\n"
            f"<i>⚠️ Yeh link 5 minute mein auto-delete ho jayega.</i>"
            f"</blockquote>"
        )
        
        buttons = []
        if join_link:
            buttons.append([InlineKeyboardButton("• ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟ •", url=join_link)])
        
        sent_msg = await client.send_message(
            chat_id=user.id,
            text=text,
            reply_markup=InlineKeyboardMarkup(buttons) if buttons else None
        )
        
        # Cleanup: 5 min baad message delete karo + stored link delete
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
