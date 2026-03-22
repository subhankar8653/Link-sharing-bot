# ========================================
# ADDITIONAL DIRECT COMMANDS FOR LINK SHARE BOT
# Ye file plugins folder mein copy karo
# File name: additional_commands.py
# ========================================

import asyncio
import time
from datetime import date, datetime
from bot import Bot
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pyrogram.errors import PeerIdInvalid
from database.database import Seishiro
from config import *
from helper_func import *

async def is_owner_or_admin(filter, client, message):
    try:
        user_id = message.from_user.id
        return any([user_id == OWNER_ID, await Seishiro.is_admin(user_id)])
    except Exception as e:
        return False
        
is_owner_or_admin = filters.create(is_owner_or_admin)

# /help command
@Bot.on_message(filters.command('help') & filters.private)
async def help_command(client: Client, message: Message):
    """Help command handler"""
    try:
        await message.reply_photo(
            photo="https://ibb.co/cSfdrzRh",
            caption=HELP_TXT.format(
                first=message.from_user.first_name,
                last=message.from_user.last_name or "",
                username=f"@{message.from_user.username}" if message.from_user.username else "None",
                mention=message.from_user.mention,
                id=message.from_user.id),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('• ʙᴀᴄᴋ', callback_data='start'), 
                 InlineKeyboardButton('ᴄʟᴏsᴇ •', callback_data='close')]
            ])
        )
    except Exception as e:
        await message.reply_text(f"<b>Eʀʀᴏʀ: {e}</b>")

# /addchannel command
@Bot.on_message(filters.command('addchannel') & filters.private & is_owner_or_admin)
async def add_channel_cmd(client: Client, message: Message):
    """Add a new link share channel"""
    try:
        btn = [[InlineKeyboardButton("Cancel", callback_data="settings_main")]]
        sent = await message.reply_text(
            "<b>Sᴇɴᴅ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ ID (e.g., -100xxxxxxxxxx) ᴏʀ /cancel ᴛᴏ ᴄᴀɴᴄᴇʟ</b>",
            reply_markup=InlineKeyboardMarkup(btn)
        )
        
        msg = await client.listen(chat_id=message.chat.id, timeout=300)
        
        if msg.text == '/cancel':
            await sent.delete()
            await msg.reply("ᴄᴀɴᴄᴇʟʟᴇᴅ!")
            return
        
        if not msg.text.lstrip('-').isdigit():
            await sent.delete()
            await msg.reply("<b>Iɴᴠᴀʟɪᴅ ᴄʜᴀɴɴᴇʟ ID. Pʟᴇᴀsᴇ sᴇɴᴅ ᴀ ᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ.</b>")
            return
        
        channel_id = int(msg.text)
        
        try:
            chat = await client.get_chat(channel_id)
            await Seishiro.add_channel(channel_id)
            await sent.delete()
            await msg.reply(f"<b>✅ Cʜᴀɴɴᴇʟ {chat.title} (`{channel_id}`) ᴀᴅᴅᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>")
        except PeerIdInvalid:
            await sent.delete()
            await msg.reply("<b>❌ Iɴᴠᴀʟɪᴅ ᴄʜᴀɴɴᴇʟ ID. Mᴀᴋᴇ sᴜʀᴇ ᴛʜᴇ ʙᴏᴛ ɪs ᴀɴ ᴀᴅᴍɪɴ ɪɴ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ.</b>")
        except Exception as e:
            await sent.delete()
            await msg.reply(f"<b>❌ Eʀʀᴏʀ: {str(e)}</b>")
            
    except asyncio.TimeoutError:
        await message.reply("<b>⏱ Tɪᴍᴇᴏᴜᴛ! Pʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ.</b>")
    except Exception as e:
        await message.reply(f"<b>❌ Eʀʀᴏʀ: {str(e)}</b>")

# /delchannel command
@Bot.on_message(filters.command('delchannel') & filters.private & is_owner_or_admin)
async def del_channel_cmd(client: Client, message: Message):
    """Delete a link share channel"""
    try:
        btn = [[InlineKeyboardButton("Cancel", callback_data="settings_main")]]
        sent = await message.reply_text(
            "<b>Sᴇɴᴅ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ ID ᴛᴏ ᴅᴇʟᴇᴛᴇ (e.g., -100xxxxxxxxxx) ᴏʀ /cancel</b>",
            reply_markup=InlineKeyboardMarkup(btn)
        )
        
        msg = await client.listen(chat_id=message.chat.id, timeout=300)
        
        if msg.text == '/cancel':
            await sent.delete()
            await msg.reply("ᴄᴀɴᴄᴇʟʟᴇᴅ!")
            return
        
        if not msg.text.lstrip('-').isdigit():
            await sent.delete()
            await msg.reply("<b>❌ Iɴᴠᴀʟɪᴅ ᴄʜᴀɴɴᴇʟ ID.</b>")
            return
        
        channel_id = int(msg.text)
        result = await Seishiro.delete_channel(channel_id)
        
        await sent.delete()
        if result.deleted_count > 0:
            await msg.reply(f"<b>✅ Cʜᴀɴɴᴇʟ `{channel_id}` ᴅᴇʟᴇᴛᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>")
        else:
            await msg.reply(f"<b>❌ Cʜᴀɴɴᴇʟ `{channel_id}` ɴᴏᴛ ғᴏᴜɴᴅ ɪɴ ᴅᴀᴛᴀʙᴀsᴇ.</b>")
            
    except asyncio.TimeoutError:
        await message.reply("<b>⏱ Tɪᴍᴇᴏᴜᴛ! Pʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ.</b>")
    except Exception as e:
        await message.reply(f"<b>❌ Eʀʀᴏʀ: {str(e)}</b>")

# /listchannels command
@Bot.on_message(filters.command('listchannels') & filters.private & is_owner_or_admin)
async def list_channels_cmd(client: Client, message: Message):
    """List all link share channels"""
    try:
        channels = await Seishiro.get_channels()
        
        if not channels:
            await message.reply_text("<b>❌ Nᴏ ᴄʜᴀɴɴᴇʟs ғᴏᴜɴᴅ!</b>")
            return
        
        lines = []
        for i, cid in enumerate(channels, 1):
            try:
                chat = await client.get_chat(cid)
                lines.append(f"{i}. <b>{chat.title}</b> (<code>{cid}</code>)")
            except:
                lines.append(f"{i}. <code>{cid}</code> <i>(ɴᴏᴛ ᴀᴄᴄᴇssɪʙʟᴇ)</i>")
        
        text = "<b>📋 Lɪɴᴋ Sʜᴀʀᴇ Cʜᴀɴɴᴇʟs:</b>\n\n" + "\n".join(lines[:50])
        await message.reply_text(text)
        
    except Exception as e:
        await message.reply(f"<b>❌ Eʀʀᴏʀ: {str(e)}</b>")

# /ban command
@Bot.on_message(filters.command('ban') & filters.private & is_owner_or_admin)
async def ban_user_cmd(client: Client, message: Message):
    """Ban a user from bot"""
    try:
        btn = [[InlineKeyboardButton("Cancel", callback_data="ban_menu")]]
        sent = await message.reply_text(
            "<b>Sᴇɴᴅ ᴛʜᴇ ᴜsᴇʀ ID ᴡʜɪᴄʜ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ʙᴀɴ (e.g., 123456789):\n\n"
            "Yᴏᴜ ᴄᴀɴ ᴀʟsᴏ ᴘʀᴏᴠɪᴅᴇ ᴀ ʀᴇᴀsᴏɴ:\n"
            "<code>user_id reason</code>\n\n"
            "/cancel ᴛᴏ ᴄᴀɴᴄᴇʟ</b>",
            reply_markup=InlineKeyboardMarkup(btn)
        )
        
        msg = await client.listen(chat_id=message.chat.id, timeout=300)
        
        if msg.text == '/cancel':
            await sent.delete()
            await msg.reply("ᴄᴀɴᴄᴇʟʟᴇᴅ!")
            return
        
        parts = msg.text.split(maxsplit=1)
        user_id_str = parts[0]
        reason = parts[1] if len(parts) > 1 else "No reason provided"
        
        if not user_id_str.lstrip('-').isdigit():
            await sent.delete()
            await msg.reply("<b>❌ Iɴᴠᴀʟɪᴅ ᴜsᴇʀ ID. Pʟᴇᴀsᴇ sᴇɴᴅ ᴀ ᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ.</b>")
            return
        
        ban_user_id = int(user_id_str)
        
        await Seishiro.ban_data.update_one(
            {"_id": ban_user_id},
            {"$set": {
                "ban_status.is_banned": True,
                "ban_status.ban_reason": reason,
                "ban_status.banned_on": date.today().isoformat()
            }},
            upsert=True
        )
        
        await sent.delete()
        await msg.reply(f"<b>✅ Usᴇʀ - <code>{ban_user_id}</code> Is sᴜᴄᴄᴇssғᴜʟʟʏ ʙᴀɴɴᴇᴅ.\nRᴇᴀsᴏɴ:- {reason}</b>")
        
    except asyncio.TimeoutError:
        await message.reply("<b>⏱ Tɪᴍᴇᴏᴜᴛ! Pʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ.</b>")
    except Exception as e:
        await message.reply(f"<b>❌ Eʀʀᴏʀ: {str(e)}</b>")

# /unban command
@Bot.on_message(filters.command('unban') & filters.private & is_owner_or_admin)
async def unban_user_cmd(client: Client, message: Message):
    """Unban a user"""
    try:
        btn = [[InlineKeyboardButton("Cancel", callback_data="ban_menu")]]
        sent = await message.reply_text(
            "<b>Sᴇɴᴅ ᴛʜᴇ ᴜsᴇʀ ID ᴛᴏ ᴜɴʙᴀɴ (e.g., 123456789):\n\n/cancel ᴛᴏ ᴄᴀɴᴄᴇʟ</b>",
            reply_markup=InlineKeyboardMarkup(btn)
        )
        
        msg = await client.listen(chat_id=message.chat.id, timeout=300)
        
        if msg.text == '/cancel':
            await sent.delete()
            await msg.reply("ᴄᴀɴᴄᴇʟʟᴇᴅ!")
            return
        
        if not msg.text.lstrip('-').isdigit():
            await sent.delete()
            await msg.reply("<b>❌ Iɴᴠᴀʟɪᴅ ᴜsᴇʀ ID. Pʟᴇᴀsᴇ sᴇɴᴅ ᴀ ᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ.</b>")
            return
        
        unban_user_id = int(msg.text)
        
        result = await Seishiro.ban_data.update_one(
            {"_id": unban_user_id},
            {"$set": {
                "ban_status.is_banned": False,
                "ban_status.ban_reason": "",
                "ban_status.banned_on": None
            }}
        )
        
        await sent.delete()
        if result.matched_count == 0:
            await msg.reply(f"<b>❌ Usᴇʀ - <code>{unban_user_id}</code> ɴᴏᴛ ғᴏᴜɴᴅ ɪɴ ᴅᴀᴛᴀʙᴀsᴇ.</b>")
        else:
            await msg.reply(f"<b>✅ Usᴇʀ - <code>{unban_user_id}</code> Is sᴜᴄᴄᴇssғᴜʟʟʏ ᴜɴʙᴀɴɴᴇᴅ.</b>")
            
    except asyncio.TimeoutError:
        await message.reply("<b>⏱ Tɪᴍᴇᴏᴜᴛ! Pʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ.</b>")
    except Exception as e:
        await message.reply(f"<b>❌ Eʀʀᴏʀ: {str(e)}</b>")

# /stats or /status command
@Bot.on_message(filters.command(['stats', 'status']) & filters.private & is_owner_or_admin)
async def stats_cmd(client: Client, message: Message):
    """Show bot statistics"""
    try:
        total_users = await Seishiro.total_users_count()
        current_time = datetime.now()
        uptime_delta = current_time - client.uptime
        uptime_seconds = uptime_delta.total_seconds()
        uptime = time.strftime("%Hh %Mm %Ss", time.gmtime(uptime_seconds))
        
        text = f"""
<b>📊 Bᴏᴛ Sᴛᴀᴛɪsᴛɪᴄs</b>

• <b>Bᴏᴛ Uᴘᴛɪᴍᴇ:</b> {uptime}
• <b>Tᴏᴛᴀʟ Usᴇʀs:</b> {total_users}
• <b>Vᴇʀsɪᴏɴ:</b> 2.05v
"""
        await message.reply_text(text)
        
    except Exception as e:
        await message.reply(f"<b>❌ Eʀʀᴏʀ: {str(e)}</b>")

# /addfsub command
@Bot.on_message(filters.command('addfsub') & filters.private & is_owner_or_admin)
async def add_fsub_cmd(client: Client, message: Message):
    """Add a force subscribe channel"""
    try:
        btn = [[InlineKeyboardButton("Cancel", callback_data="fsub_settings_menu")]]
        sent = await message.reply_text(
            "<b>Sᴇɴᴅ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ ID ᴛᴏ ᴀᴅᴅ ᴀs Fsᴜʙ (e.g., -100xxxxxxxxxx) ᴏʀ /cancel</b>",
            reply_markup=InlineKeyboardMarkup(btn)
        )
        
        msg = await client.listen(chat_id=message.chat.id, timeout=300)
        
        if msg.text == '/cancel':
            await sent.delete()
            await msg.reply("ᴄᴀɴᴄᴇʟʟᴇᴅ!")
            return
        
        if not msg.text.lstrip('-').isdigit():
            await sent.delete()
            await msg.reply("<b>❌ Iɴᴠᴀʟɪᴅ ᴄʜᴀɴɴᴇʟ ID.</b>")
            return
        
        channel_id = int(msg.text)
        
        try:
            chat = await client.get_chat(channel_id)
            await Seishiro.add_fsub_channel(channel_id)
            await sent.delete()
            await msg.reply(f"<b>✅ Fsᴜʙ Cʜᴀɴɴᴇʟ {chat.title} (<code>{channel_id}</code>) ᴀᴅᴅᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>")
        except PeerIdInvalid:
            await sent.delete()
            await msg.reply("<b>❌ Iɴᴠᴀʟɪᴅ ᴄʜᴀɴɴᴇʟ ID. Mᴀᴋᴇ sᴜʀᴇ ᴛʜᴇ ʙᴏᴛ ɪs ᴀɴ ᴀᴅᴍɪɴ ɪɴ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ.</b>")
        except Exception as e:
            await sent.delete()
            await msg.reply(f"<b>❌ Eʀʀᴏʀ: {str(e)}</b>")
            
    except asyncio.TimeoutError:
        await message.reply("<b>⏱ Tɪᴍᴇᴏᴜᴛ! Pʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ.</b>")
    except Exception as e:
        await message.reply(f"<b>❌ Eʀʀᴏʀ: {str(e)}</b>")

# /removefsub command
@Bot.on_message(filters.command('removefsub') & filters.private & is_owner_or_admin)
async def remove_fsub_cmd(client: Client, message: Message):
    """Remove a force subscribe channel"""
    try:
        btn = [[InlineKeyboardButton("Cancel", callback_data="fsub_settings_menu")]]
        sent = await message.reply_text(
            "<b>Sᴇɴᴅ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ ID ᴛᴏ ʀᴇᴍᴏᴠᴇ ғʀᴏᴍ Fsᴜʙ (e.g., -100xxxxxxxxxx) ᴏʀ /cancel</b>",
            reply_markup=InlineKeyboardMarkup(btn)
        )
        
        msg = await client.listen(chat_id=message.chat.id, timeout=300)
        
        if msg.text == '/cancel':
            await sent.delete()
            await msg.reply("ᴄᴀɴᴄᴇʟʟᴇᴅ!")
            return
        
        if not msg.text.lstrip('-').isdigit():
            await sent.delete()
            await msg.reply("<b>❌ Iɴᴠᴀʟɪᴅ ᴄʜᴀɴɴᴇʟ ID.</b>")
            return
        
        channel_id = int(msg.text)
        result = await Seishiro.delete_fsub_channel(channel_id)
        
        await sent.delete()
        if result.deleted_count > 0:
            await msg.reply(f"<b>✅ Fsᴜʙ Cʜᴀɴɴᴇʟ <code>{channel_id}</code> ʀᴇᴍᴏᴠᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>")
        else:
            await msg.reply(f"<b>❌ Cʜᴀɴɴᴇʟ <code>{channel_id}</code> ɴᴏᴛ ғᴏᴜɴᴅ ɪɴ Fsᴜʙ ʟɪsᴛ.</b>")
            
    except asyncio.TimeoutError:
        await message.reply("<b>⏱ Tɪᴍᴇᴏᴜᴛ! Pʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ.</b>")
    except Exception as e:
        await message.reply(f"<b>❌ Eʀʀᴏʀ: {str(e)}</b>")

# /listfsub command
@Bot.on_message(filters.command('listfsub') & filters.private & is_owner_or_admin)
async def list_fsub_cmd(client: Client, message: Message):
    """List all force subscribe channels"""
    try:
        channels = await Seishiro.get_fsub_channels()
        
        if not channels:
            await message.reply_text("<b>❌ Nᴏ Fsᴜʙ ᴄʜᴀɴɴᴇʟs ғᴏᴜɴᴅ!</b>")
            return
        
        lines = []
        for i, cid in enumerate(channels, 1):
            try:
                chat = await client.get_chat(cid)
                mode = await Seishiro.get_channel_mode(cid) or "off"
                lines.append(f"{i}. <b>{chat.title}</b> (<code>{cid}</code>)\n   📍 Request Mode: <b>{mode.upper()}</b>")
            except:
                lines.append(f"{i}. <code>{cid}</code> <i>(ɴᴏᴛ ᴀᴄᴄᴇssɪʙʟᴇ)</i>")
        
        text = "<b>📋 Fsᴜʙ Cʜᴀɴɴᴇʟs:</b>\n\n" + "\n\n".join(lines[:50])
        await message.reply_text(text)
        
    except Exception as e:
        await message.reply(f"<b>❌ Eʀʀᴏʀ: {str(e)}</b>")

# /togglereq command (for specific channel)
@Bot.on_message(filters.command('togglereq') & filters.private & is_owner_or_admin)
async def toggle_req_cmd(client: Client, message: Message):
    """Toggle request mode for a specific channel"""
    try:
        btn = [[InlineKeyboardButton("Cancel", callback_data="fsub_settings_menu")]]
        sent = await message.reply_text(
            "<b>Sᴇɴᴅ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ ID ᴛᴏ ᴛᴏɢɢʟᴇ ʀᴇǫᴜᴇsᴛ ᴍᴏᴅᴇ (e.g., -100xxxxxxxxxx) ᴏʀ /cancel</b>",
            reply_markup=InlineKeyboardMarkup(btn)
        )
        
        msg = await client.listen(chat_id=message.chat.id, timeout=300)
        
        if msg.text == '/cancel':
            await sent.delete()
            await msg.reply("ᴄᴀɴᴄᴇʟʟᴇᴅ!")
            return
        
        if not msg.text.lstrip('-').isdigit():
            await sent.delete()
            await msg.reply("<b>❌ Iɴᴠᴀʟɪᴅ ᴄʜᴀɴɴᴇʟ ID.</b>")
            return
        
        channel_id = int(msg.text)
        current_mode = await Seishiro.get_channel_mode(channel_id) or "off"
        new_mode = "on" if current_mode == "off" else "off"
        
        await Seishiro.set_channel_mode(channel_id, new_mode)
        
        try:
            chat = await client.get_chat(channel_id)
            channel_name = chat.title
        except:
            channel_name = str(channel_id)
        
        status_emoji = "✅" if new_mode == "on" else "❌"
        await sent.delete()
        await msg.reply(
            f"<b>{status_emoji} Rᴇǫᴜᴇsᴛ ᴍᴏᴅᴇ ғᴏʀ:</b>\n"
            f"<b>{channel_name}</b> (<code>{channel_id}</code>)\n"
            f"<b>Sᴛᴀᴛᴜs:</b> <b>{new_mode.upper()}</b>"
        )
        
    except asyncio.TimeoutError:
        await message.reply("<b>⏱ Tɪᴍᴇᴏᴜᴛ! Pʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ.</b>")
    except Exception as e:
        await message.reply(f"<b>❌ Eʀʀᴏʀ: {str(e)}</b>")
