# ========================================
# CHANNEL-WIDE ADMIN COMMANDS
# Bot jitne channels (link-share + FSub) mein admin hai, un SABHI par
# ek saath action lene ke liye commands. Sirf owner/admin use kar sakte hain.
#
#   /fban <user_id>          -> user ko har channel se ban karo
#   /funban <user_id>        -> user ko har channel se unban karo
#     (naam /unban nahi rakha kyunki bot mein pehle se /unban command
#      hai jo bot-access ban system ke liye hai — conflict avoid karne
#      ke liye /funban rakha hai.)
#   /gbroadcast (reply)      -> reply kiye gaye message ko har channel
#                                mein bhejo (line by line, delay ke saath)
#   /cbroadcast              -> pichhle /gbroadcast se bheje gaye
#                                messages ko har channel se delete karo
#   /gdescription <text>     -> har channel ka description set karo
#                                (jo pehle se likha hai wo overwrite ho jayega)
#   /cdescription             -> har channel ka description clear (khaali) karo
#
# Rate-limit se bachne ke liye har channel ke beech mein chhota sa delay
# (line by line) diya gaya hai, aur FloodWait aane par utna hi wait karke
# retry kiya jaata hai.
# ========================================

import asyncio
import logging

from bot import Bot
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait, RPCError

from config import OWNER_ID
from database.database import Seishiro

logger = logging.getLogger(__name__)

# Har channel action ke beech ka delay (seconds) — "line by line" taaki
# Telegram ka flood/rate limit na lage.
CHANNEL_ACTION_DELAY = 2.5
DESCRIPTION_ACTION_DELAY = 3.5   # description edits Telegram pe zyada strict hain
BROADCAST_ACTION_DELAY = 3.0


async def is_owner_or_admin(filter, client, message):
    try:
        user_id = message.from_user.id
        return any([user_id == OWNER_ID, await Seishiro.is_admin(user_id)])
    except Exception:
        return False

is_owner_or_admin = filters.create(is_owner_or_admin)


async def _get_target_channels(message: Message):
    """Admin wali sabhi channels laao; khaali ho to user ko bata do (None return)."""
    channels = await Seishiro.get_admin_channels()
    if not channels:
        await message.reply_text(
            "<b>❌ Koi channel nahi mila. Pehle /addchannel ya FSub se kam se kam ek channel add karo.</b>"
        )
        return None
    return channels


async def _resolve_chat_title(client: Client, channel_id: int) -> str:
    try:
        chat = await client.get_chat(channel_id)
        return chat.title or str(channel_id)
    except Exception:
        return str(channel_id)


# ─────────────────────────────────────────────
# /fban — sabhi channels se ban
# ─────────────────────────────────────────────
@Bot.on_message(filters.command("fban") & filters.private & is_owner_or_admin)
async def fban_cmd(client: Client, message: Message):
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip().lstrip('-').isdigit():
            await message.reply_text(
                "<b>Usᴇ: /fban user_id</b>\n"
                "Exᴀᴍᴘʟᴇ: <code>/fban 123456789</code>\n\n"
                "Isse user ko bot jitne channels mein admin hai un SABHI se ban kar dega."
            )
            return

        target_id = int(parts[1].strip())

        channels = await _get_target_channels(message)
        if channels is None:
            return

        total = len(channels)
        status = await message.reply_text(
            f"<b>🚫 Fʙᴀɴ sʜᴜʀᴜ...</b>\nTotal channels: {total}\nDone: 0/{total}"
        )

        success = failed = 0
        for idx, channel_id in enumerate(channels, 1):
            try:
                await client.ban_chat_member(channel_id, target_id)
                success += 1
            except FloodWait as fw:
                await asyncio.sleep(fw.value)
                try:
                    await client.ban_chat_member(channel_id, target_id)
                    success += 1
                except Exception as e:
                    logger.error(f"fban retry failed for {channel_id}: {e}")
                    failed += 1
            except RPCError as e:
                logger.error(f"fban error in {channel_id}: {e}")
                failed += 1
            except Exception as e:
                logger.error(f"fban unexpected error in {channel_id}: {e}")
                failed += 1

            if idx % 5 == 0 or idx == total:
                try:
                    await status.edit(
                        f"<b>🚫 Fʙᴀɴ ᴄʜᴀʟ ʀᴀʜᴀ ʜᴀɪ...</b>\n"
                        f"Total: {total} | Done: {idx}/{total}\n✅ {success}  ❌ {failed}"
                    )
                except Exception:
                    pass

            await asyncio.sleep(CHANNEL_ACTION_DELAY)

        await status.edit(
            f"<b>✅ Fʙᴀɴ ᴄᴏᴍᴘʟᴇᴛᴇ!</b>\n"
            f"Usᴇʀ: <code>{target_id}</code>\n"
            f"Total channels: {total}\n✅ Success: {success}  ❌ Failed: {failed}"
        )
    except Exception as e:
        logger.error(f"fban_cmd fatal: {e}")
        await message.reply_text(f"<b>❌ Eʀʀᴏʀ: {e}</b>")


# ─────────────────────────────────────────────
# /funban — sabhi channels se unban
# ─────────────────────────────────────────────
@Bot.on_message(filters.command("funban") & filters.private & is_owner_or_admin)
async def funban_cmd(client: Client, message: Message):
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip().lstrip('-').isdigit():
            await message.reply_text(
                "<b>Usᴇ: /funban user_id</b>\n"
                "Exᴀᴍᴘʟᴇ: <code>/funban 123456789</code>\n\n"
                "Isse user ko bot jitne channels mein admin hai un SABHI se unban kar dega."
            )
            return

        target_id = int(parts[1].strip())

        channels = await _get_target_channels(message)
        if channels is None:
            return

        total = len(channels)
        status = await message.reply_text(
            f"<b>✅ Fᴜɴʙᴀɴ sʜᴜʀᴜ...</b>\nTotal channels: {total}\nDone: 0/{total}"
        )

        success = failed = 0
        for idx, channel_id in enumerate(channels, 1):
            try:
                await client.unban_chat_member(channel_id, target_id)
                success += 1
            except FloodWait as fw:
                await asyncio.sleep(fw.value)
                try:
                    await client.unban_chat_member(channel_id, target_id)
                    success += 1
                except Exception as e:
                    logger.error(f"funban retry failed for {channel_id}: {e}")
                    failed += 1
            except RPCError as e:
                logger.error(f"funban error in {channel_id}: {e}")
                failed += 1
            except Exception as e:
                logger.error(f"funban unexpected error in {channel_id}: {e}")
                failed += 1

            if idx % 5 == 0 or idx == total:
                try:
                    await status.edit(
                        f"<b>✅ Fᴜɴʙᴀɴ ᴄʜᴀʟ ʀᴀʜᴀ ʜᴀɪ...</b>\n"
                        f"Total: {total} | Done: {idx}/{total}\n✅ {success}  ❌ {failed}"
                    )
                except Exception:
                    pass

            await asyncio.sleep(CHANNEL_ACTION_DELAY)

        await status.edit(
            f"<b>✅ Fᴜɴʙᴀɴ ᴄᴏᴍᴘʟᴇᴛᴇ!</b>\n"
            f"Usᴇʀ: <code>{target_id}</code>\n"
            f"Total channels: {total}\n✅ Success: {success}  ❌ Failed: {failed}"
        )
    except Exception as e:
        logger.error(f"funban_cmd fatal: {e}")
        await message.reply_text(f"<b>❌ Eʀʀᴏʀ: {e}</b>")


# ─────────────────────────────────────────────
# /gbroadcast — reply kiye gaye message ko sabhi channels mein bhejo
# ─────────────────────────────────────────────
@Bot.on_message(filters.command("gbroadcast") & filters.private & is_owner_or_admin)
async def gbroadcast_cmd(client: Client, message: Message):
    try:
        if not message.reply_to_message:
            await message.reply_text(
                "<b>⚠️ Kisi message ko reply karke /gbroadcast likho.</b>\n\n"
                "Ye message bot jitne channels mein admin hai un SABHI mein bhej dega."
            )
            return

        channels = await _get_target_channels(message)
        if channels is None:
            return

        total = len(channels)
        status = await message.reply_text(
            f"<b>📤 Gʙʀᴏᴀᴅᴄᴀsᴛ sʜᴜʀᴜ...</b>\nTotal channels: {total}\nDone: 0/{total}"
        )

        src = message.reply_to_message
        entries = []
        success = failed = 0

        for idx, channel_id in enumerate(channels, 1):
            try:
                sent = await src.copy(channel_id)
                entries.append({"channel_id": channel_id, "message_id": sent.id})
                success += 1
            except FloodWait as fw:
                await asyncio.sleep(fw.value)
                try:
                    sent = await src.copy(channel_id)
                    entries.append({"channel_id": channel_id, "message_id": sent.id})
                    success += 1
                except Exception as e:
                    logger.error(f"gbroadcast retry failed for {channel_id}: {e}")
                    failed += 1
            except RPCError as e:
                logger.error(f"gbroadcast error in {channel_id}: {e}")
                failed += 1
            except Exception as e:
                logger.error(f"gbroadcast unexpected error in {channel_id}: {e}")
                failed += 1

            if idx % 5 == 0 or idx == total:
                try:
                    await status.edit(
                        f"<b>📤 Gʙʀᴏᴀᴅᴄᴀsᴛ ᴄʜᴀʟ ʀᴀʜᴀ ʜᴀɪ...</b>\n"
                        f"Total: {total} | Done: {idx}/{total}\n✅ {success}  ❌ {failed}"
                    )
                except Exception:
                    pass

            await asyncio.sleep(BROADCAST_ACTION_DELAY)

        # Sirf latest gbroadcast ka record rakhte hain — /cbroadcast isi ko use karega.
        await Seishiro.save_last_broadcast(entries)

        await status.edit(
            f"<b>✅ Gʙʀᴏᴀᴅᴄᴀsᴛ ᴄᴏᴍᴘʟᴇᴛᴇ!</b>\n"
            f"Total channels: {total}\n✅ Sent: {success}  ❌ Failed: {failed}\n\n"
            f"Isᴇ ᴅᴇʟᴇᴛᴇ ᴋᴀʀɴᴇ ᴋᴇ ʟɪʏᴇ /cbroadcast ᴜsᴇ ᴋᴀʀᴏ."
        )
    except Exception as e:
        logger.error(f"gbroadcast_cmd fatal: {e}")
        await message.reply_text(f"<b>❌ Eʀʀᴏʀ: {e}</b>")


# ─────────────────────────────────────────────
# /cbroadcast — pichhle /gbroadcast ko sabhi channels se delete karo
# ─────────────────────────────────────────────
@Bot.on_message(filters.command("cbroadcast") & filters.private & is_owner_or_admin)
async def cbroadcast_cmd(client: Client, message: Message):
    try:
        record = await Seishiro.get_last_broadcast()
        entries = record.get("entries") if record else None

        if not entries:
            await message.reply_text(
                "<b>❌ Delete karne ke liye koi pichla /gbroadcast nahi mila.</b>"
            )
            return

        total = len(entries)
        status = await message.reply_text(
            f"<b>🗑 Cʙʀᴏᴀᴅᴄᴀsᴛ sʜᴜʀᴜ...</b>\nTotal messages: {total}\nDone: 0/{total}"
        )

        success = failed = 0
        for idx, entry in enumerate(entries, 1):
            channel_id = entry.get("channel_id")
            msg_id = entry.get("message_id")
            try:
                await client.delete_messages(channel_id, msg_id)
                success += 1
            except FloodWait as fw:
                await asyncio.sleep(fw.value)
                try:
                    await client.delete_messages(channel_id, msg_id)
                    success += 1
                except Exception as e:
                    logger.error(f"cbroadcast retry failed for {channel_id}: {e}")
                    failed += 1
            except RPCError as e:
                logger.error(f"cbroadcast error in {channel_id}: {e}")
                failed += 1
            except Exception as e:
                logger.error(f"cbroadcast unexpected error in {channel_id}: {e}")
                failed += 1

            if idx % 5 == 0 or idx == total:
                try:
                    await status.edit(
                        f"<b>🗑 Cʙʀᴏᴀᴅᴄᴀsᴛ ᴄʜᴀʟ ʀᴀʜᴀ ʜᴀɪ...</b>\n"
                        f"Total: {total} | Done: {idx}/{total}\n✅ {success}  ❌ {failed}"
                    )
                except Exception:
                    pass

            await asyncio.sleep(BROADCAST_ACTION_DELAY)

        await Seishiro.clear_last_broadcast()

        await status.edit(
            f"<b>✅ Cʙʀᴏᴀᴅᴄᴀsᴛ ᴄᴏᴍᴘʟᴇᴛᴇ!</b>\n"
            f"Total: {total}\n✅ Deleted: {success}  ❌ Failed: {failed}"
        )
    except Exception as e:
        logger.error(f"cbroadcast_cmd fatal: {e}")
        await message.reply_text(f"<b>❌ Eʀʀᴏʀ: {e}</b>")


# ─────────────────────────────────────────────
# /gdescription — sabhi channels ka description set karo (purana overwrite hoga)
# ─────────────────────────────────────────────
@Bot.on_message(filters.command("gdescription") & filters.private & is_owner_or_admin)
async def gdescription_cmd(client: Client, message: Message):
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            await message.reply_text(
                "<b>Usᴇ: /gdescription your text here</b>\n\n"
                "Isse bot jitne channels mein admin hai un SABHI ka description "
                "ye text set ho jayega (jo pehle se likha hai wo overwrite ho jayega)."
            )
            return

        new_desc = parts[1].strip()
        if len(new_desc) > 255:
            await message.reply_text(
                f"<b>❌ Description 255 characters se zyada nahi ho sakta "
                f"(abhi {len(new_desc)} hai). Telegram ki limit hai.</b>"
            )
            return

        channels = await _get_target_channels(message)
        if channels is None:
            return

        total = len(channels)
        status = await message.reply_text(
            f"<b>📝 Gᴅᴇsᴄʀɪᴘᴛɪᴏɴ sʜᴜʀᴜ...</b>\nTotal channels: {total}\nDone: 0/{total}"
        )

        success = failed = 0
        for idx, channel_id in enumerate(channels, 1):
            try:
                await client.set_chat_description(channel_id, new_desc)
                success += 1
            except FloodWait as fw:
                await asyncio.sleep(fw.value)
                try:
                    await client.set_chat_description(channel_id, new_desc)
                    success += 1
                except Exception as e:
                    logger.error(f"gdescription retry failed for {channel_id}: {e}")
                    failed += 1
            except RPCError as e:
                logger.error(f"gdescription error in {channel_id}: {e}")
                failed += 1
            except Exception as e:
                logger.error(f"gdescription unexpected error in {channel_id}: {e}")
                failed += 1

            if idx % 5 == 0 or idx == total:
                try:
                    await status.edit(
                        f"<b>📝 Gᴅᴇsᴄʀɪᴘᴛɪᴏɴ ᴄʜᴀʟ ʀᴀʜᴀ ʜᴀɪ...</b>\n"
                        f"Total: {total} | Done: {idx}/{total}\n✅ {success}  ❌ {failed}"
                    )
                except Exception:
                    pass

            await asyncio.sleep(DESCRIPTION_ACTION_DELAY)

        await status.edit(
            f"<b>✅ Gᴅᴇsᴄʀɪᴘᴛɪᴏɴ ᴄᴏᴍᴘʟᴇᴛᴇ!</b>\n"
            f"Total channels: {total}\n✅ Success: {success}  ❌ Failed: {failed}"
        )
    except Exception as e:
        logger.error(f"gdescription_cmd fatal: {e}")
        await message.reply_text(f"<b>❌ Eʀʀᴏʀ: {e}</b>")


# ─────────────────────────────────────────────
# /cdescription — sabhi channels ka description clear (khaali) karo
# ─────────────────────────────────────────────
@Bot.on_message(filters.command("cdescription") & filters.private & is_owner_or_admin)
async def cdescription_cmd(client: Client, message: Message):
    try:
        channels = await _get_target_channels(message)
        if channels is None:
            return

        total = len(channels)
        status = await message.reply_text(
            f"<b>🧹 Cᴅᴇsᴄʀɪᴘᴛɪᴏɴ sʜᴜʀᴜ...</b>\nTotal channels: {total}\nDone: 0/{total}"
        )

        success = failed = 0
        for idx, channel_id in enumerate(channels, 1):
            try:
                await client.set_chat_description(channel_id, "")
                success += 1
            except FloodWait as fw:
                await asyncio.sleep(fw.value)
                try:
                    await client.set_chat_description(channel_id, "")
                    success += 1
                except Exception as e:
                    logger.error(f"cdescription retry failed for {channel_id}: {e}")
                    failed += 1
            except RPCError as e:
                logger.error(f"cdescription error in {channel_id}: {e}")
                failed += 1
            except Exception as e:
                logger.error(f"cdescription unexpected error in {channel_id}: {e}")
                failed += 1

            if idx % 5 == 0 or idx == total:
                try:
                    await status.edit(
                        f"<b>🧹 Cᴅᴇsᴄʀɪᴘᴛɪᴏɴ ᴄʜᴀʟ ʀᴀʜᴀ ʜᴀɪ...</b>\n"
                        f"Total: {total} | Done: {idx}/{total}\n✅ {success}  ❌ {failed}"
                    )
                except Exception:
                    pass

            await asyncio.sleep(DESCRIPTION_ACTION_DELAY)

        await status.edit(
            f"<b>✅ Cᴅᴇsᴄʀɪᴘᴛɪᴏɴ ᴄᴏᴍᴘʟᴇᴛᴇ!</b>\n"
            f"Total channels: {total}\n✅ Cleared: {success}  ❌ Failed: {failed}"
        )
    except Exception as e:
        logger.error(f"cdescription_cmd fatal: {e}")
        await message.reply_text(f"<b>❌ Eʀʀᴏʀ: {e}</b>")
