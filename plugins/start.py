import asyncio
import base64
import time
import logging
from collections import defaultdict
from asyncio import Lock
from functools import wraps

from pyrogram import Client, filters
from pyrogram.enums import ParseMode, ChatMemberStatus, ChatAction
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, InputMediaPhoto
)
from pyrogram.errors import (
    FloodWait, InputUserDeactivated, UserIsBlocked,
    PeerIdInvalid, RPCError
)
from pyrogram.errors.exceptions.bad_request_400 import UserNotParticipant

from bot import Bot, _force_resolve_peer, check_bot_permissions
from datetime import datetime, timedelta
from config import *
from database.database import Seishiro
from plugins.settings import revoke_invite_after_5_minutes
from plugins.premium import get_invite_link_with_ads
from helper_func import *

logger = logging.getLogger(__name__)

# Peer cache — baar baar get_chat() na ho
chat_data_cache = {}

# Per-channel lock — ek waqt mein sirf ek invite link bane
channel_locks = defaultdict(Lock)


# ═══════════════════════════════════════════
# ADMIN FILTER
# ═══════════════════════════════════════════

async def check_admin(filter, client, message):
    try:
        uid = message.from_user.id
        return uid == OWNER_ID or await Seishiro.is_admin(uid)
    except Exception as e:
        logger.error(f"check_admin error: {e}")
        return False

admin = filters.create(check_admin)


# ═══════════════════════════════════════════
# FORCE SUBSCRIBE DECORATOR
# ═══════════════════════════════════════════

def check_fsub(func):
    @wraps(func)
    async def wrapper(client, message, *args, **kwargs):
        user_id = message.from_user.id

        async def is_sub(client, user_id, channel_id):
            try:
                member    = await client.get_chat_member(channel_id, user_id)
                is_member = member.status in {
                    ChatMemberStatus.OWNER,
                    ChatMemberStatus.ADMINISTRATOR,
                    ChatMemberStatus.MEMBER
                }
                if is_member:
                    try:
                        if await Seishiro.req_user_exist(channel_id, user_id):
                            await Seishiro.del_req_user(channel_id, user_id)
                    except Exception:
                        pass
                return is_member
            except UserNotParticipant:
                mode = await Seishiro.get_channel_mode(channel_id)
                if mode == "on":
                    return await Seishiro.req_user_exist(channel_id, user_id)
                return False
            except Exception as e:
                logger.error(f"is_sub error: {e}")
                return False

        async def is_subscribed(client, user_id):
            channels = await Seishiro.get_fsub_channels()
            if not channels:
                return True
            if user_id == OWNER_ID:
                return True
            # Premium users FSub bypass karte hain
            if await Seishiro.has_premium_access(user_id):
                logger.info(f"User {user_id} is premium — FSub bypassed")
                return True
            for cid in channels:
                if not await is_sub(client, user_id, cid):
                    mode = await Seishiro.get_channel_mode(cid)
                    if mode == "on":
                        await asyncio.sleep(2)
                        if await is_sub(client, user_id, cid):
                            continue
                    return False
            return True

        try:
            if not await is_subscribed(client, user_id):
                return await not_joined(client, message)
            return await func(client, message, *args, **kwargs)
        except Exception as e:
            logger.error(f"check_fsub error: {e}")
            await message.reply_text("An unexpected error occurred. Please contact the developer.")
    return wrapper


# ═══════════════════════════════════════════
# NOT JOINED — FSub channels dikhao
# ═══════════════════════════════════════════

async def not_joined(client: Client, message: Message):
    user_id = message.from_user.id
    temp    = await message.reply("<b><i>ᴡᴀɪᴛ ᴀ sᴇᴄ..</i></b>")
    if not temp:
        return

    buttons = []
    count   = 0

    try:
        all_channels = await Seishiro.get_fsub_channels()

        # Fake link button sabse pehle (agar set hai)
        if all_channels:
            fake = await Seishiro.get_fake_link()
            if fake:
                buttons.append([InlineKeyboardButton(
                    text=fake["button_text"], url=fake["url"]
                )])

        for chat_id in all_channels:
            await message.reply_chat_action(ChatAction.TYPING)

            is_member = False
            try:
                member    = await client.get_chat_member(chat_id, user_id)
                is_member = member.status in {
                    ChatMemberStatus.OWNER,
                    ChatMemberStatus.ADMINISTRATOR,
                    ChatMemberStatus.MEMBER
                }
            except UserNotParticipant:
                is_member = False
            except Exception as e:
                logger.error(f"Member check error {chat_id}: {e}")

            if is_member:
                continue

            try:
                if chat_id in chat_data_cache:
                    data = chat_data_cache[chat_id]
                else:
                    try:
                        data = await client.get_chat(chat_id)
                        chat_data_cache[chat_id] = data
                    except PeerIdInvalid:
                        logger.warning(f"PeerIdInvalid {chat_id} — deep resolve...")
                        if not await _force_resolve_peer(client, chat_id):
                            logger.error(f"Deep resolve failed {chat_id} — skip")
                            continue
                        try:
                            data = await client.get_chat(chat_id)
                            chat_data_cache[chat_id] = data
                        except Exception as e2:
                            logger.error(f"get_chat after resolve failed {chat_id}: {e2}")
                            continue
                    except Exception as e:
                        logger.error(f"get_chat error {chat_id}: {e}")
                        continue

                name = data.title
                mode = await Seishiro.get_channel_mode(chat_id)

                if mode == "on" and not data.username:
                    invite = await client.create_chat_invite_link(
                        chat_id=chat_id,
                        creates_join_request=True,
                        expire_date=datetime.utcnow() + timedelta(seconds=FSUB_LINK_EXPIRY) if FSUB_LINK_EXPIRY else None
                    )
                    link = invite.invite_link
                elif data.username:
                    link = f"https://t.me/{data.username}"
                else:
                    invite = await client.create_chat_invite_link(
                        chat_id=chat_id,
                        expire_date=datetime.utcnow() + timedelta(seconds=FSUB_LINK_EXPIRY) if FSUB_LINK_EXPIRY else None
                    )
                    link = invite.invite_link

                buttons.append([InlineKeyboardButton(text=name, url=link)])
                count += 1
                try:
                    await temp.edit(f"<b>{'! ' * count}</b>")
                except Exception:
                    pass

            except Exception as e:
                logger.error(f"FSub button error {chat_id}: {e}")
                continue

        # Joined button
        try:
            buttons.append([InlineKeyboardButton(
                text='• Jᴏɪɴᴇᴅ •',
                url=f"https://t.me/{BOT_USERNAME}?start={message.command[1]}"
            )])
        except (IndexError, AttributeError):
            pass

        if not buttons:
            return await temp.edit(
                "<b><i>! No valid channels found. Contact @suhanibots</i></b>"
            )

        try:
            await temp.delete()
        except Exception:
            pass

        await message.reply_photo(
            photo=FSUB_PIC,
            caption=(
                "<b>Welcome! 😁\n\n"
                "<blockquote>Links pane ke liye niche diye gaye "
                "channels join karein ya request karein.</blockquote></b>"
            ),
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    except Exception as e:
        logger.error(f"not_joined error: {e}")
        try:
            await temp.edit(
                f"<b><i>Error! Contact @suhanibots</i></b>\n"
                f"<blockquote expandable><b>Reason:</b> {e}</blockquote>"
            )
        except Exception:
            pass


# ═══════════════════════════════════════════
# /start COMMAND
# ═══════════════════════════════════════════

@Bot.on_message(filters.command('start') & filters.private)
@check_fsub
async def start_command(client: Bot, message: Message):
    user_id = message.from_user.id

    # Ban check
    if await Seishiro.is_user_banned(user_id):
        return await message.reply_text(
            "🚫 Yᴏᴜ ᴀʀᴇ ʙᴀɴɴᴇᴅ! Contact: @suhanibots",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Cᴏɴᴛᴀᴄᴛ", url="https://t.me/suhanibots")
            ]])
        )

    # User save karo
    await Seishiro.add_user(user_id, message)

    try:
        text = message.text

        # ── Deep link ─────────────────────────────────────────────────
        if len(text) > 7:
            try:
                base64_string = text.split(" ", 1)[1]
                is_request    = base64_string.startswith("req_")

                # Decode
                try:
                    base64_to_decode = base64_string[4:] if is_request else base64_string
                    decoded_string   = await decode(base64_to_decode)
                    channel_id       = int(decoded_string)
                    logger.info(f"Deep link: channel_id={channel_id}, req={is_request}")
                except Exception as e:
                    logger.error(f"Decode failed '{base64_string}': {e}")
                    return await message.reply_text(
                        "<b><blockquote expandable>Invalid or expired invite link.</blockquote></b>"
                    )

                if not channel_id or channel_id > 0:
                    return await message.reply_text(
                        "<b><blockquote expandable>Invalid or expired invite link.</blockquote></b>"
                    )

                # Channel DB mein save karo agar nahi hai
                if not await Seishiro.channel_data.find_one({"channel_id": channel_id}):
                    await Seishiro.save_channel(channel_id)

                # ── STEP 1: Peer Resolution ────────────────────────────
                try:
                    chat = await client.get_chat(channel_id)
                    logger.info(f"Peer OK: {channel_id} → {chat.title}")
                except PeerIdInvalid:
                    logger.warning(f"PeerIdInvalid {channel_id} — deep resolve...")
                    if not await _force_resolve_peer(client, channel_id):
                        return await message.reply_text(
                            "<b><blockquote expandable>"
                            "⚠️ Channel resolve nahi hua.\n\n"
                            "Bot ko is channel mein admin banao aur dobara try karo."
                            "</blockquote></b>"
                        )
                    logger.info(f"Deep resolve OK: {channel_id}")
                except Exception as e:
                    logger.error(f"get_chat failed {channel_id}: {e}")
                    return await message.reply_text(
                        f"<b><blockquote expandable>Channel access error: {str(e)[:80]}</blockquote></b>"
                    )

                # ── STEP 2: Admin + Permission Check ──────────────────
                is_admin_ch, can_invite, reason = await check_bot_permissions(client, channel_id)

                if not is_admin_ch:
                    return await message.reply_text(
                        f"<b><blockquote expandable>"
                        f"⚠️ Bot is channel mein admin nahi hai.\n\nKaaran: {reason}"
                        f"</blockquote></b>"
                    )

                if not can_invite:
                    return await message.reply_text(
                        "<b><blockquote expandable>"
                        "⚠️ Bot admin hai lekin 'Invite Users' permission nahi hai.\n\n"
                        "Channel settings mein yeh permission do."
                        "</blockquote></b>"
                    )

                # ── STEP 3: Encoded link save karo ────────────────────
                if is_request:
                    await Seishiro.save_encoded_link2(channel_id, base64_to_decode)
                else:
                    await Seishiro.save_encoded_link(channel_id)

                # Original link check
                original_link = await Seishiro.get_original_link(channel_id)
                if original_link:
                    return await message.reply_text(
                        "<b><blockquote expandable>Your channel link 👇</blockquote></b>",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("• ᴄʟɪᴄᴋ ʜᴇʀᴇ •", url=original_link)
                        ]])
                    )

                # ── STEP 4: Invite Link Create / Reuse ────────────────
                async with channel_locks[channel_id]:
                    invite_link     = None
                    is_request_link = is_request
                    current_time    = datetime.now()

                    old = await Seishiro.get_current_invite_link(channel_id)
                    if old:
                        ch_doc     = await Seishiro.channel_data.find_one({"channel_id": channel_id})
                        created_at = ch_doc.get("invite_link_created_at") if ch_doc else None
                        if created_at and (current_time - created_at).total_seconds() < 240:
                            invite_link     = old["invite_link"]
                            is_request_link = old["is_request"]
                            logger.info(f"Reusing link {channel_id}")
                        else:
                            try:
                                await client.revoke_chat_invite_link(channel_id, old["invite_link"])
                            except Exception as e:
                                logger.warning(f"Revoke failed: {e}")

                    if not invite_link:
                        try:
                            inv = await client.create_chat_invite_link(
                                chat_id=channel_id,
                                expire_date=datetime.now() + timedelta(minutes=5),
                                creates_join_request=is_request
                            )
                            invite_link = inv.invite_link
                            await Seishiro.save_invite_link(channel_id, invite_link, is_request_link)
                            logger.info(f"New link created {channel_id}")
                        except Exception as e:
                            logger.error(f"create_chat_invite_link failed {channel_id}: {e}")
                            return await message.reply_text(
                                f"<b><blockquote expandable>"
                                f"Invite link banane mein error.\nKaaran: {str(e)[:100]}"
                                f"</blockquote></b>"
                            )

                    # ── STEP 5: Shortener (ads → earnings) ────────────
                    # Premium user → direct link (no ads)
                    # Free user   → shortener link (ads dikhenge → paisa milega)
                    display_link = await get_invite_link_with_ads(
                        client, user_id, invite_link
                    )
                    logger.info(
                        f"Link user {user_id}: "
                        f"{'direct/premium' if display_link == invite_link else 'shortened/free'}"
                    )

                    button = InlineKeyboardMarkup([[
                        InlineKeyboardButton("• ᴄʟɪᴄᴋ ʜᴇʀᴇ •", url=display_link)
                    ]])

                    wait_msg = await message.reply_text("<b><i>ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ...</i></b>")
                    await asyncio.sleep(0.5)
                    await wait_msg.delete()

                    link_msg = await message.reply_text(
                        "<b><blockquote expandable>"
                        "ʜᴇʀᴇ ɪs ʏᴏᴜʀ ʟɪɴᴋ! ᴄʟɪᴄᴋ ʙᴇʟᴏᴡ ᴛᴏ ᴘʀᴏᴄᴇᴇᴅ"
                        "</blockquote></b>",
                        reply_markup=button
                    )

                    note_msg = await message.reply_text(
                        "<b>⚠️ Warning ⚠️</b>\n\n"
                        "<blockquote><b><i>Yeh message aur link kuch minutes mein "
                        "auto-delete ho jayega. Agar link expire ho jaaye toh dobara try karein.</i></b></blockquote>"
                    )

                    asyncio.create_task(delete_after_delay(note_msg, 300))
                    asyncio.create_task(delete_after_delay(link_msg, 300))
                    asyncio.create_task(revoke_invite_after_5_minutes(
                        client, channel_id, invite_link, is_request
                    ))

            except Exception as e:
                logger.error(f"Deep link error: {e}", exc_info=True)
                await message.reply_text(
                    "<b><blockquote expandable>Invalid or expired invite link.</blockquote></b>"
                )

        # ── Normal /start (no deep link) ──────────────────────────────
        else:
            is_admin = (user_id == OWNER_ID) or await Seishiro.is_admin(user_id)

            if is_admin:
                inline_buttons = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("• ᴀʙᴏᴜᴛ", callback_data="about"),
                        InlineKeyboardButton("Hᴇʟᴘ •", callback_data="help")
                    ],
                    [InlineKeyboardButton("⚙️ Sᴇᴛᴛɪɴɢs", callback_data="settings_main")],
                    [InlineKeyboardButton("💎 Pʀᴇᴍɪᴜᴍ", callback_data="prem_plans")],
                ])
            else:
                inline_buttons = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("• ᴀʙᴏᴜᴛ", callback_data="about"),
                        InlineKeyboardButton("Hᴇʟᴘ •", callback_data="help")
                    ],
                    [InlineKeyboardButton("💎 Pʀᴇᴍɪᴜᴍ", callback_data="prem_plans")],
                ])

            caption = START_MSG.format(
                first=message.from_user.first_name,
                last=message.from_user.last_name or "",
                username="@" + message.from_user.username if message.from_user.username else "N/A",
                mention=message.from_user.mention,
                id=message.from_user.id
            )

            try:
                await message.reply_photo(
                    photo=START_PIC,
                    caption=caption,
                    reply_markup=inline_buttons
                )
            except Exception as e:
                logger.warning(f"Photo failed: {e}")
                await message.reply_text(caption, reply_markup=inline_buttons)

    except Exception as e:
        logger.error(f"FATAL start_command: {e}", exc_info=True)
        await message.reply_text(
            "<b>An unexpected error occurred. Please try again later.</b>\n\n"
            "<blockquote>If this persists, contact support.</blockquote>"
        )


# ═══════════════════════════════════════════
# BROADCAST
# ═══════════════════════════════════════════

@Bot.on_message(filters.command("broadcast") & filters.private & admin)
async def broadcast_handler(bot: Client, m: Message):
    try:
        if not m.reply_to_message:
            return await m.reply_text(
                "<b>⚠️ Reply to a message and use /broadcast</b>"
            )

        try:
            all_users = await Seishiro.get_all_users()
        except Exception as e:
            return await m.reply_text(f"<b>❌ Error fetching users: {e}</b>")

        broadcast_msg = m.reply_to_message
        sts_msg       = await m.reply_text("📤 Broadcast started...")

        done = failed = success = 0
        start_time = time.time()

        try:
            total_users = await Seishiro.total_users_count()
        except Exception:
            total_users = 0

        try:
            async for user in all_users:
                try:
                    sts = await send_msg(user['_id'], broadcast_msg)
                    if sts == 200:
                        success += 1
                    else:
                        failed += 1
                    if sts == 400:
                        try:
                            await Seishiro.delete_user(user['_id'])
                        except Exception:
                            pass
                    done += 1

                    if done % 20 == 0:
                        try:
                            await sts_msg.edit(
                                f"📤 Broadcast in progress...\n\n"
                                f"Total: {total_users}\n"
                                f"Done: {done}/{total_users}\n"
                                f"✅ Success: {success}  ❌ Failed: {failed}"
                            )
                        except FloodWait as fw:
                            await asyncio.sleep(fw.value)
                        except Exception:
                            pass

                except Exception as e:
                    logger.error(f"Broadcast user {user.get('_id')} error: {e}")
                    failed += 1
                    done   += 1
                    continue

            completed_in = timedelta(seconds=int(time.time() - start_time))
            try:
                await sts_msg.edit(
                    f"✅ Broadcast Complete!\n\n"
                    f"Time: {completed_in}\n"
                    f"Total: {total_users} | Done: {done}\n"
                    f"✅ Success: {success}  ❌ Failed: {failed}"
                )
            except Exception:
                await m.reply_text(
                    f"✅ Broadcast done. Success: {success}, Failed: {failed}"
                )

        except Exception as e:
            logger.error(f"Broadcast loop error: {e}")
            try:
                await sts_msg.edit(
                    f"<b>❌ Broadcast Failed!</b>\n\n"
                    f"Done: {done} | ✅ {success} | ❌ {failed}\n\n"
                    f"<blockquote expandable>Error: {e}</blockquote>"
                )
            except Exception:
                pass

    except Exception as e:
        logger.error(f"broadcast_handler fatal: {e}")
        await m.reply_text(f"<b>❌ Error: {e}</b>")


# ═══════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════

async def send_msg(user_id, message):
    try:
        await message.copy(chat_id=int(user_id))
        return 200
    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await send_msg(user_id, message)
    except InputUserDeactivated:
        return 400
    except UserIsBlocked:
        return 400
    except PeerIdInvalid:
        return 400
    except RPCError as e:
        logger.error(f"RPC error {user_id}: {e}")
        return 500
    except Exception as e:
        logger.error(f"send_msg error {user_id}: {e}")
        return 500


async def delete_after_delay(msg, delay: int):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except Exception:
        pass
