# ============================================
# FEATURE 1 & 2: LINK ANALYTICS + USER ANALYTICS
# File: plugins/analytics.py
# ============================================

import asyncio
import time
from datetime import datetime, timedelta
from bot import Bot
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from database.database import Seishiro
from config import *
import matplotlib.pyplot as plt
import io
from collections import defaultdict

async def is_owner_or_admin(filter, client, message):
    try:
        user_id = message.from_user.id
        return any([user_id == OWNER_ID, await Seishiro.is_admin(user_id)])
    except Exception as e:
        return False
        
is_owner_or_admin = filters.create(is_owner_or_admin)

# ========== ANALYTICS DATABASE FUNCTIONS ==========

class Analytics:
    """Analytics database handler"""
    
    @staticmethod
    async def log_link_access(user_id: int, link_id: str, channel_id: int):
        """Log when a user accesses a link"""
        await Seishiro.col.insert_one({
            "type": "link_access",
            "user_id": user_id,
            "link_id": link_id,
            "channel_id": channel_id,
            "accessed_at": datetime.now(),
            "date": datetime.now().strftime("%Y-%m-%d")
        })
    
    @staticmethod
    async def log_link_generation(admin_id: int, link_id: str, channel_id: int, link_type: str):
        """Log when a link is generated"""
        await Seishiro.col.insert_one({
            "type": "link_generation",
            "admin_id": admin_id,
            "link_id": link_id,
            "channel_id": channel_id,
            "link_type": link_type,  # "single" or "batch"
            "created_at": datetime.now(),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "access_count": 0,
            "unique_users": []
        })
    
    @staticmethod
    async def increment_link_access(link_id: str, user_id: int):
        """Increment access count for a link"""
        await Seishiro.col.update_one(
            {"type": "link_generation", "link_id": link_id},
            {
                "$inc": {"access_count": 1},
                "$addToSet": {"unique_users": user_id},
                "$set": {"last_accessed": datetime.now()}
            }
        )
    
    @staticmethod
    async def log_user_activity(user_id: int, activity_type: str):
        """Log user activity"""
        await Seishiro.col.insert_one({
            "type": "user_activity",
            "user_id": user_id,
            "activity_type": activity_type,  # "start", "link_access", "channel_join"
            "timestamp": datetime.now(),
            "date": datetime.now().strftime("%Y-%m-%d")
        })
    
    @staticmethod
    async def update_user_last_active(user_id: int):
        """Update user's last active time"""
        await Seishiro.users.update_one(
            {"_id": user_id},
            {"$set": {"last_active": datetime.now()}},
            upsert=True
        )
    
    @staticmethod
    async def get_link_stats(link_id: str = None, days: int = 7):
        """Get link statistics"""
        match_query = {"type": "link_generation"}
        if link_id:
            match_query["link_id"] = link_id
        
        # Get date range
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        pipeline = [
            {"$match": match_query},
            {"$match": {"date": {"$gte": start_date}}},
            {"$group": {
                "_id": None,
                "total_links": {"$sum": 1},
                "total_accesses": {"$sum": "$access_count"},
                "unique_users_count": {"$sum": {"$size": "$unique_users"}}
            }}
        ]
        
        result = await Seishiro.col.aggregate(pipeline).to_list(length=1)
        return result[0] if result else {
            "total_links": 0,
            "total_accesses": 0,
            "unique_users_count": 0
        }
    
    @staticmethod
    async def get_user_stats(days: int = 7):
        """Get user statistics"""
        start_date = datetime.now() - timedelta(days=days)
        
        # Total users
        total_users = await Seishiro.total_users_count()
        
        # New users in last X days
        new_users = await Seishiro.users.count_documents({
            "join_date": {"$gte": start_date}
        })
        
        # Active users (who were active in last X days)
        active_users = await Seishiro.users.count_documents({
            "last_active": {"$gte": start_date}
        })
        
        # Daily active users (today)
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        daily_active = await Seishiro.users.count_documents({
            "last_active": {"$gte": today_start}
        })
        
        return {
            "total_users": total_users,
            "new_users": new_users,
            "active_users": active_users,
            "daily_active": daily_active,
            "inactive_users": total_users - active_users
        }
    
    @staticmethod
    async def get_top_links(limit: int = 10):
        """Get most accessed links"""
        pipeline = [
            {"$match": {"type": "link_generation"}},
            {"$sort": {"access_count": -1}},
            {"$limit": limit},
            {"$project": {
                "link_id": 1,
                "channel_id": 1,
                "access_count": 1,
                "unique_users": {"$size": "$unique_users"},
                "created_at": 1
            }}
        ]
        
        return await Seishiro.col.aggregate(pipeline).to_list(length=limit)
    
    @staticmethod
    async def get_daily_stats(days: int = 7):
        """Get daily statistics for graph"""
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        # Links per day
        links_pipeline = [
            {"$match": {"type": "link_generation", "date": {"$gte": start_date}}},
            {"$group": {
                "_id": "$date",
                "count": {"$sum": 1}
            }},
            {"$sort": {"_id": 1}}
        ]
        
        # Users per day
        users_pipeline = [
            {"$match": {"join_date": {"$gte": datetime.now() - timedelta(days=days)}}},
            {"$group": {
                "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$join_date"}},
                "count": {"$sum": 1}
            }},
            {"$sort": {"_id": 1}}
        ]
        
        links_data = await Seishiro.col.aggregate(links_pipeline).to_list(length=days)
        users_data = await Seishiro.users.aggregate(users_pipeline).to_list(length=days)
        
        return {
            "links_per_day": links_data,
            "users_per_day": users_data
        }

# ========== ANALYTICS COMMANDS ==========

# /analytics command - Main analytics dashboard
@Bot.on_message(filters.command('analytics') & filters.private & is_owner_or_admin)
async def analytics_command(client: Client, message: Message):
    """Show analytics dashboard"""
    try:
        msg = await message.reply_text("<b>📊 Fᴇᴛᴄʜɪɴɢ ᴀɴᴀʟʏᴛɪᴄs...</b>")
        
        # Get stats for last 7 days
        link_stats = await Analytics.get_link_stats(days=7)
        user_stats = await Analytics.get_user_stats(days=7)
        
        # Get stats for last 30 days
        link_stats_30 = await Analytics.get_link_stats(days=30)
        user_stats_30 = await Analytics.get_user_stats(days=30)
        
        text = f"""
<b>📊 Aɴᴀʟʏᴛɪᴄs Dᴀsʜʙᴏᴀʀᴅ</b>

<b>━━━━━━━━━━━━━━━━━━━</b>

<b>👥 Usᴇʀ Sᴛᴀᴛɪsᴛɪᴄs (7 Dᴀʏs):</b>

• <b>Tᴏᴛᴀʟ Usᴇʀs:</b> <code>{user_stats['total_users']}</code>
• <b>Nᴇᴡ Usᴇʀs:</b> <code>{user_stats['new_users']}</code> 📈
• <b>Aᴄᴛɪᴠᴇ Usᴇʀs:</b> <code>{user_stats['active_users']}</code> ✅
• <b>Dᴀɪʟʏ Aᴄᴛɪᴠᴇ:</b> <code>{user_stats['daily_active']}</code> 🔥
• <b>Iɴᴀᴄᴛɪᴠᴇ Usᴇʀs:</b> <code>{user_stats['inactive_users']}</code> 💤

<b>━━━━━━━━━━━━━━━━━━━</b>

<b>🔗 Lɪɴᴋ Sᴛᴀᴛɪsᴛɪᴄs (7 Dᴀʏs):</b>

• <b>Tᴏᴛᴀʟ Lɪɴᴋs:</b> <code>{link_stats['total_links']}</code>
• <b>Tᴏᴛᴀʟ Aᴄᴄᴇssᴇs:</b> <code>{link_stats['total_accesses']}</code> 👁
• <b>Uɴɪǫᴜᴇ Usᴇʀs:</b> <code>{link_stats['unique_users_count']}</code>
• <b>Aᴠɢ Aᴄᴄᴇss/Lɪɴᴋ:</b> <code>{link_stats['total_accesses'] // max(link_stats['total_links'], 1)}</code>

<b>━━━━━━━━━━━━━━━━━━━</b>

<b>📈 30 Dᴀʏs Cᴏᴍᴘᴀʀɪsᴏɴ:</b>

• <b>Lɪɴᴋs:</b> <code>{link_stats_30['total_links']}</code> ({link_stats['total_links']} ɪɴ 7ᴅ)
• <b>Nᴇᴡ Usᴇʀs:</b> <code>{user_stats_30['new_users']}</code> ({user_stats['new_users']} ɪɴ 7ᴅ)

<b>━━━━━━━━━━━━━━━━━━━</b>

<i>Usᴇ /toplinks ᴛᴏ sᴇᴇ ᴍᴏsᴛ ᴘᴏᴘᴜʟᴀʀ ʟɪɴᴋs
Usᴇ /graph ᴛᴏ sᴇᴇ ᴠɪsᴜᴀʟ ɢʀᴀᴘʜs</i>
"""
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔝 Tᴏᴘ Lɪɴᴋs", callback_data="analytics_toplinks"),
             InlineKeyboardButton("📊 Gʀᴀᴘʜs", callback_data="analytics_graphs")],
            [InlineKeyboardButton("🔄 Rᴇғʀᴇsʜ", callback_data="analytics_refresh"),
             InlineKeyboardButton("❌ Cʟᴏsᴇ", callback_data="close")]
        ])
        
        await msg.edit_text(text, reply_markup=keyboard)
        
    except Exception as e:
        await message.reply_text(f"<b>❌ Eʀʀᴏʀ: {str(e)}</b>")

# /toplinks command - Show most popular links
@Bot.on_message(filters.command('toplinks') & filters.private & is_owner_or_admin)
async def top_links_command(client: Client, message: Message):
    """Show top accessed links"""
    try:
        msg = await message.reply_text("<b>🔝 Fᴇᴛᴄʜɪɴɢ ᴛᴏᴘ ʟɪɴᴋs...</b>")
        
        top_links = await Analytics.get_top_links(limit=10)
        
        if not top_links:
            await msg.edit_text("<b>❌ Nᴏ ʟɪɴᴋs ғᴏᴜɴᴅ!</b>")
            return
        
        text = "<b>🔝 Tᴏᴘ 10 Mᴏsᴛ Aᴄᴄᴇssᴇᴅ Lɪɴᴋs</b>\n\n"
        
        for i, link in enumerate(top_links, 1):
            emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            
            try:
                chat = await client.get_chat(link['channel_id'])
                channel_name = chat.title
            except:
                channel_name = f"Channel {link['channel_id']}"
            
            text += f"""
{emoji} <b>{channel_name}</b>
   • Lɪɴᴋ ID: <code>{link['link_id']}</code>
   • Aᴄᴄᴇssᴇs: <code>{link['access_count']}</code> 👁
   • Uɴɪǫᴜᴇ Usᴇʀs: <code>{link['unique_users']}</code>
   • Cʀᴇᴀᴛᴇᴅ: <code>{link['created_at'].strftime('%d-%b-%Y')}</code>

"""
        
        await msg.edit_text(text)
        
    except Exception as e:
        await message.reply_text(f"<b>❌ Eʀʀᴏʀ: {str(e)}</b>")

# /graph command - Show visual graphs
@Bot.on_message(filters.command('graph') & filters.private & is_owner_or_admin)
async def graph_command(client: Client, message: Message):
    """Generate and send analytics graphs"""
    try:
        msg = await message.reply_text("<b>📊 Gᴇɴᴇʀᴀᴛɪɴɢ ɢʀᴀᴘʜs...</b>")
        
        # Get daily stats
        daily_stats = await Analytics.get_daily_stats(days=7)
        
        # Prepare data
        dates = []
        links_count = []
        users_count = []
        
        # Fill in missing dates
        for i in range(7):
            date = (datetime.now() - timedelta(days=6-i)).strftime("%Y-%m-%d")
            dates.append(date)
            
            # Find link count for this date
            link_data = next((x for x in daily_stats['links_per_day'] if x['_id'] == date), None)
            links_count.append(link_data['count'] if link_data else 0)
            
            # Find user count for this date
            user_data = next((x for x in daily_stats['users_per_day'] if x['_id'] == date), None)
            users_count.append(user_data['count'] if user_data else 0)
        
        # Create graph
        plt.figure(figsize=(12, 6))
        
        # Subplot 1: Links
        plt.subplot(1, 2, 1)
        plt.plot(dates, links_count, marker='o', color='#3498db', linewidth=2)
        plt.title('Links Generated (Last 7 Days)', fontsize=14, fontweight='bold')
        plt.xlabel('Date')
        plt.ylabel('Links Count')
        plt.xticks(rotation=45)
        plt.grid(True, alpha=0.3)
        
        # Subplot 2: Users
        plt.subplot(1, 2, 2)
        plt.plot(dates, users_count, marker='o', color='#2ecc71', linewidth=2)
        plt.title('New Users (Last 7 Days)', fontsize=14, fontweight='bold')
        plt.xlabel('Date')
        plt.ylabel('Users Count')
        plt.xticks(rotation=45)
        plt.grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        # Save to buffer
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
        buf.seek(0)
        plt.close()
        
        # Send graph
        await msg.delete()
        await message.reply_photo(
            photo=buf,
            caption="<b>📊 Aɴᴀʟʏᴛɪᴄs Gʀᴀᴘʜs (Lᴀsᴛ 7 Dᴀʏs)</b>"
        )
        
    except Exception as e:
        await message.reply_text(f"<b>❌ Eʀʀᴏʀ: {str(e)}</b>")

# /userstats command - Detailed user statistics
@Bot.on_message(filters.command('userstats') & filters.private & is_owner_or_admin)
async def user_stats_command(client: Client, message: Message):
    """Show detailed user statistics"""
    try:
        msg = await message.reply_text("<b>👥 Fᴇᴛᴄʜɪɴɢ ᴜsᴇʀ sᴛᴀᴛs...</b>")
        
        # Get various time ranges
        stats_1d = await Analytics.get_user_stats(days=1)
        stats_7d = await Analytics.get_user_stats(days=7)
        stats_30d = await Analytics.get_user_stats(days=30)
        
        text = f"""
<b>👥 Dᴇᴛᴀɪʟᴇᴅ Usᴇʀ Sᴛᴀᴛɪsᴛɪᴄs</b>

<b>━━━━━━━━━━━━━━━━━━━</b>

<b>📊 Oᴠᴇʀᴀʟʟ:</b>
• <b>Tᴏᴛᴀʟ Usᴇʀs:</b> <code>{stats_7d['total_users']}</code>

<b>━━━━━━━━━━━━━━━━━━━</b>

<b>📅 Lᴀsᴛ 24 Hᴏᴜʀs:</b>
• <b>Nᴇᴡ Usᴇʀs:</b> <code>{stats_1d['new_users']}</code> 🆕
• <b>Aᴄᴛɪᴠᴇ Usᴇʀs:</b> <code>{stats_1d['daily_active']}</code> ✅

<b>━━━━━━━━━━━━━━━━━━━</b>

<b>📅 Lᴀsᴛ 7 Dᴀʏs:</b>
• <b>Nᴇᴡ Usᴇʀs:</b> <code>{stats_7d['new_users']}</code> 🆕
• <b>Aᴄᴛɪᴠᴇ Usᴇʀs:</b> <code>{stats_7d['active_users']}</code> ✅
• <b>Iɴᴀᴄᴛɪᴠᴇ Usᴇʀs:</b> <code>{stats_7d['inactive_users']}</code> 💤

<b>━━━━━━━━━━━━━━━━━━━</b>

<b>📅 Lᴀsᴛ 30 Dᴀʏs:</b>
• <b>Nᴇᴡ Usᴇʀs:</b> <code>{stats_30d['new_users']}</code> 🆕
• <b>Aᴄᴛɪᴠᴇ Usᴇʀs:</b> <code>{stats_30d['active_users']}</code> ✅
• <b>Iɴᴀᴄᴛɪᴠᴇ Usᴇʀs:</b> <code>{stats_30d['inactive_users']}</code> 💤

<b>━━━━━━━━━━━━━━━━━━━</b>

<b>📈 Gʀᴏᴡᴛʜ Rᴀᴛᴇ:</b>
• <b>Dᴀɪʟʏ Aᴠɢ:</b> <code>{stats_7d['new_users'] // 7}</code> ɴᴇᴡ ᴜsᴇʀs/ᴅᴀʏ
• <b>Wᴇᴇᴋʟʏ Aᴠɢ:</b> <code>{stats_30d['new_users'] // 4}</code> ɴᴇᴡ ᴜsᴇʀs/ᴡᴇᴇᴋ
"""
        
        await msg.edit_text(text)
        
    except Exception as e:
        await message.reply_text(f"<b>❌ Eʀʀᴏʀ: {str(e)}</b>")

# Callback query handler for analytics buttons
@Bot.on_callback_query(filters.regex("^analytics_"))
async def analytics_callback(client: Client, callback_query):
    """Handle analytics button callbacks"""
    try:
        data = callback_query.data.split("_")[1]
        
        if data == "refresh":
            # Refresh analytics
            await callback_query.answer("🔄 Rᴇғʀᴇsʜɪɴɢ...")
            # Call analytics command again
            await analytics_command(client, callback_query.message)
            
        elif data == "toplinks":
            await callback_query.answer("🔝 Fᴇᴛᴄʜɪɴɢ ᴛᴏᴘ ʟɪɴᴋs...")
            await top_links_command(client, callback_query.message)
            
        elif data == "graphs":
            await callback_query.answer("📊 Gᴇɴᴇʀᴀᴛɪɴɢ ɢʀᴀᴘʜs...")
            await graph_command(client, callback_query.message)
            
    except Exception as e:
        await callback_query.answer(f"❌ Eʀʀᴏʀ: {str(e)}", show_alert=True)
