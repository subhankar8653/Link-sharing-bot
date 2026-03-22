# ============================================
# FEATURE 5: NOTIFICATION SYSTEM
# File: plugins/notifications.py
# ============================================

import asyncio
from datetime import datetime, timedelta
from bot import Bot
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from database.database import Seishiro
from config import *

async def is_owner_or_admin(filter, client, message):
    try:
        user_id = message.from_user.id
        return any([user_id == OWNER_ID, await Seishiro.is_admin(user_id)])
    except:
        return False
        
is_owner_or_admin = filters.create(is_owner_or_admin)

# ========== NOTIFICATION DATABASE ==========

class NotificationDB:
    """Manage notification settings"""
    
    @staticmethod
    async def get_settings():
        """Get notification settings"""
        settings = await Seishiro.col.find_one({"type": "notification_settings"})
        if not settings:
            return {
                "enabled": True,
                "new_users": True,
                "user_left_channel": True,
                "link_accessed": False,
                "daily_stats": True,
                "weekly_stats": True,
                "admin_channel": DATABASE_CHANNEL
            }
        return settings
    
    @staticmethod
    async def update_settings(**kwargs):
        """Update notification settings"""
        await Seishiro.col.update_one(
            {"type": "notification_settings"},
            {"$set": kwargs},
            upsert=True
        )

# ========== NOTIFICATION FUNCTIONS ==========

async def send_notification(client: Client, text: str, disable_notification: bool = False):
    """Send notification to admin channel"""
    try:
        settings = await NotificationDB.get_settings()
        if not settings['enabled']:
            return
        
        admin_channel = settings['admin_channel']
        await client.send_message(
            chat_id=admin_channel,
            text=text,
            disable_notification=disable_notification
        )
    except Exception as e:
        print(f"Error sending notification: {e}")

async def notify_new_user(client: Client, user):
    """Notify when a new user joins"""
    try:
        settings = await NotificationDB.get_settings()
        if not settings.get('new_users', True):
            return
        
        text = f"""
<b>🆕 Nᴇᴡ Usᴇʀ Jᴏɪɴᴇᴅ!</b>

<b>Nᴀᴍᴇ:</b> {user.mention}
<b>Usᴇʀɴᴀᴍᴇ:</b> @{user.username or 'None'}
<b>Usᴇʀ ID:</b> <code>{user.id}</code>
<b>Tɪᴍᴇ:</b> {datetime.now().strftime('%d-%b-%Y %H:%M')}
"""
        await send_notification(client, text, disable_notification=True)
    except Exception as e:
        print(f"Error in notify_new_user: {e}")

async def notify_user_left_channel(client: Client, user_id: int, channel_id: int):
    """Notify when user leaves a channel"""
    try:
        settings = await NotificationDB.get_settings()
        if not settings.get('user_left_channel', True):
            return
        
        try:
            user = await client.get_users(user_id)
            user_name = user.mention
        except:
            user_name = f"<code>{user_id}</code>"
        
        try:
            chat = await client.get_chat(channel_id)
            channel_name = chat.title
        except:
            channel_name = f"<code>{channel_id}</code>"
        
        text = f"""
<b>⚠️ Usᴇʀ Lᴇғᴛ Cʜᴀɴɴᴇʟ!</b>

<b>Usᴇʀ:</b> {user_name}
<b>Cʜᴀɴɴᴇʟ:</b> {channel_name}
<b>Tɪᴍᴇ:</b> {datetime.now().strftime('%d-%b-%Y %H:%M')}
"""
        await send_notification(client, text)
    except Exception as e:
        print(f"Error in notify_user_left_channel: {e}")

async def notify_link_accessed(client: Client, user_id: int, link_id: str, access_count: int):
    """Notify when link is accessed (only for milestones)"""
    try:
        settings = await NotificationDB.get_settings()
        if not settings.get('link_accessed', False):
            return
        
        # Only notify at milestones (10, 50, 100, 500, 1000)
        milestones = [10, 50, 100, 500, 1000]
        if access_count not in milestones:
            return
        
        try:
            user = await client.get_users(user_id)
            user_name = user.mention
        except:
            user_name = f"<code>{user_id}</code>"
        
        text = f"""
<b>🎉 Lɪɴᴋ Mɪʟᴇsᴛᴏɴᴇ!</b>

<b>Lɪɴᴋ ID:</b> <code>{link_id}</code>
<b>Aᴄᴄᴇssᴇᴅ:</b> {access_count} ᴛɪᴍᴇs
<b>Lᴀsᴛ Usᴇʀ:</b> {user_name}
"""
        await send_notification(client, text)
    except Exception as e:
        print(f"Error in notify_link_accessed: {e}")

async def send_daily_stats(client: Client):
    """Send daily statistics report"""
    try:
        settings = await NotificationDB.get_settings()
        if not settings.get('daily_stats', True):
            return
        
        # Import Analytics class
        from plugins.analytics import Analytics
        
        link_stats = await Analytics.get_link_stats(days=1)
        user_stats = await Analytics.get_user_stats(days=1)
        
        text = f"""
<b>📊 Dᴀɪʟʏ Rᴇᴘᴏʀᴛ</b>
<b>Dᴀᴛᴇ:</b> {datetime.now().strftime('%d-%b-%Y')}

<b>━━━━━━━━━━━━━━━━━━━</b>

<b>👥 Usᴇʀs:</b>
• Nᴇᴡ: <code>{user_stats['new_users']}</code>
• Aᴄᴛɪᴠᴇ: <code>{user_stats['daily_active']}</code>
• Tᴏᴛᴀʟ: <code>{user_stats['total_users']}</code>

<b>🔗 Lɪɴᴋs:</b>
• Gᴇɴᴇʀᴀᴛᴇᴅ: <code>{link_stats['total_links']}</code>
• Aᴄᴄᴇssᴇs: <code>{link_stats['total_accesses']}</code>

<b>━━━━━━━━━━━━━━━━━━━</b>

<i>Aᴜᴛᴏᴍᴀᴛɪᴄ Dᴀɪʟʏ Rᴇᴘᴏʀᴛ</i>
"""
        await send_notification(client, text)
    except Exception as e:
        print(f"Error in send_daily_stats: {e}")

async def send_weekly_stats(client: Client):
    """Send weekly statistics report"""
    try:
        settings = await NotificationDB.get_settings()
        if not settings.get('weekly_stats', True):
            return
        
        from plugins.analytics import Analytics
        
        link_stats = await Analytics.get_link_stats(days=7)
        user_stats = await Analytics.get_user_stats(days=7)
        top_links = await Analytics.get_top_links(limit=5)
        
        text = f"""
<b>📈 Wᴇᴇᴋʟʏ Rᴇᴘᴏʀᴛ</b>
<b>Wᴇᴇᴋ Eɴᴅɪɴɢ:</b> {datetime.now().strftime('%d-%b-%Y')}

<b>━━━━━━━━━━━━━━━━━━━</b>

<b>👥 Usᴇʀ Sᴛᴀᴛs:</b>
• Nᴇᴡ Usᴇʀs: <code>{user_stats['new_users']}</code> 🆕
• Aᴄᴛɪᴠᴇ Usᴇʀs: <code>{user_stats['active_users']}</code> ✅
• Tᴏᴛᴀʟ Usᴇʀs: <code>{user_stats['total_users']}</code>

<b>🔗 Lɪɴᴋ Sᴛᴀᴛs:</b>
• Gᴇɴᴇʀᴀᴛᴇᴅ: <code>{link_stats['total_links']}</code>
• Aᴄᴄᴇssᴇs: <code>{link_stats['total_accesses']}</code> 👁
• Uɴɪǫᴜᴇ Usᴇʀs: <code>{link_stats['unique_users_count']}</code>

<b>━━━━━━━━━━━━━━━━━━━</b>

<b>🔝 Tᴏᴘ 5 Lɪɴᴋs:</b>
"""
        for i, link in enumerate(top_links[:5], 1):
            text += f"\n{i}. <code>{link['link_id']}</code> - {link['access_count']} ᴀᴄᴄᴇssᴇs"
        
        text += "\n\n<b>━━━━━━━━━━━━━━━━━━━</b>\n\n<i>Aᴜᴛᴏᴍᴀᴛɪᴄ Wᴇᴇᴋʟʏ Rᴇᴘᴏʀᴛ</i>"
        
        await send_notification(client, text)
    except Exception as e:
        print(f"Error in send_weekly_stats: {e}")

# ========== NOTIFICATION COMMANDS ==========

# /notifications command - Manage notification settings
@Bot.on_message(filters.command('notifications') & filters.private & is_owner_or_admin)
async def notifications_command(client: Client, message: Message):
    """Manage notification settings"""
    try:
        settings = await NotificationDB.get_settings()
        
        status = "✅ Eɴᴀʙʟᴇᴅ" if settings['enabled'] else "❌ Dɪsᴀʙʟᴇᴅ"
        
        text = f"""
<b>🔔 Nᴏᴛɪғɪᴄᴀᴛɪᴏɴ Sᴇᴛᴛɪɴɢs</b>

<b>━━━━━━━━━━━━━━━━━━━</b>

<b>Sᴛᴀᴛᴜs:</b> {status}

<b>━━━━━━━━━━━━━━━━━━━</b>

<b>Nᴏᴛɪғɪᴄᴀᴛɪᴏɴ Tʏᴘᴇs:</b>

• Nᴇᴡ Usᴇʀs: {"✅" if settings['new_users'] else "❌"}
• Usᴇʀ Lᴇғᴛ: {"✅" if settings['user_left_channel'] else "❌"}
• Lɪɴᴋ Aᴄᴄᴇss: {"✅" if settings['link_accessed'] else "❌"}
• Dᴀɪʟʏ Rᴇᴘᴏʀᴛ: {"✅" if settings['daily_stats'] else "❌"}
• Wᴇᴇᴋʟʏ Rᴇᴘᴏʀᴛ: {"✅" if settings['weekly_stats'] else "❌"}

<b>━━━━━━━━━━━━━━━━━━━</b>

<i>Usᴇ ʙᴜᴛᴛᴏɴs ᴛᴏ ᴛᴏɢɢʟᴇ</i>
"""
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "🔴 Dɪsᴀʙʟᴇ Aʟʟ" if settings['enabled'] else "🟢 Eɴᴀʙʟᴇ Aʟʟ",
                callback_data="notif_toggle_all"
            )],
            [InlineKeyboardButton(
                f"{'🔴' if settings['new_users'] else '🟢'} Nᴇᴡ Usᴇʀs",
                callback_data="notif_toggle_new_users"
            )],
            [InlineKeyboardButton(
                f"{'🔴' if settings['user_left_channel'] else '🟢'} Usᴇʀ Lᴇғᴛ",
                callback_data="notif_toggle_user_left"
            )],
            [InlineKeyboardButton(
                f"{'🔴' if settings['link_accessed'] else '🟢'} Lɪɴᴋ Aᴄᴄᴇss",
                callback_data="notif_toggle_link_access"
            )],
            [InlineKeyboardButton(
                f"{'🔴' if settings['daily_stats'] else '🟢'} Dᴀɪʟʏ Rᴇᴘᴏʀᴛ",
                callback_data="notif_toggle_daily"
            )],
            [InlineKeyboardButton(
                f"{'🔴' if settings['weekly_stats'] else '🟢'} Wᴇᴇᴋʟʏ Rᴇᴘᴏʀᴛ",
                callback_data="notif_toggle_weekly"
            )],
            [InlineKeyboardButton("🔄 Rᴇғʀᴇsʜ", callback_data="notif_refresh"),
             InlineKeyboardButton("❌ Cʟᴏsᴇ", callback_data="close")]
        ])
        
        await message.reply_text(text, reply_markup=keyboard)
        
    except Exception as e:
        await message.reply_text(f"<b>❌ Eʀʀᴏʀ: {str(e)}</b>")

# /testnotif command - Send test notification
@Bot.on_message(filters.command('testnotif') & filters.private & is_owner_or_admin)
async def test_notif_command(client: Client, message: Message):
    """Send a test notification"""
    try:
        await send_notification(
            client,
            f"""
<b>🧪 Tᴇsᴛ Nᴏᴛɪғɪᴄᴀᴛɪᴏɴ</b>

Tʜɪs ɪs ᴀ ᴛᴇsᴛ ɴᴏᴛɪғɪᴄᴀᴛɪᴏɴ sᴇɴᴛ ʙʏ {message.from_user.mention}

<b>Tɪᴍᴇ:</b> {datetime.now().strftime('%d-%b-%Y %H:%M:%S')}
"""
        )
        await message.reply_text("<b>✅ Tᴇsᴛ ɴᴏᴛɪғɪᴄᴀᴛɪᴏɴ sᴇɴᴛ!</b>")
    except Exception as e:
        await message.reply_text(f"<b>❌ Eʀʀᴏʀ: {str(e)}</b>")

# Callback handler for notification settings
@Bot.on_callback_query(filters.regex("^notif_"))
async def notif_callback(client: Client, callback_query):
    """Handle notification callbacks"""
    try:
        data = callback_query.data.split("_", 1)[1]
        settings = await NotificationDB.get_settings()
        
        if data == "toggle_all":
            new_status = not settings['enabled']
            await NotificationDB.update_settings(enabled=new_status)
            await callback_query.answer(
                f"✅ Notifications {'enabled' if new_status else 'disabled'}!",
                show_alert=True
            )
            
        elif data.startswith("toggle_"):
            setting_key = data.replace("toggle_", "")
            if setting_key == "user_left":
                setting_key = "user_left_channel"
            elif setting_key == "link_access":
                setting_key = "link_accessed"
            elif setting_key == "daily":
                setting_key = "daily_stats"
            elif setting_key == "weekly":
                setting_key = "weekly_stats"
            
            new_value = not settings.get(setting_key, True)
            await NotificationDB.update_settings(**{setting_key: new_value})
            await callback_query.answer(
                f"✅ {'Enabled' if new_value else 'Disabled'}!",
                show_alert=True
            )
            
        elif data == "refresh":
            await callback_query.answer("🔄 Refreshing...")
        
        # Refresh the message
        await notifications_command(client, callback_query.message)
        
    except Exception as e:
        await callback_query.answer(f"❌ Error: {str(e)}", show_alert=True)

# ========== AUTOMATIC SCHEDULED REPORTS ==========

async def schedule_daily_reports(client: Client):
    """Schedule daily reports"""
    while True:
        try:
            # Calculate time until next report (9 AM)
            now = datetime.now()
            next_report = now.replace(hour=9, minute=0, second=0, microsecond=0)
            if now >= next_report:
                next_report += timedelta(days=1)
            
            # Wait until next report time
            wait_seconds = (next_report - now).total_seconds()
            await asyncio.sleep(wait_seconds)
            
            # Send daily report
            await send_daily_stats(client)
            
        except Exception as e:
            print(f"Error in schedule_daily_reports: {e}")
            await asyncio.sleep(3600)  # Wait 1 hour before retry

async def schedule_weekly_reports(client: Client):
    """Schedule weekly reports"""
    while True:
        try:
            # Calculate time until next report (Monday 9 AM)
            now = datetime.now()
            days_until_monday = (7 - now.weekday()) % 7
            if days_until_monday == 0 and now.hour >= 9:
                days_until_monday = 7
            
            next_report = now + timedelta(days=days_until_monday)
            next_report = next_report.replace(hour=9, minute=0, second=0, microsecond=0)
            
            # Wait until next report time
            wait_seconds = (next_report - now).total_seconds()
            await asyncio.sleep(wait_seconds)
            
            # Send weekly report
            await send_weekly_stats(client)
            
        except Exception as e:
            print(f"Error in schedule_weekly_reports: {e}")
            await asyncio.sleep(3600)

# Start scheduled tasks (add this to bot.py startup)
async def start_notification_tasks(client: Client):
    """Start all notification background tasks"""
    asyncio.create_task(schedule_daily_reports(client))
    asyncio.create_task(schedule_weekly_reports(client))
    print("✅ Notification tasks started!")
