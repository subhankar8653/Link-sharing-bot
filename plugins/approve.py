import os
import asyncio
from bot import Bot
from config import *
from pyrogram import Client, filters
from pyrogram.types import Message, User, ChatJoinRequest, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, ChatAdminRequired, UserNotParticipant, UserAlreadyParticipant
from helper_func import *

# 🔥 Auto-approve disabled - not needed anymore
AUTO_APPROVE_ENABLED = true

@Client.on_chat_join_request((filters.group | filters.channel))
async def on_join_request(client: Bot, message: ChatJoinRequest):
    """
    🔥 NEW LOGIC: Jab user request bhejta hai, turant database mein add kar do
    No approval needed - request bhejne se hi bot recognize kar lega
    """
    from database.database import Seishiro
    
    chat = message.chat
    user = message.from_user
    
    print(f"✅ Join request received from {user.first_name} ({user.id}) for {chat.title} ({chat.id})")
    
    try:
        # 🔥 IMPORTANT: Request ko database mein save karo
        await Seishiro.req_user(chat.id, user.id)
        print(f"✅ Added {user.id} to request database for channel {chat.id}")
        
        # Optional: User ko message bhej sakte ho ki request received
        # (Agar chahte ho toh uncomment kar do)
        """
        try:
            await client.send_message(
                chat_id=user.id,
                text=(
                    f"<b>✅ Request Received!</b>\n\n"
                    f"Your request to join <b>{chat.title}</b> has been detected.\n"
                    f"You can now use the bot!"
                )
            )
        except:
            pass
        """
        
    except Exception as e:
        print(f"❌ Error adding user {user.id} to request database: {e}")


# 🔥 NEW: Detect when admin manually approves (optional cleanup)
@Client.on_chat_member_updated((filters.group | filters.channel))
async def on_member_approved(client: Bot, update):
    """
    Jab admin manually approve kar deta hai, database se request remove karo
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
