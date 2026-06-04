import asyncio
import secrets
import time
import logging
from collections import defaultdict
from asyncio import Lock
from functools import wraps

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ChatAction
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from pyrogram.errors import (
    FloodWait, InputUserDeactivated, UserIsBlocked, PeerIdInvalid, RPCError
)
from pyrogram.errors.exceptions.bad_request_400 import UserNotParticipant

from bot import Bot, _force_resolve_peer, check_bot_permissions
from datetime import datetime, timedelta
from config import *
from database.database import Seishiro
from plugins.settings import revoke_invite_after_5_minutes
from plugins.premium import shorten_link, _get_bot_config
from helper_func import *
from plugins.tutorial import send_fsub_tutorial_if_not_joined, send_linkshortner_tutorial_if_not_verified

logger = logging.getLogger(__name__)

# ── TTL Chat Cache (10 minute) ────────────────────────────────────────────────
# Ek hi channel ko baar baar GetFullChannel se fetch karne pe FloodWait aata hai.
# Cache mein rakhne se Telegram API calls drastically kam ho jaate hain.
_CHAT_CACHE: dict[int, tuple] = {}   # {channel_id: (chat_object, timestamp)}
_CHAT_CACHE_TTL = 600                # 10 minute

def _get_cached_chat(cid: int):
    entry = _CHAT_CACHE.get(cid)
    if entry:
        obj, ts = entry
        if (datetime.now() - ts).total_seconds() < _CHAT_CACHE_TTL:
            return obj
    return None

def _set_cached_chat(cid: int, obj):
    _CHAT_CACHE[cid] = (obj, datetime.now())


async def _safe_get_chat(client, cid: int, retries: int = 3):
    """
    get_chat ka flood-safe wrapper.
    FloodWait aaye toh wait karke retry karo (max 3 baar).
    Cache se milega toh Telegram call hi nahi hoga.
    """
    cached = _get_cached_chat(cid)
    if cached:
        return cached

    for attempt in range(retries):
        try:
            data = await client.get_chat(cid)
            _set_cached_chat(cid, data)
            return data
        except FloodWait as fw:
            wait = fw.value + 2
            logger.warning(f"FloodWait {wait}s on get_chat({cid}), attempt {attempt+1}/{retries}")
            await asyncio.sleep(wait)
        except PeerIdInvalid:
            raise
        except Exception as e:
            logger.error(f"get_chat({cid}) error: {e}")
            raise
    raise Exception(f"get_chat({cid}) failed after {retries} retries (FloodWait)")


async def _safe_get_member(client, cid: int, uid: int, retries: int = 3):
    """
    get_chat_member ka flood-safe wrapper.
    FloodWait aaye toh wait karke retry karo.
    """
    for attempt in range(retries):
        try:
            return await client.get_chat_member(cid, uid)
        except FloodWait as fw:
            wait = fw.value + 2
            logger.warning(f"FloodWait {wait}s on get_chat_member({cid},{uid}), attempt {attempt+1}/{retries}")
            await asyncio.sleep(wait)
        except Exception:
            raise
    raise Exception(f"get_chat_member({cid},{uid}) failed after {retries} retries (FloodWait)")


# Legacy dict — kuch jagah directly use hota tha, ab _safe_get_chat use karo
chat_data_cache = {}
channel_locks   = defaultdict(Lock)

# ═══════════════════════════════════════════
# ADMIN FILTER
# ═══════════════════════════════════════════

async def _is_admin(user_id: int) -> bool:
    return user_id == OWNER_ID or await Seishiro.is_admin(user_id)

async def check_admin(filter, client, message):
    try:
        return await _is_admin(message.from_user.id)
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
        uid = message.from_user.id

        async def is_sub(uid, cid):
            try:
                m = await _safe_get_member(client, cid, uid)
                ok = m.status in {
                    ChatMemberStatus.OWNER,
                    ChatMemberStatus.ADMINISTRATOR,
                    ChatMemberStatus.MEMBER
                }
                if ok:
                    try:
                        if await Seishiro.req_user_exist(cid, uid):
                            await Seishiro.del_req_user(cid, uid)
                    except Exception:
                        pass
                return ok
            except UserNotParticipant:
                if await Seishiro.get_channel_mode(cid) == "on":
                    return await Seishiro.req_user_exist(cid, uid)
                return False
            except Exception as e:
                logger.error(f"is_sub error: {e}")
                return False

        async def is_subscribed(uid):
            channels = await Seishiro.get_fsub_channels()
            if not channels or uid == OWNER_ID:
                return True
            # Premium users FSub bypass karte hain
            if await Seishiro.has_premium_access(uid):
                logger.info(f"User {uid} premium — FSub bypassed")
                return True
            # ── PARALLEL CHECK (fast) ─────────────────────────────────
            # Sab channels simultaneously check karo — ek ke baad ek nahi
            results = await asyncio.gather(*[is_sub(uid, cid) for cid in channels], return_exceptions=True)
            for cid, res in zip(channels, results):
                # Exception aa gayi toh False maano
                sub_ok = res if isinstance(res, bool) else False
                if not sub_ok:
                    if await Seishiro.get_channel_mode(cid) == "on":
                        # Request mode: ek baar aur check karo (no sleep)
                        sub_ok = await is_sub(uid, cid)
                        if sub_ok:
                            continue
                    return False
            return True

        try:
            if not await is_subscribed(uid):
                return await not_joined(client, message)
            return await func(client, message, *args, **kwargs)
        except Exception as e:
            logger.error(f"check_fsub error: {e}")
            await message.reply_text("An unexpected error occurred. Please contact the developer.")
    return wrapper


# ═══════════════════════════════════════════
# NOT JOINED
# ═══════════════════════════════════════════

async def not_joined(client: Client, message: Message):
    uid  = message.from_user.id
    temp = await message.reply("<b><i>ᴡᴀɪᴛ ᴀ sᴇᴄ..</i></b>")
    if not temp:
        return

    buttons = []
    count   = 0

    try:
        channels = await Seishiro.get_fsub_channels()

        # Fake link sabse pehle
        if channels:
            fake = await Seishiro.get_fake_link()
            if fake:
                buttons.append([InlineKeyboardButton(text=fake["button_text"], url=fake["url"])])

        for cid in channels:
            await message.reply_chat_action(ChatAction.TYPING)

            is_member = False
            try:
                m         = await _safe_get_member(client, cid, uid)
                is_member = m.status in {
                    ChatMemberStatus.OWNER,
                    ChatMemberStatus.ADMINISTRATOR,
                    ChatMemberStatus.MEMBER
                }
            except UserNotParticipant:
                pass
            except Exception as e:
                logger.error(f"Member check {cid}: {e}")

            if is_member:
                continue

            try:
                if cid in chat_data_cache:
                    data = chat_data_cache[cid]
                else:
                    try:
                        data = await _safe_get_chat(client, cid)
                        chat_data_cache[cid] = data
                    except PeerIdInvalid:
                        if not await _force_resolve_peer(client, cid):
                            continue
                        data = await _safe_get_chat(client, cid)
                        chat_data_cache[cid] = data

                mode = await Seishiro.get_channel_mode(cid)
                if mode == "on" and not data.username:
                    inv  = await client.create_chat_invite_link(
                        chat_id=cid, creates_join_request=True,
                        expire_date=datetime.utcnow() + timedelta(seconds=FSUB_LINK_EXPIRY) if FSUB_LINK_EXPIRY else None
                    )
                    link = inv.invite_link
                elif data.username:
                    link = f"https://t.me/{data.username}"
                else:
                    inv  = await client.create_chat_invite_link(
                        chat_id=cid,
                        expire_date=datetime.utcnow() + timedelta(seconds=FSUB_LINK_EXPIRY) if FSUB_LINK_EXPIRY else None
                    )
                    link = inv.invite_link

                # Custom name check — agar set hai toh wahi use karo, warna channel title
                custom_name = await Seishiro.get_fsub_channel_name(cid)
                btn_text = custom_name if custom_name else data.title
                buttons.append([InlineKeyboardButton(text=btn_text, url=link)])
                count += 1
                try:
                    await temp.edit(f"<b>{'! ' * count}</b>")
                except Exception:
                    pass

            except Exception as e:
                logger.error(f"FSub button error {cid}: {e}")
                continue

        try:
            buttons.append([InlineKeyboardButton(
                text='• Jᴏɪɴᴇᴅ •',
                url=f"https://t.me/{BOT_USERNAME}?start={message.command[1]}"
            )])
        except (IndexError, AttributeError):
            pass

        if not buttons:
            return await temp.edit("<b><i>No valid channels found. Contact @suhanibots</i></b>")

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

        # ── FSub Tutorial: 30s baad check, join nahi kiya toh video ──
        async def _check_joined_all(check_uid: int) -> bool:
            try:
                chs = await Seishiro.get_fsub_channels()
                for cid in chs:
                    try:
                        m = await _safe_get_member(client, cid, check_uid)
                        if m.status not in {
                            ChatMemberStatus.OWNER,
                            ChatMemberStatus.ADMINISTRATOR,
                            ChatMemberStatus.MEMBER,
                        }:
                            return False
                    except Exception:
                        if await Seishiro.get_channel_mode(cid) == "on":
                            if not await Seishiro.req_user_exist(cid, check_uid):
                                return False
                        else:
                            return False
                return True
            except Exception:
                return False

        asyncio.create_task(
            send_fsub_tutorial_if_not_joined(client, uid, _check_joined_all)
        )

    except Exception as e:
        logger.error(f"not_joined error: {e}")
        try:
            await temp.edit(f"<b><i>Error! Contact @suhanibots</i></b>\n<blockquote expandable>{e}</blockquote>")
        except Exception:
            pass


# ═══════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════

async def _resolve_peer_safe(client: Bot, channel_id: int) -> bool:
    """Peer resolve karo — PeerIdInvalid pe deep resolve, FloodWait pe retry."""
    try:
        await _safe_get_chat(client, channel_id)
        return True
    except PeerIdInvalid:
        return await _force_resolve_peer(client, channel_id)
    except Exception:
        return True  # Other errors — channel exist karta hai


async def _get_fresh_invite_link(client: Bot, channel_id: int, is_request: bool) -> str | None:
    """
    Fresh invite link banao aur DB mein save karo.
    4 minute ke andar purana link reuse hoga.
    """
    async with channel_locks[channel_id]:
        old = await Seishiro.get_current_invite_link(channel_id)
        if old:
            ch  = await Seishiro.channel_data.find_one({"channel_id": channel_id})
            cat = ch.get("invite_link_created_at") if ch else None
            if cat and (datetime.now() - cat).total_seconds() < 240:
                return old["invite_link"]
            try:
                await client.revoke_chat_invite_link(channel_id, old["invite_link"])
            except Exception:
                pass

        try:
            for attempt in range(3):
                try:
                    inv  = await client.create_chat_invite_link(
                        chat_id=channel_id,
                        expire_date=datetime.now() + timedelta(minutes=5),
                        creates_join_request=is_request
                    )
                    await Seishiro.save_invite_link(channel_id, inv.invite_link, is_request)
                    return inv.invite_link
                except FloodWait as fw:
                    wait = fw.value + 2
                    logger.warning(f"FloodWait {wait}s on create_invite_link({channel_id}), attempt {attempt+1}/3")
                    await asyncio.sleep(wait)
            logger.error(f"create_invite_link({channel_id}) failed after 3 retries")
            return None
        except Exception as e:
            logger.error(f"create_invite_link failed {channel_id}: {e}")
            return None


async def _send_invite_msg(message: Message, invite_link: str):
    """Direct invite link bhejo (premium user ya shortener off)."""
    wait = await message.reply_text("<b><i>ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ...</i></b>")
    await asyncio.sleep(0.5)
    await wait.delete()

    link_msg = await message.reply_text(
        "<b><blockquote expandable>ʜᴇʀᴇ ɪs ʏᴏᴜʀ ʟɪɴᴋ! ᴄʟɪᴄᴋ ʙᴇʟᴏᴡ ᴛᴏ ᴘʀᴏᴄᴇᴇᴅ</blockquote></b>",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("• ᴄʟɪᴄᴋ ʜᴇʀᴇ •", url=invite_link)
        ]])
    )
    asyncio.create_task(delete_after_delay(link_msg, 300))
    return link_msg  # caller ke liye return karo taaki ID save ho sake


async def delete_after_delay(msg, delay: int):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except Exception:
        pass


# ═══════════════════════════════════════════
# VERIFY TOKEN HANDLER
# User shortener complete karke vfy_<token> ke
# saath bot pe aata hai
# ═══════════════════════════════════════════

async def _handle_verify_token(client: Bot, message: Message, uid: int, token: str):
    """
    Flow:
    1. Token DB mein dhundo
    2. Already used? → reject
    3. Dusre user ka token? → reject
    4. Temp premium do (setverifytime duration)
    5. Fresh invite link banao aur do
    6. Token mark used
    """
    doc = await Seishiro.get_verify_token(token)

    if not doc:
        return await message.reply_text(
            "<b><blockquote expandable>"
            "⚠️ Invalid ya expired verification link.\n\n"
            "Dobara try karo — original link pe click karo."
            "</blockquote></b>"
        )

    if doc.get("used"):
        return await message.reply_text(
            "<b><blockquote expandable>"
            "⚠️ Yeh link pehle use ho chuka hai.\n\n"
            "Dobara channel link pane ke liye original link pe click karo."
            "</blockquote></b>"
        )

    if doc.get("user_id") and doc["user_id"] != uid:
        return await message.reply_text(
            "<b><blockquote expandable>"
            "⚠️ Yeh link tumhare liye nahi hai."
            "</blockquote></b>"
        )

    channel_id = doc["channel_id"]
    is_request = doc.get("is_request", False)

    # Temp premium duration
    cfg     = await _get_bot_config()
    seconds = cfg.get("verify_premium_seconds", 86400)  # default 24h

    # Temp premium do
    await Seishiro.add_premium(uid, seconds)
    logger.info(f"Temp premium: user={uid}, seconds={seconds}, channel={channel_id}")

    # Peer resolve
    await _resolve_peer_safe(client, channel_id)

    # Fresh invite link
    invite_link = await _get_fresh_invite_link(client, channel_id, is_request)
    if not invite_link:
        return await message.reply_text(
            "<b><blockquote expandable>"
            "✅ Verified! Lekin invite link banane mein error.\n"
            "Dobara try karein."
            "</blockquote></b>"
        )

    # Token use mark karo
    await Seishiro.mark_token_used(token)

    hours = seconds // 3600
    mins  = (seconds % 3600) // 60
    dur   = f"{hours}h" if mins == 0 else f"{hours}h {mins}m"

    link_msg = await message.reply_text(
        f"✅ <b>Verified! Yeh raha aapka link:</b>\n\n"
        f"<blockquote>"
        f"⚡ Agle <b>{dur}</b> tak direct links milenge — koi ads nahi, koi FSub nahi!\n"
        f"Time khatam hone ke baad dobara shortener complete karna padega.\n\n"
        f"💎 Hamesha ads-free rehne ke liye <b>Premium</b> lo!"
        f"</blockquote>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("• ᴄʟɪᴄᴋ ʜᴇʀᴇ •", url=invite_link)],
            [InlineKeyboardButton("💎 Buy Premium", callback_data="prem_plans")],
        ])
    )

    # 5 min baad delete + revoke
    async def cleanup():
        await asyncio.sleep(300)
        try:
            await link_msg.delete()
        except Exception:
            pass
        try:
            await client.revoke_chat_invite_link(channel_id, invite_link)
        except Exception:
            pass

    asyncio.create_task(cleanup())


# ═══════════════════════════════════════════
# /start COMMAND
# ═══════════════════════════════════════════

@Bot.on_message(filters.command('start') & filters.private)
@check_fsub
async def start_command(client: Bot, message: Message):
    uid = message.from_user.id

    # Ban check
    if await Seishiro.is_user_banned(uid):
        return await message.reply_text(
            "🚫 Yᴏᴜ ᴀʀᴇ ʙᴀɴɴᴇᴅ!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Contact", url="https://t.me/suhanibots")
            ]])
        )

    await Seishiro.add_user(uid, message)

    try:
        text = message.text

        # ── Deep link ─────────────────────────────────────────────────
        if len(text) > 7:
            try:
                param = text.split(" ", 1)[1]

                # ── Verify token (shortener complete ke baad) ──────────
                if param.startswith("vfy_"):
                    return await _handle_verify_token(client, message, uid, param[4:])

                # ── Normal encoded channel link ────────────────────────
                is_request = param.startswith("req_")
                b64        = param[4:] if is_request else param

                try:
                    channel_id = int(await decode(b64))
                except Exception as e:
                    logger.error(f"Decode failed: {e}")
                    return await message.reply_text(
                        "<b><blockquote expandable>Invalid or expired invite link.</blockquote></b>"
                    )

                if not channel_id or channel_id > 0:
                    return await message.reply_text(
                        "<b><blockquote expandable>Invalid or expired invite link.</blockquote></b>"
                    )

                # ── Channel Alias Check ────────────────────────────────
                # Agar purana channel ban ho gaya aur alias set hai,
                # toh silently naye channel pe redirect karo
                alias_id = await Seishiro.get_channel_alias(channel_id)
                if alias_id:
                    logger.info(f"Alias redirect: {channel_id} → {alias_id}")
                    channel_id = alias_id

                # Channel DB mein save
                if not await Seishiro.channel_data.find_one({"channel_id": channel_id}):
                    await Seishiro.save_channel(channel_id)

                # ── Request link save karo for approve notification ────
                if is_request:
                    await Seishiro.save_user_request_link(uid, channel_id, b64)

                # Peer resolve
                try:
                    chat = await _safe_get_chat(client, channel_id)
                    logger.info(f"Peer OK: {channel_id} → {chat.title}")
                except PeerIdInvalid:
                    if not await _force_resolve_peer(client, channel_id):
                        return await message.reply_text(
                            "<b><blockquote expandable>"
                            "⚠️ Channel resolve nahi hua. Bot ko admin banao aur dobara try karo."
                            "</blockquote></b>"
                        )
                except Exception as e:
                    return await message.reply_text(
                        f"<b><blockquote expandable>Channel error: {str(e)[:80]}</blockquote></b>"
                    )

                # Admin check
                is_admin_ch, can_invite, reason = await check_bot_permissions(client, channel_id)
                if not is_admin_ch:
                    return await message.reply_text(
                        f"<b><blockquote expandable>⚠️ Bot admin nahi hai.\nKaaran: {reason}</blockquote></b>"
                    )
                if not can_invite:
                    return await message.reply_text(
                        "<b><blockquote expandable>⚠️ Bot ko 'Invite Users' permission chahiye.</blockquote></b>"
                    )

                # Encoded link save
                if is_request:
                    await Seishiro.save_encoded_link2(channel_id, b64)
                else:
                    await Seishiro.save_encoded_link(channel_id)

                # Original link check
                orig = await Seishiro.get_original_link(channel_id)
                if orig:
                    return await message.reply_text(
                        "<b><blockquote expandable>Your channel link 👇</blockquote></b>",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("• ᴄʟɪᴄᴋ ʜᴇʀᴇ •", url=orig)
                        ]])
                    )

                # ── Premium → direct link ──────────────────────────────
                if await Seishiro.has_premium_access(uid):
                    inv = await _get_fresh_invite_link(client, channel_id, is_request)
                    if not inv:
                        return await message.reply_text(
                            "<b><blockquote expandable>Invite link error. Dobara try karein.</blockquote></b>"
                        )
                    sent = await _send_invite_msg(message, inv)
                    if is_request and sent:
                        await Seishiro.save_user_request_link(
                            uid, channel_id, b64,
                            link_msg_id=sent.id,
                            link_chat_id=sent.chat.id,
                            invite_link=inv
                        )
                    return

                # ── Free user → shortener flow ─────────────────────────
                cfg          = await _get_bot_config()
                shortener_on = cfg.get("shortener_enabled", False) and bool(cfg.get("shortener_api"))

                if not shortener_on:
                    # Shortener off — direct link do
                    inv = await _get_fresh_invite_link(client, channel_id, is_request)
                    if not inv:
                        return await message.reply_text(
                            "<b><blockquote expandable>Invite link error. Dobara try karein.</blockquote></b>"
                        )
                    sent = await _send_invite_msg(message, inv)
                    if is_request and sent:
                        await Seishiro.save_user_request_link(
                            uid, channel_id, b64,
                            link_msg_id=sent.id,
                            link_chat_id=sent.chat.id,
                            invite_link=inv
                        )
                    return

                # Shortener ON:
                # 1. Token banao
                # 2. Bot verify link → shortener se pass karo
                # 3. User ko shortened URL do
                # 4. User ad complete kare → vfy_<token> pe aaye → temp premium + fresh link
                token = secrets.token_urlsafe(12)
                await Seishiro.create_verify_token(uid, channel_id, token)

                bot_link  = f"https://t.me/{BOT_USERNAME}?start=vfy_{token}"
                short_url = await shorten_link(bot_link)
                logger.info(f"Shortener URL for user {uid}, channel {channel_id}")

                await message.reply_text(
                    "<b>🔗 Aapka Link Ready Hai!</b>\n\n"
                    "<blockquote>"
                    "Niche button pe click karo.\n"
                    "Short ad complete karne ke baad automatically "
                    "channel link mil jayega — <b>koi waiting nahi!</b>\n\n"
                    "⚡ <b>Premium users</b> ko yeh step kabhi nahi karna padta!"
                    "</blockquote>",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔗 Get Channel Link", url=short_url)],
                        [InlineKeyboardButton("💎 Buy Premium — No Ads Ever", callback_data="prem_plans")],
                    ])
                )

                # ── LinkShortner Tutorial: 30s baad check ──
                asyncio.create_task(
                    send_linkshortner_tutorial_if_not_verified(client, uid, token)
                )

            except Exception as e:
                logger.error(f"Deep link error: {e}", exc_info=True)
                await message.reply_text(
                    "<b><blockquote expandable>Invalid or expired invite link.</blockquote></b>"
                )

        # ── Normal /start ──────────────────────────────────────────────
        else:
            is_adm = await _is_admin(uid)
            btns   = [
                [
                    InlineKeyboardButton("• ᴀʙᴏᴜᴛ", callback_data="about"),
                    InlineKeyboardButton("Hᴇʟᴘ •",  callback_data="help")
                ],
                *([[InlineKeyboardButton("⚙️ Sᴇᴛᴛɪɴɢs", callback_data="settings_main")]] if is_adm else []),
                [InlineKeyboardButton("💎 Pʀᴇᴍɪᴜᴍ", callback_data="prem_plans")],
            ]

            caption = START_MSG.format(
                first=message.from_user.first_name,
                last=message.from_user.last_name or "",
                username="@" + message.from_user.username if message.from_user.username else "N/A",
                mention=message.from_user.mention,
                id=uid
            )
            try:
                await message.reply_photo(
                    photo=START_PIC, caption=caption,
                    reply_markup=InlineKeyboardMarkup(btns)
                )
            except Exception as e:
                logger.warning(f"Photo failed: {e}")
                await message.reply_text(caption, reply_markup=InlineKeyboardMarkup(btns))

    except Exception as e:
        logger.error(f"FATAL start_command: {e}", exc_info=True)
        await message.reply_text("<b>Unexpected error. Please try again later.</b>")


# ═══════════════════════════════════════════
# BROADCAST
# ═══════════════════════════════════════════

@Bot.on_message(filters.command("broadcast") & filters.private & admin)
async def broadcast_handler(bot: Client, m: Message):
    try:
        if not m.reply_to_message:
            return await m.reply_text("<b>⚠️ Reply to a message and use /broadcast</b>")

        try:
            all_users = await Seishiro.get_all_users()
        except Exception as e:
            return await m.reply_text(f"<b>❌ Error fetching users: {e}</b>")

        msg     = m.reply_to_message
        sts_msg = await m.reply_text("📤 Broadcast started...")

        done = failed = success = 0
        start_time = time.time()

        try:
            total = await Seishiro.total_users_count()
        except Exception:
            total = 0

        async for user in all_users:
            try:
                sts = await send_msg(user['_id'], msg)
                success += (sts == 200)
                failed  += (sts != 200)
                if sts == 400:
                    try:
                        await Seishiro.delete_user(user['_id'])
                    except Exception:
                        pass
                done += 1
                if done % 20 == 0:
                    try:
                        await sts_msg.edit(
                            f"📤 Broadcasting...\nTotal: {total}\nDone: {done}/{total}\n"
                            f"✅ {success}  ❌ {failed}"
                        )
                    except FloodWait as fw:
                        await asyncio.sleep(fw.value)
                    except Exception:
                        pass
            except Exception as e:
                logger.error(f"Broadcast user error: {e}")
                failed += 1; done += 1

        elapsed = timedelta(seconds=int(time.time() - start_time))
        try:
            await sts_msg.edit(
                f"✅ Broadcast Complete!\nTime: {elapsed}\n"
                f"Total: {total} | Done: {done}\n✅ {success}  ❌ {failed}"
            )
        except Exception:
            await m.reply_text(f"✅ Done. ✅ {success}  ❌ {failed}")

    except Exception as e:
        logger.error(f"broadcast_handler fatal: {e}")
        await m.reply_text(f"<b>❌ Error: {e}</b>")


async def send_msg(user_id, message):
    try:
        await message.copy(chat_id=int(user_id))
        return 200
    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await send_msg(user_id, message)
    except (InputUserDeactivated, UserIsBlocked, PeerIdInvalid):
        return 400
    except RPCError as e:
        logger.error(f"RPC {user_id}: {e}")
        return 500
    except Exception as e:
        logger.error(f"send_msg {user_id}: {e}")
        return 500
