import os
import asyncio
from bot import Bot
from config import *
from pyrogram import Client, filters
from pyrogram.types import Message, User, ChatJoinRequest, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, ChatAdminRequired, UserNotParticipant, UserAlreadyParticipant
from helper_func import *

# 🔥 CHANGE 2: Auto-approve disabled kar diya
AUTO_APPROVE_ENABLED = False

@Client.on_chat_join_request((filters.group | filters.channel))
async def auto_approve(client: Bot, message: ChatJoinRequest):
    global AUTO_APPROVE_ENABLED
    chat = message.chat
    user = message.from_user
    
    # 🔥 CRITICAL FIX: Check if auto-approve is enabled
    if not AUTO_APPROVE_ENABLED:
        print(f"❌ {user.first_name} requested to join {chat.title} - Auto-approve is DISABLED")
        print(f"ℹ️  Admin needs to manually approve this request")
        return  # Exit without approving
    
    print(f"✅ {user.first_name} requested to join {chat.title} - Auto-approve is ENABLED")
    
    await asyncio.sleep(2)
    
    # Check if user is already a participant before approving
    try:
        member = await client.get_chat_member(chat.id, user.id)
        if member.status in ["member", "administrator", "creator"]:
            print(f"User {user.id} is already a participant of {chat.id}, skipping approval.")
            return
    except UserNotParticipant:
        # User is not a participant, proceed with approval
        pass
    except Exception as e:
        print(f"Error checking membership: {e}")
        return
    
    # Approve the join request
    try:
        await client.approve_chat_join_request(chat_id=chat.id, user_id=user.id)
        print(f"Approved join request for {user.first_name} ({user.id})")
    except UserAlreadyParticipant:
        print(f"User {user.id} is already a participant.")
        return
    except Exception as e:
        print(f"Error approving join request: {e}")
        return
    
    print(f"Request approved for {user.first_name} ({user.id}) - No message sent to user")


# 🔥 NEW: Handler for when member status changes (manual approval detection)
@Client.on_chat_member_updated((filters.group | filters.channel))
async def on_chat_member_updated(client: Bot, update: ChatMemberUpdated):
    """
    Yeh handler tab trigger hota hai jab kisi user ka status change hota hai.
    Jab admin manually request approve karta hai, tab yeh detect kar leta hai.
    """
    try:
        from database.database import Seishiro
        
        chat = update.chat
        user = update.new_chat_member.user if update.new_chat_member else None
        
        if not user:
            return
        
        old_status = update.old_chat_member.status if update.old_chat_member else None
        new_status = update.new_chat_member.status if update.new_chat_member else None
        
        # Agar user ka status change hua hai aur ab member ban gaya hai
        if new_status in ["member", "administrator", "creator"] and old_status != new_status:
            # Database se request remove karo (cleanup)
            try:
                # Check if this user had pending request in database
                req_exists = await Seishiro.req_user_exist(chat.id, user.id)
                if req_exists:
                    await Seishiro.del_req_user(chat.id, user.id)
                    print(f"✅ User {user.id} ({user.first_name}) approved in {chat.title} - Removed from request DB")
                else:
                    print(f"ℹ️  User {user.id} ({user.first_name}) joined {chat.title} (no pending request in DB)")
            except Exception as e:
                print(f"⚠️  Error cleaning up request for user {user.id}: {e}")
                
    except Exception as e:
        print(f"Error in on_chat_member_updated: {e}")
