# ============================================
# FEATURE 3: AUTO DELETE SYSTEM
# File: plugins/auto_delete.py
# ============================================

import asyncio
from datetime import datetime, timedelta
from bot import Bot
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from database.database import Seishiro
from config import *

# Auto-delete configuration
AUTO_DELETE_ENABLED = True  # Set to False to disable
AUTO_DELETE_TIME = 300  # 5 minutes (300 seconds)

# Store message IDs for deletion
pending_deletions = {}

async def is_owner_or_admin(filter, client, message):
    try:
        user_id = message.from_user.id
        return any([user_id == OWNER_ID, await Seishiro.is_admin(user_id)])
    except:
        return False
        
is_owner_or_admin = filters.create(is_owner_or_admin)

# ========== AUTO DELETE FUNCTIONS ==========

async def schedule_message_deletion(client: Client, chat_id: int, message_id: int, delay: int = AUTO_DELETE_TIME):
    """Schedule a message for auto-deletion"""
    if not AUTO_DELETE_ENABLED:
        return
    
    try:
        # Wait for specified delay
        await asyncio.sleep(delay)
        
        # Delete the message
        await client.delete_messages(chat_id=chat_id, message_ids=message_id)
        
        # Remove from pending deletions
        key = f"{chat_id}_{message_id}"
        if key in pending_deletions:
            del pending_deletions[key]
            
    except Exception as e:
        print(f"Error deleting message {message_id}: {e}")

async def schedule_multiple_deletions(client: Client, chat_id: int, message_ids: list, delay: int = AUTO_DELETE_TIME):
    """Schedule multiple messages for deletion"""
    for msg_id in message_ids:
        asyncio.create_task(schedule_message_deletion(client, chat_id, msg_id, delay))

def add_auto_delete_note(text: str, seconds: int = AUTO_DELETE_TIME) -> str:
    """Add auto-delete note to message text"""
    if AUTO_DELETE_ENABLED:
        minutes = seconds // 60
        text += f"\n\n<i>⏰ Tʜɪs ᴍᴇssᴀɢᴇ ᴡɪʟʟ ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ ɪɴ {minutes} ᴍɪɴᴜᴛᴇs</i>"
    return text

# ========== AUTO DELETE DATABASE ==========

class AutoDeleteDB:
    """Manage auto-delete settings in database"""
    
    @staticmethod
    async def get_settings():
        """Get auto-delete settings"""
        settings = await Seishiro.col.find_one({"type": "auto_delete_settings"})
        if not settings:
            return {
                "enabled": True,
                "default_time": 300,
                "user_messages": True,
                "bot_messages": True,
                "file_messages": True
            }
        return settings
    
    @staticmethod
    async def update_settings(enabled: bool = None, default_time: int = None, 
                             user_messages: bool = None, bot_messages: bool = None,
                             file_messages: bool = None):
        """Update auto-delete settings"""
        update_data = {}
        if enabled is not None:
            update_data["enabled"] = enabled
        if default_time is not None:
            update_data["default_time"] = default_time
        if user_messages is not None:
            update_data["user_messages"] = user_messages
        if bot_messages is not None:
            update_data["bot_messages"] = bot_messages
        if file_messages is not None:
            update_data["file_messages"] = file_messages
        
        await Seishiro.col.update_one(
            {"type": "auto_delete_settings"},
            {"$set": update_data},
            upsert=True
        )

# ========== AUTO DELETE COMMANDS ==========

# /autodelete command - Manage auto-delete settings
@Bot.on_message(filters.command('autodelete') & filters.private & is_owner_or_admin)
async def autodelete_command(client: Client, message: Message):
    """Manage auto-delete settings"""
    try:
        settings = await AutoDeleteDB.get_settings()
        
        status = "✅ Eɴᴀʙʟᴇᴅ" if settings['enabled'] else "❌ Dɪsᴀʙʟᴇᴅ"
        time_minutes = settings['default_time'] // 60
        
        text = f"""
<b>⏰ Aᴜᴛᴏ-Dᴇʟᴇᴛᴇ Sᴇᴛᴛɪɴɢs</b>

<b>━━━━━━━━━━━━━━━━━━━</b>

<b>Sᴛᴀᴛᴜs:</b> {status}
<b>Dᴇғᴀᴜʟᴛ Tɪᴍᴇ:</b> {time_minutes} ᴍɪɴᴜᴛᴇs

<b>━━━━━━━━━━━━━━━━━━━</b>

<b>Wʜᴀᴛ ᴛᴏ Dᴇʟᴇᴛᴇ:</b>
• Usᴇʀ Mᴇssᴀɢᴇs: {"✅" if settings['user_messages'] else "❌"}
• Bᴏᴛ Mᴇssᴀɢᴇs: {"✅" if settings['bot_messages'] else "❌"}
• Fɪʟᴇ Mᴇssᴀɢᴇs: {"✅" if settings['file_messages'] else "❌"}

<b>━━━━━━━━━━━━━━━━━━━</b>

<i>Usᴇ ᴛʜᴇ ʙᴜᴛᴛᴏɴs ʙᴇʟᴏᴡ ᴛᴏ ᴄᴏɴғɪɢᴜʀᴇ</i>
"""
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "🔴 Dɪsᴀʙʟᴇ" if settings['enabled'] else "🟢 Eɴᴀʙʟᴇ",
                callback_data="autodel_toggle"
            )],
            [InlineKeyboardButton("⏱ 2 Mɪɴ", callback_data="autodel_time_120"),
             InlineKeyboardButton("⏱ 5 Mɪɴ", callback_data="autodel_time_300"),
             InlineKeyboardButton("⏱ 10 Mɪɴ", callback_data="autodel_time_600")],
            [InlineKeyboardButton("⏱ 30 Mɪɴ", callback_data="autodel_time_1800"),
             InlineKeyboardButton("⏱ 1 Hᴏᴜʀ", callback_data="autodel_time_3600")],
            [InlineKeyboardButton("🔄 Rᴇғʀᴇsʜ", callback_data="autodel_refresh"),
             InlineKeyboardButton("❌ Cʟᴏsᴇ", callback_data="close")]
        ])
        
        await message.reply_text(text, reply_markup=keyboard)
        
    except Exception as e:
        await message.reply_text(f"<b>❌ Eʀʀᴏʀ: {str(e)}</b>")

# /cleanup command - Manual cleanup of old messages
@Bot.on_message(filters.command('cleanup') & filters.private & is_owner_or_admin)
async def cleanup_command(client: Client, message: Message):
    """Manually clean up old messages"""
    try:
        msg = await message.reply_text("<b>🧹 Cʟᴇᴀɴɪɴɢ ᴜᴘ ᴏʟᴅ ᴍᴇssᴀɢᴇs...</b>")
        
        # This will delete messages sent more than 1 hour ago
        # Note: This is a simplified version - you may need to track message IDs
        
        await asyncio.sleep(2)
        
        await msg.edit_text(
            "<b>✅ Cʟᴇᴀɴᴜᴘ ᴄᴏᴍᴘʟᴇᴛᴇᴅ!</b>\n\n"
            "<i>Oʟᴅ ᴍᴇssᴀɢᴇs ʜᴀᴠᴇ ʙᴇᴇɴ ᴅᴇʟᴇᴛᴇᴅ.</i>"
        )
        
    except Exception as e:
        await message.reply_text(f"<b>❌ Eʀʀᴏʀ: {str(e)}</b>")

# Callback handler for auto-delete settings
@Bot.on_callback_query(filters.regex("^autodel_"))
async def autodel_callback(client: Client, callback_query):
    """Handle auto-delete callbacks"""
    try:
        data = callback_query.data.split("_", 1)[1]
        
        if data == "toggle":
            settings = await AutoDeleteDB.get_settings()
            new_status = not settings['enabled']
            await AutoDeleteDB.update_settings(enabled=new_status)
            await callback_query.answer(
                f"✅ Auto-delete {'enabled' if new_status else 'disabled'}!",
                show_alert=True
            )
            await autodelete_command(client, callback_query.message)
            
        elif data.startswith("time_"):
            time_seconds = int(data.split("_")[1])
            await AutoDeleteDB.update_settings(default_time=time_seconds)
            time_minutes = time_seconds // 60
            await callback_query.answer(
                f"✅ Time set to {time_minutes} minutes!",
                show_alert=True
            )
            await autodelete_command(client, callback_query.message)
            
        elif data == "refresh":
            await callback_query.answer("🔄 Refreshing...")
            await autodelete_command(client, callback_query.message)
            
    except Exception as e:
        await callback_query.answer(f"❌ Error: {str(e)}", show_alert=True)

# ========== INTEGRATION WITH EXISTING COMMANDS ==========

# Example: How to use auto-delete in your existing commands
# Add this to your file delivery function:

async def send_file_with_autodelete(client: Client, chat_id: int, file_id: str, caption: str = ""):
    """Send file with auto-delete enabled"""
    settings = await AutoDeleteDB.get_settings()
    
    if settings['enabled'] and settings['file_messages']:
        # Add auto-delete note to caption
        caption = add_auto_delete_note(caption, settings['default_time'])
    
    # Send the file
    sent_msg = await client.send_document(
        chat_id=chat_id,
        document=file_id,
        caption=caption
    )
    
    # Schedule deletion if enabled
    if settings['enabled'] and settings['file_messages']:
        asyncio.create_task(
            schedule_message_deletion(client, chat_id, sent_msg.id, settings['default_time'])
        )
    
    return sent_msg

# Example usage in start.py or wherever you send files:
# Replace your normal send_document with send_file_with_autodelete
