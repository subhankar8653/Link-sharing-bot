import asyncio
import os
import stat
import sys
from datetime import datetime
from pyrogram import Client
from pyrogram.enums import ParseMode, ChatMemberStatus
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import PeerIdInvalid, ChatAdminRequired, RPCError
from config import *
from plugins import web_server
import pyrogram.utils
from aiohttp import web

pyrogram.utils.MIN_CHANNEL_ID = -1002449417637

name = """
Link share bot started ✨ Credit:- @Suhanibots
"""

# ═══════════════════════════════════════════════════════════════
# ROBUST ADMIN CHECKER  (inspired by help_Lucky.py)
# Redeploy ke baad bhi sahi kaam karta hai — PeerIdInvalid handle
# ═══════════════════════════════════════════════════════════════
async def check_bot_permissions(client: Client, channel_id: int):
    """
    Bot ka admin status properly check karta hai.
    Returns: (is_admin: bool, can_invite: bool, reason: str | None)

    help_Lucky.py ki check_bot_permissions() se inspired — woh aiogram
    mein ChatMemberOwner/Administrator isinstance check karta tha,
    hum yahan Pyrogram ke ChatMemberStatus enum se karte hain.
    """
    try:
        member = await client.get_chat_member(channel_id, "me")
        status = member.status

        # Owner ko saari permissions hoti hain
        if status == ChatMemberStatus.OWNER:
            return True, True, None

        # Administrator check
        if status == ChatMemberStatus.ADMINISTRATOR:
            can_invite = getattr(member.privileges, "can_invite_users", False)
            if not can_invite:
                return True, False, "Bot ko 'Invite Users' permission chahiye"
            return True, True, None

        # Bot admin hi nahi hai
        return False, False, "Bot is channel mein admin nahi hai"

    except PeerIdInvalid:
        # Peer session mein nahi — yahi redeploy ke baad hota tha
        # get_chat() se peer resolve karke retry karte hain
        try:
            await client.get_chat(channel_id)
            # Retry after resolution
            return await check_bot_permissions(client, channel_id)
        except Exception as e:
            return False, False, f"Peer resolve failed: {str(e)[:60]}"

    except ChatAdminRequired:
        return False, False, "Bot ko admin banana zaroori hai"

    except RPCError as e:
        return False, False, f"Telegram error: {str(e)[:60]}"

    except Exception as e:
        return False, False, f"Unknown error: {str(e)[:60]}"


# ═══════════════════════════════════════════════════════════════
# PEER RESOLUTION  (redeploy fix — session cache warm-up)
# ═══════════════════════════════════════════════════════════════
async def resolve_all_peers(client: Client, channels: list):
    """
    Startup pe sabhi channels ka peer resolve karta hai.

    Yeh zaroor karo — redeploy ke baad Pyrogram ka session
    nayi machine pe blank hota hai. Bina is step ke pehli
    invite link request pe PeerIdInvalid aata hai.

    Logic: get_chat() Pyrogram ke internal session cache mein
    peer data store karta hai, jisse baad ke API calls fail nahi hote.
    """
    logger = LOGGER(__name__)
    logger.info("=" * 60)
    logger.info("🔍 PEER RESOLUTION STARTING...")
    logger.info("=" * 60)

    resolved = 0
    failed = 0
    total = len(channels)

    for channel_id in channels:
        try:
            chat = await client.get_chat(channel_id)
            resolved += 1
            logger.info(f"✅ [{resolved}/{total}] Resolved: {channel_id} → {chat.title}")
        except PeerIdInvalid:
            # Channel ID DB mein hai lekin bot kabhi is channel mein gaya nahi
            # ya channel delete ho gaya — dono cases ignore karo
            failed += 1
            logger.warning(f"⚠️  [{resolved + failed}/{total}] PeerIdInvalid: {channel_id} — skipping")
        except Exception as e:
            failed += 1
            logger.warning(f"❌ [{resolved + failed}/{total}] Failed: {channel_id} — {e}")

    logger.info("=" * 60)
    logger.info(f"PEER RESOLUTION DONE: {resolved} OK / {failed} failed / {total} total")
    logger.info("=" * 60)
    return resolved, failed


class Bot(Client):
    def __init__(self):
        super().__init__(
            name="/tmp/Bot",
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
        self.username = usr_bot_me.username

        logger = self.LOGGER(__name__)

        # ── 1. Session Reset (agar RESET_SESSION=true env var set ho) ──
        if os.getenv("RESET_SESSION", "false").lower() == "true":
            logger.info("=" * 60)
            logger.info("♻️  SESSION RESET ACTIVATED")
            for file in ["/tmp/Bot.session", "/tmp/Bot.session-journal"]:
                if os.path.exists(file):
                    try:
                        os.chmod(file, stat.S_IWRITE | stat.S_IREAD)
                        os.remove(file)
                        logger.info(f"🗑️  Deleted: {file}")
                    except PermissionError:
                        try:
                            os.system(f"rm -f '{file}'")
                            logger.info(f"🗑️  Force deleted: {file}")
                        except Exception as e:
                            logger.error(f"❌ Could not delete {file}: {e}")
                    except Exception as e:
                        logger.error(f"❌ Could not delete {file}: {e}")
            logger.info("🔄 Fresh session will be created in /tmp...")
            logger.info("=" * 60)

        # ── 2. Peer Resolution — redeploy ke baad PeerIdInvalid fix ──
        try:
            from database.database import Seishiro

            # Saare channels fetch karo: link-share + fsub dono
            link_channels = await Seishiro.get_channels()
            fsub_channels = await Seishiro.get_fsub_channels()

            # Duplicate hata ke ek list banao
            all_channels = list(set(link_channels + fsub_channels))
            # DATABASE_CHANNEL bhi add karo
            if DATABASE_CHANNEL and DATABASE_CHANNEL not in all_channels:
                all_channels.append(DATABASE_CHANNEL)

            if all_channels:
                await resolve_all_peers(self, all_channels)
            else:
                logger.info("No channels in database. Skipping peer resolution.")

        except Exception as e:
            logger.error(f"Peer resolution error: {e}")
            logger.warning("Bot will continue — PeerIdInvalid possible on first request")

        # ── 3. Restart notification ──
        try:
            await self.send_photo(
                chat_id=DATABASE_CHANNEL,
                photo="https://ibb.co/jky6J3D7",
                caption="<b>I ʀᴇsᴛᴀʀᴛᴇᴅ ᴀɢᴀɪɴ !</b>",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("ᴜᴘᴅᴀᴛᴇs", url="https://t.me/Suhanibots")]]
                )
            )
        except Exception as e:
            logger.warning(f"Restart notification failed: {e}")

        self.set_parse_mode(ParseMode.HTML)
        logger.info("Bot is running ⚡  Credit:- @Suhanibots")
        logger.info(name)

        # ── 4. Web server ──
        try:
            app = web.AppRunner(await web_server())
            await app.setup()
            await web.TCPSite(app, "0.0.0.0", PORT).start()
            logger.info(f"Web server started on 0.0.0.0:{PORT}")
        except Exception as e:
            logger.error(f"Web server failed: {e}")

    async def stop(self, *args):
        await super().stop()
        self.LOGGER(__name__).info("Bot stopped.")


if __name__ == "__main__":
    Bot().run()
