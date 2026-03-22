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
