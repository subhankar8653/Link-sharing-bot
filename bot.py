import asyncio
import sys
from datetime import datetime
from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from config import *
from plugins import web_server
import pyrogram.utils
from aiohttp import web

pyrogram.utils.MIN_CHANNEL_ID = -1002449417637

name = """
Link share bot started ✨ Credit:- @Suhanibots
"""

class Bot(Client):
    def __init__(self):
        # Store session in current directory for persistence
        super().__init__(
            name="Bot",  # Will create Bot.session in current directory
            api_hash=API_HASH,
            api_id=APP_ID,
            plugins={"root": "plugins"},
            workers=TG_BOT_WORKERS,
            bot_token=TG_BOT_TOKEN,
        )
        self.LOGGER = LOGGER

    async def start(self, *args, **kwargs):
        await super().start()
        usr_bot_me = await self.get_me()
        self.uptime = datetime.now()
        
        # 🔥 FIX: Better channel peer resolution with auto-cleanup
        try:
            from database.database import Seishiro
            
            self.LOGGER(__name__).info("=" * 60)
            self.LOGGER(__name__).info("🔄 STARTING CHANNEL VALIDATION & PEER RESOLUTION...")
            self.LOGGER(__name__).info("=" * 60)
            
            # Get all channels from database
            channels = await Seishiro.get_channels()
            
            if channels:
                self.LOGGER(__name__).info(f"📋 Found {len(channels)} channel(s) in database")
                self.LOGGER(__name__).info("🔍 Validating and resolving peers...")
                
                resolved_count = 0
                failed_count = 0
                invalid_channels = []
                
                for idx, channel_id in enumerate(channels, 1):
                    try:
                        # Validate channel exists and bot has access
                        chat = await self.get_chat(channel_id)
                        
                        # Check if bot is admin
                        member = await self.get_chat_member(channel_id, "me")
                        
                        if member.status not in ["administrator", "creator"]:
                            self.LOGGER(__name__).warning(
                                f"⚠️  [{idx}/{len(channels)}] Bot is not admin in {channel_id} ({chat.title})"
                            )
                            invalid_channels.append(channel_id)
                            failed_count += 1
                            continue
                        
                        # Check if bot has invite permission
                        if not member.privileges or not member.privileges.can_invite_users:
                            self.LOGGER(__name__).warning(
                                f"⚠️  [{idx}/{len(channels)}] No invite permission in {channel_id} ({chat.title})"
                            )
                            invalid_channels.append(channel_id)
                            failed_count += 1
                            continue
                        
                        resolved_count += 1
                        self.LOGGER(__name__).info(
                            f"✓ [{resolved_count}/{len(channels)}] Resolved: {channel_id} ({chat.title})"
                        )
                        
                    except Exception as e:
                        failed_count += 1
                        invalid_channels.append(channel_id)
                        self.LOGGER(__name__).warning(
                            f"✗ [{idx}/{len(channels)}] Failed: {channel_id} - {e}"
                        )
                
                # 🔥 AUTO-CLEANUP: Remove invalid channels from database
                if invalid_channels:
                    self.LOGGER(__name__).warning("=" * 60)
                    self.LOGGER(__name__).warning(f"🗑️  AUTO-CLEANUP: Removing {len(invalid_channels)} invalid channels...")
                    
                    removed = 0
                    for channel_id in invalid_channels:
                        try:
                            await Seishiro.channel_data.update_one(
                                {"channel_id": channel_id},
                                {"$set": {"status": "inactive", "inactive_reason": "Failed validation", "inactive_at": datetime.utcnow()}}
                            )
                            removed += 1
                            self.LOGGER(__name__).info(f"  🗑️  Marked {channel_id} as inactive")
                        except Exception as e:
                            self.LOGGER(__name__).error(f"  ❌ Failed to mark {channel_id} as inactive: {e}")
                    
                    self.LOGGER(__name__).info(f"✅ Removed {removed} invalid channels from active list")
                    self.LOGGER(__name__).warning("=" * 60)
                
                self.LOGGER(__name__).info("=" * 60)
                self.LOGGER(__name__).info(
                    f"✅ VALIDATION COMPLETE: {resolved_count} valid, {failed_count} invalid (cleaned)"
                )
                self.LOGGER(__name__).info("=" * 60)
            else:
                self.LOGGER(__name__).info("📭 No channels found in database. Skipping validation.")
                
        except Exception as e:
            self.LOGGER(__name__).error(f"❌ Error during channel validation: {e}")
            self.LOGGER(__name__).warning("⚠️  Bot will continue, but may encounter errors")
        
        # Notify bot restart
        try:
            await self.send_photo(
                chat_id=DATABASE_CHANNEL,
                photo="https://telegra.ph/file/your-image-here.jpg",  # Replace with valid image URL
                caption=("**🤖 I ʀᴇsᴛᴀʀᴛᴇᴅ ᴀɢᴀɪɴ !**"),
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("ᴜᴘᴅᴀᴛᴇs", url="https://t.me/Suhanibots")]]
                )
            )
        except Exception as e:
            self.LOGGER(__name__).warning(f"⚠️  Failed to send bot start message: {e}")
        
        self.set_parse_mode(ParseMode.HTML)
        self.LOGGER(__name__).info("⚡ Bot is running... Credit:- @Suhanibots")
        self.LOGGER(__name__).info(f"{name}")
        self.username = usr_bot_me.username
        
        # Web-response
        try:
            app = web.AppRunner(await web_server())
            await app.setup()
            bind_address = "0.0.0.0"
            await web.TCPSite(app, bind_address, PORT).start()
            self.LOGGER(__name__).info(f"🌐 Web server started on {bind_address}:{PORT}")
        except Exception as e:
            self.LOGGER(__name__).error(f"❌ Failed to start web server: {e}")

    async def stop(self, *args):
        await super().stop()
        self.LOGGER(__name__).info("🛑 Bot stopped...")
        

if __name__ == "__main__":
    Bot().run()
