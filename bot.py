import asyncio
import os
import signal
import stat
from datetime import datetime
from pyrogram import Client
from pyrogram.enums import ParseMode, ChatMemberStatus
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import (
    PeerIdInvalid, ChatAdminRequired, RPCError,
    FloodWait, ChannelInvalid, ChannelPrivate
)
from pyrogram import raw
from config import *
from plugins import web_server
import pyrogram.utils
from aiohttp import web

pyrogram.utils.MIN_CHANNEL_ID = -1002449417637

name = "Link share bot started ✨ Credit:- @Suhanibots"


# ═══════════════════════════════════════════════════════════════
# DEEP PEER RESOLUTION
# Normal get_chat() fresh session pe fail karta hai kyunki
# Pyrogram ko pehle channel ka access_hash chahiye hota hai.
# Yeh function Telegram ke raw API (GetChannels) se directly
# woh data fetch karta hai — bina session cache ke bhi kaam karta hai.
# ═══════════════════════════════════════════════════════════════
async def _force_resolve_peer(client: Client, channel_id: int) -> bool:
    """
    Ek channel ko raw API se resolve karta hai.
    Returns True agar successfully resolve hua, False otherwise.

    Pyrogram internally peer ko session DB mein store karta hai
    jab bhi resolve_peer() successfully return kare. Iske baad
    get_chat(), get_chat_member(), create_chat_invite_link() sab
    kaam karte hain bina PeerIdInvalid ke.
    """
    try:
        # Step 1: resolve_peer() try karo — session mein already hai toh yahi kaafi
        await client.resolve_peer(channel_id)
        return True
    except PeerIdInvalid:
        pass
    except Exception:
        pass

    try:
        # Step 2: Raw GetChannels call — access_hash ki zarurat nahi
        # Yeh Telegram se seedha channel info maangta hai aur
        # Pyrogram apne aap peer cache update kar leta hai
        channel_id_without_prefix = -(channel_id + 1000000000000)  # -100XXXXX → XXXXX
        result = await client.invoke(
            raw.functions.channels.GetChannels(
                id=[raw.types.InputChannel(
                    channel_id=channel_id_without_prefix,
                    access_hash=0  # 0 bhi chalega bot ke liye
                )]
            )
        )
        if result and result.chats:
            return True
    except Exception:
        pass

    try:
        # Step 3: get_chat() fallback — kabhi kabhi yeh bhi kaam karta hai
        await client.get_chat(channel_id)
        return True
    except Exception:
        return False


async def resolve_all_peers(client: Client, channels: list):
    """
    Startup pe sabhi channels resolve karta hai.
    Redeploy ke baad fresh session pe bhi kaam karta hai.
    """
    logger = LOGGER(__name__)
    logger.info("=" * 60)
    logger.info("🔍 PEER RESOLUTION STARTING (Deep Mode)...")
    logger.info("=" * 60)

    resolved = failed = 0
    total = len(channels)

    for i, channel_id in enumerate(channels, 1):
        try:
            ok = await _force_resolve_peer(client, channel_id)
            if ok:
                resolved += 1
                # Title get karne ki koshish
                try:
                    chat = await client.get_chat(channel_id)
                    logger.info(f"✅ [{i}/{total}] {channel_id} → {chat.title}")
                except Exception:
                    logger.info(f"✅ [{i}/{total}] {channel_id} → resolved (no title)")
            else:
                failed += 1
                logger.warning(f"⚠️  [{i}/{total}] {channel_id} → could not resolve (check bot is admin)")
        except FloodWait as e:
            logger.warning(f"FloodWait {e.value}s — waiting...")
            await asyncio.sleep(e.value)
            # Retry
            ok = await _force_resolve_peer(client, channel_id)
            resolved += ok
            failed += not ok
        except Exception as e:
            failed += 1
            logger.warning(f"❌ [{i}/{total}] {channel_id} → {e}")

        # Telegram rate limit se bachne ke liye
        await asyncio.sleep(0.3)

    logger.info("=" * 60)
    logger.info(f"DONE: ✅ {resolved} resolved / ❌ {failed} failed / 📊 {total} total")
    logger.info("=" * 60)
    return resolved, failed


# ═══════════════════════════════════════════════════════════════
# ADMIN + PERMISSION CHECKER
# Peer resolve ke baad yeh call karo.
# Returns: (is_admin, can_invite, reason)
# ═══════════════════════════════════════════════════════════════
async def check_bot_permissions(client: Client, channel_id: int):
    """
    Bot ka admin status + invite permission check.
    Agar PeerIdInvalid aaye toh pehle resolve karta hai, phir retry.
    """
    async def _check(channel_id):
        member = await client.get_chat_member(channel_id, "me")
        status = member.status
        if status == ChatMemberStatus.OWNER:
            return True, True, None
        if status == ChatMemberStatus.ADMINISTRATOR:
            can_invite = getattr(member.privileges, "can_invite_users", False)
            if not can_invite:
                return True, False, "Bot ko 'Invite Users' permission chahiye"
            return True, True, None
        return False, False, "Bot is channel mein admin nahi hai"

    try:
        return await _check(channel_id)
    except PeerIdInvalid:
        # Peer abhi bhi nahi mila — force resolve karke retry
        ok = await _force_resolve_peer(client, channel_id)
        if not ok:
            return False, False, "Channel resolve nahi hua — bot admin hai? Channel exist karta hai?"
        try:
            return await _check(channel_id)
        except Exception as e:
            return False, False, f"Retry failed: {str(e)[:80]}"
    except (ChannelInvalid, ChannelPrivate):
        return False, False, "Channel exist nahi karta ya private hai"
    except ChatAdminRequired:
        return False, False, "Bot ko admin banana zaroori hai"
    except RPCError as e:
        return False, False, f"Telegram error: {str(e)[:60]}"
    except Exception as e:
        return False, False, f"Unknown: {str(e)[:60]}"


# ═══════════════════════════════════════════════════════════════
# BOT CLASS
# ═══════════════════════════════════════════════════════════════
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

        # ── 1. Session Reset ──────────────────────────────────────────
        if os.getenv("RESET_SESSION", "false").lower() == "true":
            logger.info("=" * 60)
            logger.info("♻️  SESSION RESET ACTIVATED")
            for f in ["/tmp/Bot.session", "/tmp/Bot.session-journal"]:
                if os.path.exists(f):
                    try:
                        os.chmod(f, stat.S_IWRITE | stat.S_IREAD)
                        os.remove(f)
                        logger.info(f"🗑️  Deleted: {f}")
                    except Exception:
                        os.system(f"rm -f '{f}'")
                        logger.info(f"🗑️  Force deleted: {f}")
            logger.info("🔄 Fresh session will be created in /tmp...")
            logger.info("=" * 60)

        # ── 2. Deep Peer Resolution ───────────────────────────────────
        # Yeh step ZAROOR chahiye redeploy ke baad.
        # Fresh session mein Pyrogram ko channels ka access_hash nahi
        # hota. _force_resolve_peer() raw API se woh data fetch karta
        # hai taaki baad ke saare API calls (get_chat_member,
        # create_chat_invite_link, etc.) bina error ke kaam karein.
        try:
            from database.database import Seishiro
            link_ch  = await Seishiro.get_channels()
            fsub_ch  = await Seishiro.get_fsub_channels()
            all_ch   = list(set(link_ch + fsub_ch))
            if DATABASE_CHANNEL and DATABASE_CHANNEL not in all_ch:
                all_ch.append(DATABASE_CHANNEL)

            if all_ch:
                logger.info(f"Resolving {len(all_ch)} channels...")
                await resolve_all_peers(self, all_ch)
            else:
                logger.info("No channels in DB — skipping peer resolution.")
        except Exception as e:
            logger.error(f"Peer resolution error: {e}")
            logger.warning("Bot will continue — some channels may show PeerIdInvalid")

        # ── 3. Restart Notification ───────────────────────────────────
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
        logger.info(f"Bot is running ⚡  @{self.username}")
        logger.info(name)

        # ── 4. Web Server ─────────────────────────────────────────────
        try:
            app = web.AppRunner(await web_server())
            await app.setup()
            await web.TCPSite(app, "0.0.0.0", PORT).start()
            logger.info(f"Web server: 0.0.0.0:{PORT}")
        except Exception as e:
            logger.error(f"Web server failed: {e}")

    async def stop(self, *args):
        await super().stop()
        self.LOGGER(__name__).info("Bot stopped.")


if __name__ == "__main__":
    import signal as _signal
    _bot = Bot()
    _loop = asyncio.get_event_loop()

    def _shutdown(sig):
        LOGGER(__name__).info(f"Signal {sig.name} — graceful shutdown...")
        _loop.create_task(_bot.stop())

    for _sig in (_signal.SIGTERM, _signal.SIGINT):
        try:
            _loop.add_signal_handler(_sig, _shutdown, _sig)
        except Exception:
            pass

    _bot.run()
