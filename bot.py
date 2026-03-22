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
import os

pyrogram.utils.MIN_CHANNEL_ID = -1002449417637

name = """
Link share bot started ✨ Credit:- @Suhanibots
"""

class Bot(Client):
    def __init__(self):
        # 🔥 IMPORTANT: Set LOGGER first before using it
        self.LOGGER = LOGGER
        
        # 🔥 FIX: Use string session for persistence across restarts
        session_string = os.getenv("SESSION_STRING", "")
        
        if session_string:
            # Production: String session use karo
            super().__init__(
                name="Bot",
                session_string=session_string,
                api_hash=API_HASH,
                api_id=APP_ID,
                plugins={"root": "plugins"},
                workers=TG_BOT_WORKERS,
                bot_token=TG_BOT_TOKEN,
            )
            self.LOGGER(__name__).info("✅ Using STRING SESSION (persistent)")
        else:
            # Development: File session use karo
            super().__init__(
                name="Bot",
                api_hash=API_HASH,
                api_id=APP_ID,
                plugins={"root": "plugins"},
                workers=TG_BOT_WORKERS,
                bot_token=TG_BOT_TOKEN,
            )
            self.LOGGER(__name__).info("⚠️  Using FILE SESSION (not persistent)")

    async def start(self, *args, **kwargs):
        await super().start()
        usr_bot_me = await self.get_me()
        self.uptime = datetime.now()
        
        # 🔥 OPTIONAL: Skip channel validation if environment variable is set
        skip_validation = os.getenv("SKIP_VALIDATION", "false").lower() == "true"
        
        if skip_validation:
            self.LOGGER(__name__).warning("⚠️  Channel validation SKIPPED (SKIP_VALIDATION=true)")
        
        # 🔥 IMPORTANT: Pre-resolve all channels on startup
        if not skip_validation:
            try:
                from database.database import Seishiro
            
            self.LOGGER(__name__).info("=" * 60)
            self.LOGGER(__name__).info("🔄 RESOLVING CHANNEL PEERS...")
            self.LOGGER(__name__).info("=" * 60)
            
            channels = await Seishiro.get_channels()
            
            if channels:
                self.LOGGER(__name__).info(f"📋 Found {len(channels)} channel(s)")
                
                resolved_count = 0
                failed_count = 0
                invalid_channels = []
                
                for idx, channel_id in enumerate(channels, 1):
                    try:
                        # Resolve peer to populate session cache
                        chat = await self.get_chat(channel_id)
                        
                        # Verify bot is admin
                        member = await self.get_chat_member(channel_id, "me")
                        
                        if member.status not in ["administrator", "creator"]:
                            self.LOGGER(__name__).warning(
                                f"⚠️  [{idx}/{len(channels)}] Not admin: {channel_id} ({chat.title})"
                            )
                            invalid_channels.append(channel_id)
                            failed_count += 1
                            continue
                        
                        if not member.privileges or not member.privileges.can_invite_users:
                            self.LOGGER(__name__).warning(
                                f"⚠️  [{idx}/{len(channels)}] No invite permission: {channel_id} ({chat.title})"
                            )
                            invalid_channels.append(channel_id)
                            failed_count += 1
                            continue
                        
                        resolved_count += 1
                        self.LOGGER(__name__).info(
                            f"✓ [{resolved_count}/{len(channels)}] {chat.title}"
                        )
                        
                    except Exception as e:
                        failed_count += 1
                        invalid_channels.append(channel_id)
                        self.LOGGER(__name__).warning(
                            f"✗ [{idx}/{len(channels)}] Failed {channel_id}: {e}"
                        )
                
                # Auto-cleanup invalid channels
                if invalid_channels:
                    self.LOGGER(__name__).warning("=" * 60)
                    self.LOGGER(__name__).warning(f"🗑️  Marking {len(invalid_channels)} invalid channels as inactive...")
                    
                    for channel_id in invalid_channels:
                        try:
                            await Seishiro.channel_data.update_one(
                                {"channel_id": channel_id},
                                {"$set": {"status": "inactive", "inactive_at": datetime.utcnow()}}
                            )
                        except:
                            pass
                    
                    self.LOGGER(__name__).info(f"✅ Cleaned up {len(invalid_channels)} channels")
                    self.LOGGER(__name__).warning("=" * 60)
                
                self.LOGGER(__name__).info("=" * 60)
                self.LOGGER(__name__).info(
                    f"✅ RESOLUTION COMPLETE: {resolved_count} valid, {failed_count} invalid"
                )
                self.LOGGER(__name__).info("=" * 60)
            else:
                self.LOGGER(__name__).info("📭 No channels in database")
                
        except Exception as e:
            self.LOGGER(__name__).error(f"❌ Error during peer resolution: {e}")
        
        # End of validation block
        else:
            self.LOGGER(__name__).info("⚠️  Skipping channel validation")
        
        # Notify restart
        try:
            await self.send_photo(
                chat_id=DATABASE_CHANNEL,
                photo="https://telegra.ph/file/d3c1d3f1e58c3164f8e2e.jpg",
                caption=("**🤖 I ʀᴇsᴛᴀʀᴛᴇᴅ ᴀɢᴀɪɴ !**"),
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("ᴜᴘᴅᴀᴛᴇs", url="https://t.me/Suhanibots")]]
                )
            )
        except Exception as e:
            self.LOGGER(__name__).warning(f"⚠️  Failed to send restart message: {e}")
        
        self.set_parse_mode(ParseMode.HTML)
        self.LOGGER(__name__).info("⚡ Bot is running... Credit:- @Suhanibots")
        self.LOGGER(__name__).info(f"{name}")
        self.username = usr_bot_me.username
        
        # Web server
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
