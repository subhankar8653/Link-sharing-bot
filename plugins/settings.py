import asyncio
import base64
import re, time
from datetime import date, datetime, timedelta
from bot import Bot
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, InputMediaPhoto
from pyrogram.errors import UserNotParticipant, FloodWait, ChatAdminRequired, RPCError, PeerIdInvalid
from pyrogram.errors import InviteHashExpired, InviteRequestSent
from database.database import Seishiro
from config import *
from helper_func import *
from pyrogram.enums import ParseMode, ChatMemberStatus

PAGE_SIZE = 6

# Revoke invite link after 5 minutes
async def revoke_invite_after_5_minutes(client: Bot, channel_id: int, link: str, is_request: bool = False):
    await asyncio.sleep(300)
    try:
        await client.revoke_chat_invite_link(channel_id, link)
        print(f"{'Jᴏɪɴ ʀᴇǫᴜᴇsᴛ' if is_request else 'Iɴᴠɪᴛᴇ'} ʟɪɴᴋ ʀᴇᴠᴏᴋᴇᴅ ғᴏʀ ᴄʜᴀɴɴᴇʟ {channel_id}")
    except Exception as e:
        print(f"Fᴀɪʟᴇᴅ ᴛᴏ ʀᴇᴠᴏᴋᴇ ɪɴᴠɪᴛᴇ ғᴏʀ ᴄʜᴀɴɴᴇʟ {channel_id}: {e}")

async def is_owner_or_admin(filter, client, message):
    try:
        user_id = message.from_user.id
        return any([user_id == OWNER_ID, await Seishiro.is_admin(user_id)])
    except Exception as e:
        logger.error(f"Exception in check_admin: {e}")
        return False
        
is_owner_or_admin = filters.create(is_owner_or_admin)

async def is_admin_user(filter, client, message):
    try:
        user_id = message.from_user.id
        return any([user_id == OWNER_ID, await Seishiro.is_admin(user_id)])
    except Exception as e:
        logger.error(f"Exception in check_admin: {e}")
        return False

is_admin_user = filters.create(is_admin_user)

# Build the unified "Mode" menu — one row per channel (name) + one row below it
# (its own Request/Normal toggle). Every channel's toggle is fully independent,
# so switching one channel's mode never touches any other channel's mode.
async def build_fsub_mode_menu(client):
    channels = await Seishiro.get_fsub_channels()
    buttons = []
    for cid in channels:
        try:
            chat = await client.get_chat(cid)
            mode = await Seishiro.get_channel_mode(cid)
            mode_label = "Rᴇǫᴜᴇsᴛ ✅" if mode == "on" else "Nᴏʀᴍᴀʟ ⭕️"
            buttons.append([InlineKeyboardButton(f"{chat.title}", callback_data=f"fsub_mode_info_{cid}")])
            buttons.append([InlineKeyboardButton(f"Mᴏᴅᴇ: {mode_label}  (ᴛᴀᴘ ᴛᴏ sᴡɪᴛᴄʜ)", callback_data=f"fsub_toggle_mode_{cid}")])
        except Exception as e:
            print(f"Error fetching channel {cid}: {e}")
            continue

    buttons.append([InlineKeyboardButton("back", callback_data="fsub_settings_menu")])

    text = (
        "<blockquote><b><i>ᴛᴀᴘ ᴀ ᴄʜᴀɴɴᴇʟ's ᴍᴏᴅᴇ ʙᴜᴛᴛᴏɴ ᴛᴏ sᴡɪᴛᴄʜ ɪᴛ ʙᴇᴛᴡᴇᴇɴ Rᴇǫᴜᴇsᴛ ᴀɴᴅ Nᴏʀᴍᴀʟ.\n"
        "Eᴀᴄʜ ᴄʜᴀɴɴᴇʟ's ᴍᴏᴅᴇ ɪs sᴇᴘᴀʀᴀᴛᴇ — ᴄʜᴀɴɢɪɴɢ ᴏɴᴇ ᴡᴏɴ'ᴛ ᴀғғᴇᴄᴛ ᴀɴʏ ᴏᴛʜᴇʀ ᴄʜᴀɴɴᴇʟ.</i></b></blockquote>"
    )
    return text, buttons


# FSub "Check Duration" (cooldown) menu — ON/OFF + 12h/24h/48h/7day options.
# OFF (default): har baar poora FSub check hota hai, bilkul pehle jaisa.
# ON: user ek baar FSub pass kar le, uske baad is duration ke andar naya FSub
# channel add hone par bhi dubara check/join karne ki zarurat nahi hoti.
FSUB_DURATION_OPTIONS = [
    ("12 Hᴏᴜʀs", 12),
    ("24 Hᴏᴜʀs", 24),
    ("48 Hᴏᴜʀs", 48),
    ("7 Dᴀʏs", 168),
]


async def build_fsub_duration_menu():
    cfg = await Seishiro.get_fsub_check_duration()
    enabled = cfg.get("enabled", False)
    hours = cfg.get("hours", 0)

    status_label = "✅ ON" if enabled else "❌ OFF"
    buttons = [[InlineKeyboardButton(f"Sᴛᴀᴛᴜs: {status_label}  (ᴛᴀᴘ ᴛᴏ sᴡɪᴛᴄʜ)", callback_data="fsub_duration_toggle")]]

    row = []
    for label, hrs in FSUB_DURATION_OPTIONS:
        mark = " ✅" if (enabled and hours == hrs) else ""
        row.append(InlineKeyboardButton(f"{label}{mark}", callback_data=f"fsub_duration_set_{hrs}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([InlineKeyboardButton("back", callback_data="fsub_settings_menu")])

    if enabled and hours:
        duration_text = "7 Dᴀʏs" if hours == 168 else f"{hours} Hᴏᴜʀs"
        status_line = f"Aʙʜɪ: <b>ON</b> — {duration_text}"
    else:
        status_line = "Aʙʜɪ: <b>OFF</b> (ʜᴀʀ ʙᴀᴀʀ ᴘᴏᴏʀᴀ FSᴜʙ ᴄʜᴇᴄᴋ ʜᴏɢᴀ, ʙɪʟᴋᴜʟ ᴘᴇʜʟᴇ ᴊᴀɪsᴀ)"

    text = (
        "<b>⏱ FSᴜʙ Cʜᴇᴄᴋ Dᴜʀᴀᴛɪᴏɴ</b>\n\n"
        "<blockquote>Ek baar user FSub check pass kar le, uske baad is duration "
        "ke andar (chahe koi NAYA FSub channel bhi add ho jaaye) usko dubara "
        "check/join karne ki zarurat nahi hogi.\n\n"
        f"{status_line}</blockquote>"
    )
    return text, buttons

# Settings command to show the main menu
@Bot.on_message(filters.command('settings') & filters.private & is_owner_or_admin)
async def settings_command(client: Client, message: Message):
    try:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Lɪɴᴋ sʜᴀʀᴇ ᴍᴇɴᴜ", callback_data="link_share"), InlineKeyboardButton("Aᴅᴍɪɴ ᴍᴇɴᴜ", callback_data="admin_bna_system")],
            [InlineKeyboardButton("Bᴀɴ ᴍᴇɴᴜ", callback_data="ban_menu"), InlineKeyboardButton("Fsᴜʙ ᴍᴇɴᴜ", callback_data="fsub_settings_menu")],
            [InlineKeyboardButton("🎬 Mɪɴɪ Aᴘᴘ Mᴇɴᴜ", callback_data="mini_menu")],
            [InlineKeyboardButton("Vɪᴇᴡ sᴛᴀᴛᴜs", callback_data="status")],
            [InlineKeyboardButton("• Cʟᴏsᴇ •", callback_data="close")]
        ])
        await message.reply_photo(
            photo="https://ibb.co/cSfdrzRh",
            caption="<b>Hᴇʏ ᴅᴜᴅᴇ...!!</b>\n <blockquote><b><i>Iᴛ's ᴀ ᴘᴏᴡᴇʀғᴜʟ sᴇᴛᴛɪɴɢs ᴍᴇɴᴜ ᴏғ ʟɪɴᴋ sʜᴀʀᴇ ʙᴏᴛ Iɴ ᴛʜɪs ʏᴏᴜ ᴄᴀɴ ᴄʜᴀɴɢᴇ ʏᴏᴜʀ sᴇᴛᴛɪɴɢs ᴇᴀsɪʟʏ ᴡɪᴛʜᴏᴜᴛ ᴀɴʏ ᴍɪsᴛᴀᴋᴇ.</i></b></blockquote>",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Error in settings command: {e}")
        await message.reply_text("An error occurred while opening the settings menu. Please try again later.")
        
# Callback query handler for settings
@Bot.on_callback_query()
async def settings_callback(client: Bot, callback_query):
    user_id = callback_query.from_user.id
    cb_data = callback_query.data
    print(f"Callback received: {cb_data} from user {user_id}")

    try:
        is_admin_user = user_id == OWNER_ID or await Seishiro.is_admin(user_id)

        # Main Settings Menu
        if cb_data == "settings_main":
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Lɪɴᴋ sʜᴀʀᴇ ᴍᴇɴᴜ", callback_data="link_share"), InlineKeyboardButton("Aᴅᴍɪɴ ᴍᴇɴᴜ", callback_data="admin_bna_system")],
                [InlineKeyboardButton("Bᴀɴ ᴍᴇɴᴜ", callback_data="ban_menu"), InlineKeyboardButton("Fsᴜʙ ᴍᴇɴᴜ", callback_data="fsub_settings_menu")],
                [InlineKeyboardButton("🎬 Mɪɴɪ Aᴘᴘ Mᴇɴᴜ", callback_data="mini_menu")],
                [InlineKeyboardButton("Vɪᴇᴡ sᴛᴀᴛᴜs", callback_data="view_status")],
                [InlineKeyboardButton("• Cʟᴏsᴇ •", callback_data="close")]
            ])
            await callback_query.edit_message_media(
                InputMediaPhoto(
                    "https://ibb.co/cSfdrzRh",
                    "<b>Hᴇʏ ᴅᴜᴅᴇ...!!</b>\n <blockquote><b><i>Iᴛ's ᴀ ᴘᴏᴡᴇʀғᴜʟ sᴇᴛᴛɪɴɢs ᴍᴇɴᴜ ᴏғ ʟɪɴᴋ sʜᴀʀᴇ ʙᴏᴛ Iɴ ᴛʜɪs ʏᴏᴜ ᴄᴀɴ ᴄʜᴀɴɢᴇ ʏᴏᴜʀ sᴇᴛᴛɪɴɢs ᴇᴀsɪʟʏ ᴡɪᴛʜᴏᴜᴛ ᴀɴʏ ᴍɪsᴛᴀᴋᴇ.</i></b></blockquote>"),
                reply_markup=keyboard)

        elif cb_data == "close":
            await callback_query.message.delete()
            try:
                await callback_query.message.reply_to_message.delete()
            except:
                pass

        elif cb_data == "link_share":
            auto_accept_on = await Seishiro.get_auto_accept()
            auto_accept_label = f"Aᴜᴛᴏ Rᴇǫᴜᴇsᴛ Aᴄᴄᴇᴘᴛ: {'✅ ON' if auto_accept_on else '❌ OFF'}"
            btn = [
                [InlineKeyboardButton("Aᴅᴅ Cʜᴀɴɴᴇʟ", callback_data="add_channel"), InlineKeyboardButton("Dᴇʟᴇᴛᴇ Cʜᴀɴɴᴇʟ", callback_data="delete_channel")],
                [InlineKeyboardButton("Nᴏʀᴍᴀʟ Lɪɴᴋs", callback_data="channel_links"), InlineKeyboardButton("Rᴇǫᴜᴇsᴛ Lɪɴᴋs", callback_data="request_links")],
                [InlineKeyboardButton("Lɪsᴛ Cʜᴀɴɴᴇʟs", callback_data="list_channels")],
                [InlineKeyboardButton(auto_accept_label, callback_data="toggle_auto_accept")],
                [InlineKeyboardButton("back", callback_data="settings_main")]]
            await callback_query.message.edit_text("<blockquote><b><i>Iɴ ᴛʜɪs ʏᴏᴜ ᴄᴀɴ ᴄʜᴀɴɢᴇ ᴀɴᴅ ᴠɪᴇᴡ ʏᴏᴜʀs ᴄʜᴀɴɴᴇʟs...!!</i></b></blockquote>", reply_markup=InlineKeyboardMarkup(btn))

        elif cb_data == "toggle_auto_accept":
            if not is_admin_user:
                await callback_query.answer("Only admins can change this setting!", show_alert=True)
                return

            current = await Seishiro.get_auto_accept()
            new_status = not current
            await Seishiro.set_auto_accept(new_status)

            auto_accept_label = f"Aᴜᴛᴏ Rᴇǫᴜᴇsᴛ Aᴄᴄᴇᴘᴛ: {'✅ ON' if new_status else '❌ OFF'}"
            btn = [
                [InlineKeyboardButton("Aᴅᴅ Cʜᴀɴɴᴇʟ", callback_data="add_channel"), InlineKeyboardButton("Dᴇʟᴇᴛᴇ Cʜᴀɴɴᴇʟ", callback_data="delete_channel")],
                [InlineKeyboardButton("Nᴏʀᴍᴀʟ Lɪɴᴋs", callback_data="channel_links"), InlineKeyboardButton("Rᴇǫᴜᴇsᴛ Lɪɴᴋs", callback_data="request_links")],
                [InlineKeyboardButton("Lɪsᴛ Cʜᴀɴɴᴇʟs", callback_data="list_channels")],
                [InlineKeyboardButton(auto_accept_label, callback_data="toggle_auto_accept")],
                [InlineKeyboardButton("back", callback_data="settings_main")]]
            await callback_query.message.edit_text("<blockquote><b><i>Iɴ ᴛʜɪs ʏᴏᴜ ᴄᴀɴ ᴄʜᴀɴɢᴇ ᴀɴᴅ ᴠɪᴇᴡ ʏᴏᴜʀs ᴄʜᴀɴɴᴇʟs...!!</i></b></blockquote>", reply_markup=InlineKeyboardMarkup(btn))
            await callback_query.answer(f"Auto Request Accept {'ON kar diya ✅' if new_status else 'OFF kar diya ❌'}")

        elif cb_data == "view_status":
            total_users = await Seishiro.total_users_count()
            # Calculate uptime properly using datetime
            current_time = datetime.now()
            uptime_delta = current_time - client.uptime
            uptime_seconds = uptime_delta.total_seconds()
            uptime = time.strftime("%Hh%Mm%Ss", time.gmtime(uptime_seconds))
            await callback_query.answer(f"•Bᴏᴛ ᴜᴘᴛɪᴍᴇ: {uptime}\n•Tᴏᴛᴀʟ ᴜsᴇʀs: {total_users}\n•Vᴇʀsɪᴏɴ: 2.05v", show_alert=True)
            
        elif cb_data == "about":
            user = await client.get_users(OWNER_ID)
            community = await Seishiro.get_community()
            await callback_query.edit_message_media(
                InputMediaPhoto(
                    "https://ibb.co/cSfdrzRh",
                    get_about_txt(community["name"], community["link"])
                ),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('• ʙᴀᴄᴋ', callback_data='start'), 
                     InlineKeyboardButton('ᴄʟᴏsᴇ •', callback_data='close')]
                ])
            )

        elif cb_data == "help":
            await callback_query.edit_message_media(
                InputMediaPhoto(
                    "https://ibb.co/cSfdrzRh",
                    HELP_TXT.format(
                        first=callback_query.from_user.first_name,
                        last=callback_query.from_user.last_name or "",
                        username=f"@{callback_query.from_user.username}" if callback_query.from_user.username else "None",
                        mention=callback_query.from_user.mention,
                        id=callback_query.from_user.id)),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('• ʙᴀᴄᴋ', callback_data='start'), 
                     InlineKeyboardButton('ᴄʟᴏsᴇ •', callback_data='close')]
                ])
            )
        
        elif cb_data == "start":
            user_id = callback_query.from_user.id
            # Check if user is owner or admin in database
            is_admin = (user_id == OWNER_ID) or await Seishiro.is_admin(user_id)

            if is_admin:
                # Show Settings button for admins/owner
                inline_buttons = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton("• ᴀʙᴏᴜᴛ", callback_data="about"),
                            InlineKeyboardButton("Hᴇʟᴘ •", callback_data="help")
                        ],
                        [
                            InlineKeyboardButton("Sᴇᴛᴛɪɴɢs", callback_data="settings_main")
                        ]
                    ]
                )
            else:
                # Hide Settings for normal users
                inline_buttons = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton("• ᴀʙᴏᴜᴛ", callback_data="about"),
                            InlineKeyboardButton("Hᴇʟᴘ •", callback_data="help")
                        ]
                    ]
                )
                
            try:
                await callback_query.edit_message_media(
                    InputMediaPhoto(START_PIC, START_MSG.format(
                        first=callback_query.from_user.first_name,
                        last=callback_query.from_user.last_name or "",
                        username=f"@{callback_query.from_user.username}" if callback_query.from_user.username else "None",
                        mention=callback_query.from_user.mention,
                        id=callback_query.from_user.id)),
                    reply_markup=inline_buttons
                )
            except Exception as e:
                print(f"Error sending start/home photo: {e}")
                await callback_query.edit_message_text(
                    START_MSG.format(
                        first=callback_query.from_user.first_name,
                        last=callback_query.from_user.last_name or "",
                        username=f"@{callback_query.from_user.username}" if callback_query.from_user.username else "None",
                        mention=callback_query.from_user.mention,
                        id=callback_query.from_user.id),
                    reply_markup=inline_buttons,
                    parse_mode=ParseMode.HTML
                )

        # Ban Menu
        elif cb_data == "ban_menu":
            if not is_admin_user:
                await callback_query.answer("Only admins can access this!", show_alert=True)
                return
            
            btn = [
                [InlineKeyboardButton("Bᴀɴ Usᴇʀ", callback_data="ban_user"), 
                 InlineKeyboardButton("Uɴʙᴀɴ Usᴇʀ", callback_data="unban_user")],
                [InlineKeyboardButton("Bᴀɴɴᴇᴅ Lɪsᴛ", callback_data="banned_list")],
                [InlineKeyboardButton("back", callback_data="settings_main")]
            ]
            await callback_query.message.edit_text(
                "<blockquote><b><i>Iɴ ᴛʜɪs ʏᴏᴜ ᴄᴀɴ ʙᴀɴ, ᴜɴʙᴀɴ ᴀɴᴅ sᴇᴇ ᴛʜᴇ ʙᴀɴɴᴇᴅ ᴜsᴇʀs.</i></b></blockquote>",
                reply_markup=InlineKeyboardMarkup(btn)
            )

        # Ban User
        elif cb_data == "ban_user":
            if not is_admin_user:
                await callback_query.answer("Only admins can ban users!", show_alert=True)
                return
            
            btn = [[InlineKeyboardButton("back", callback_data="ban_menu")]]
            await callback_query.message.edit_text(
                "<b>Sᴇɴᴅ ᴛʜᴇ ᴜsᴇʀ ID ᴡʜɪᴄʜ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ʙᴀɴ (e.g., 123456789):\n\n"
                "Yᴏᴜ ᴄᴀɴ ᴀʟsᴏ ᴘʀᴏᴠɪᴅᴇ ᴀ ʀᴇᴀsᴏɴ:\n"
                "<code>user_id reason</code>\n\n"
                "/cancel ᴛᴏ ᴄᴀɴᴄᴇʟ</b>",
                reply_markup=InlineKeyboardMarkup(btn)
            )
            
            try:
                msg = await client.listen(chat_id=callback_query.message.chat.id, timeout=300)
                await callback_query.message.delete()
                
                if msg.text == '/cancel':
                    await msg.reply("ᴄᴀɴᴄᴇʟʟᴇᴅ!", reply_markup=InlineKeyboardMarkup(btn))
                    return
                
                parts = msg.text.split(maxsplit=1)
                user_id_str = parts[0]
                reason = parts[1] if len(parts) > 1 else "No reason provided"
                
                if not user_id_str.lstrip('-').isdigit():
                    await msg.reply(
                        "<b><blockquote expandable>Iɴᴠᴀʟɪᴅ ᴜsᴇʀ ID. Pʟᴇᴀsᴇ sᴇɴᴅ ᴀ ᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ.</blockquote></b>",
                        reply_markup=InlineKeyboardMarkup(btn)
                    )
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
                
                await msg.reply(
                    f"<b>Usᴇʀ - `{ban_user_id}` Is sᴜᴄᴄᴇssғᴜʟʟʏ ʙᴀɴɴᴇᴅ. Success\nRᴇᴀsᴏɴ:- {reason}</b>",
                    reply_markup=InlineKeyboardMarkup(btn)
                )
            except asyncio.TimeoutError:
                await callback_query.message.reply(
                    "<b>Tɪᴍᴇᴏᴜᴛ! Pʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ.</b>",
                    reply_markup=InlineKeyboardMarkup(btn)
                )
            except Exception as e:
                print(f"Error banning user: {e}")
                await msg.reply(f"Uɴᴇxᴘᴇᴄᴛᴇᴅ Eʀʀᴏʀ: {str(e)}", reply_markup=InlineKeyboardMarkup(btn))

        # Unban User
        elif cb_data == "unban_user":
            if not is_admin_user:
                await callback_query.answer("Only admins can unban users!", show_alert=True)
                return
            
            btn = [[InlineKeyboardButton("back", callback_data="ban_menu")]]
            await callback_query.message.edit_text(
                "<b>Sᴇɴᴅ ᴛʜᴇ ᴜsᴇʀ ID ᴛᴏ ᴜɴʙᴀɴ (e.g., 123456789):\n\n/cancel ᴛᴏ ᴄᴀɴᴄᴇʟ</b>",
                reply_markup=InlineKeyboardMarkup(btn)
            )
            
            try:
                msg = await client.listen(chat_id=callback_query.message.chat.id, timeout=300)
                await callback_query.message.delete()
                
                if msg.text == '/cancel':
                    await msg.reply("ᴄᴀɴᴄᴇʟʟᴇᴅ!", reply_markup=InlineKeyboardMarkup(btn))
                    return
                
                if not msg.text.lstrip('-').isdigit():
                    await msg.reply(
                        "<b><blockquote expandable>Iɴᴠᴀʟɪᴅ ᴜsᴇʀ ID. Pʟᴇᴀsᴇ sᴇɴᴅ ᴀ ᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ.</blockquote></b>",
                        reply_markup=InlineKeyboardMarkup(btn)
                    )
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
                
                if result.matched_count == 0:
                    await msg.reply(
                        f"<b>Usᴇʀ - `{unban_user_id}` ɴᴏᴛ ғᴏᴜɴᴅ ɪɴ ᴅᴀᴛᴀʙᴀsᴇ.</b>",
                        reply_markup=InlineKeyboardMarkup(btn)
                    )
                else:
                    await msg.reply(
                        f"<b>Usᴇʀ - `{unban_user_id}` Is sᴜᴄᴄᴇssғᴜʟʟʏ ᴜɴʙᴀɴɴᴇᴅ. Success</b>",
                        reply_markup=InlineKeyboardMarkup(btn)
                    )
            except asyncio.TimeoutError:
                await callback_query.message.reply(
                    "<b>Tɪᴍᴇᴏᴜᴛ! Pʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ.</b>",
                    reply_markup=InlineKeyboardMarkup(btn)
                )
            except Exception as e:
                print(f"Error unbanning user: {e}")
                await msg.reply(f"Uɴᴇxᴘᴇᴄᴛᴇᴅ Eʀʀᴏʀ: {str(e)}", reply_markup=InlineKeyboardMarkup(btn))

        # Banned List - FIXED: Removed reply_markup from answer()
        elif cb_data == "banned_list":
            if not is_admin_user:
                await callback_query.answer("Only admins can view banned list!", show_alert=True)
                return
            
            await callback_query.answer("Pʟᴇᴀsᴇ ᴡᴀɪᴛ...")
            
            try:
                cursor = Seishiro.ban_data.find({"ban_status.is_banned": True})
                lines = []
                
                async for user in cursor:
                    uid = user['_id']
                    reason = user.get('ban_status', {}).get('ban_reason', 'No reason')
                    try:
                        user_obj = await client.get_users(uid)
                        name = user_obj.mention
                    except PeerIdInvalid:
                        name = f"`{uid}` (Name not found)"
                    except Exception:
                        name = f"`{uid}`"
                    lines.append(f"• {name} - {reason}")
                
                btn = [[InlineKeyboardButton("back", callback_data="ban_menu")]]
                
                if not lines:
                    await callback_query.message.edit_text(
                        "<b>Nᴏ ᴜsᴇʀ(s) ɪs ᴄᴜʀʀᴇɴᴛʟʏ ʙᴀɴɴᴇᴅ</b>",
                        reply_markup=InlineKeyboardMarkup(btn)
                    )
                else:
                    await callback_query.message.edit_text(
                        "Bᴀɴɴᴇᴅ ᴜsᴇʀ(s)\n\n" + "\n".join(lines[:50]),
                        reply_markup=InlineKeyboardMarkup(btn)
                    )
            except Exception as e:
                btn = [[InlineKeyboardButton("back", callback_data="ban_menu")]]
                await callback_query.message.edit_text(
                    f"<b>An error occurred while fetching banned users:</b> `{e}`",
                    reply_markup=InlineKeyboardMarkup(btn)
                )

        # Fsub Settings Menu
        elif cb_data == "fsub_settings_menu":
            if not is_admin_user:
                await callback_query.answer("Only admins can access this!", show_alert=True)
                return
            
            layout = await Seishiro.get_fsub_layout()
            btn = [
                [InlineKeyboardButton("Aᴅᴅ Cʜᴀɴɴᴇʟ", callback_data="add_fsub_channel"), InlineKeyboardButton("Rᴇᴍᴏᴠᴇ Cʜᴀɴɴᴇʟ", callback_data="delete_fsub_channel")],
                [InlineKeyboardButton("Lɪsᴛ Cʜᴀɴɴᴇʟs", callback_data="list_fsub_channels")],
                [InlineKeyboardButton("✏️ Rᴇɴᴀᴍᴇ Bᴜᴛᴛᴏɴ", callback_data="rename_fsub_channel")],
                [InlineKeyboardButton("Mᴏᴅᴇ", callback_data="fsub_mode_menu")],
                [InlineKeyboardButton("⏳ Aᴜᴛᴏ Rᴇᴍᴏᴠᴇ / Lɪɴᴋ Rᴏᴛᴀᴛᴇ", callback_data="fsx_sch")],
                [InlineKeyboardButton("📝 Eᴅɪᴛ Fsᴜʙ Tᴇxᴛ", callback_data="fsx_txt")],
                [InlineKeyboardButton("⏱ Cʜᴇᴄᴋ Dᴜʀᴀᴛɪᴏɴ", callback_data="fsub_check_duration_menu")],
                [InlineKeyboardButton(("✅ " if layout == 1 else "") + "1 Rᴏᴡ = 1 Bᴜᴛᴛᴏɴ", callback_data="fsx_lay:1"),
                 InlineKeyboardButton(("✅ " if layout == 2 else "") + "1 Rᴏᴡ = 2 Bᴜᴛᴛᴏɴs", callback_data="fsx_lay:2")],
                [InlineKeyboardButton("back", callback_data="settings_main")]
            ]
            await callback_query.message.edit_text(
                "<blockquote><b><i>Iᴛ's ʏᴏᴜʀs ғᴏʀᴄᴇ sᴜʙsᴄʀɪᴘᴛɪᴏɴ ᴍᴇɴᴜ ɪɴ ᴛʜɪs ʏᴏᴜ ᴄᴀɴ ᴀᴅᴅ, ᴅᴇʟᴇᴛᴇ, ᴠɪᴇᴡ, ʀᴇǫᴜᴇsᴛ ʏᴏᴜʀ ғᴏʀᴄᴇ sᴜʙ ᴄʜᴀɴɴᴇʟs.</i></b></blockquote>",
                reply_markup=InlineKeyboardMarkup(btn)
            )

        # FSub Check Duration (cooldown) menu
        elif cb_data == "fsub_check_duration_menu":
            if not is_admin_user:
                await callback_query.answer("Only admins can access this!", show_alert=True)
                return
            text, buttons = await build_fsub_duration_menu()
            await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

        elif cb_data == "fsub_duration_toggle":
            if not is_admin_user:
                await callback_query.answer("Only admins can perform this action!", show_alert=True)
                return
            cfg = await Seishiro.get_fsub_check_duration()
            new_enabled = not cfg.get("enabled", False)
            hours = cfg.get("hours") or 12  # pehli baar ON karte waqt agar kabhi duration set nahi hui to default 12h
            await Seishiro.set_fsub_check_duration(new_enabled, hours)
            await callback_query.answer(f"Switched {'ON' if new_enabled else 'OFF'}")
            text, buttons = await build_fsub_duration_menu()
            await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

        elif cb_data.startswith("fsub_duration_set_"):
            if not is_admin_user:
                await callback_query.answer("Only admins can perform this action!", show_alert=True)
                return
            try:
                hours = int(cb_data.replace("fsub_duration_set_", ""))
            except ValueError:
                await callback_query.answer("Invalid duration", show_alert=True)
                return
            await Seishiro.set_fsub_check_duration(True, hours)
            label = "7 Days" if hours == 168 else f"{hours} Hours"
            await callback_query.answer(f"✅ Set to {label} & turned ON")
            text, buttons = await build_fsub_duration_menu()
            await callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))

        # Unified Mode Menu — every channel gets its own name row + its own
        # Request/Normal toggle row directly below it. No shared "all channels"
        # switch anymore, so toggling one channel can never bleed into another.
        elif cb_data == "fsub_mode_menu":
            if not is_admin_user:
                await callback_query.answer("Only admins can access this!", show_alert=True)
                return

            fsub_channels = await Seishiro.get_fsub_channels()
            if not fsub_channels:
                await callback_query.answer("No fsub channels found! Add channels first.", show_alert=True)
                return

            text, buttons = await build_fsub_mode_menu(client)
            await callback_query.message.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup(buttons)
            )

        # Tapping a channel's name — just confirms which channel that row is for
        elif cb_data.startswith("fsub_mode_info_"):
            cid = int(cb_data.split("_")[-1])
            try:
                chat = await client.get_chat(cid)
                mode = await Seishiro.get_channel_mode(cid)
                mode_label = "Rᴇǫᴜᴇsᴛ Mᴏᴅᴇ (ON)" if mode == "on" else "Nᴏʀᴍᴀʟ Mᴏᴅᴇ (OFF)"
                await callback_query.answer(f"{chat.title}\nCurrent: {mode_label}", show_alert=True)
            except Exception:
                await callback_query.answer("Failed to fetch channel info", show_alert=True)

        # One-click, per-channel Request/Normal toggle — only the tapped
        # channel's mode changes; every other channel is left untouched.
        elif cb_data.startswith("fsub_toggle_mode_"):
            if not is_admin_user:
                await callback_query.answer("Only admins can perform this action!", show_alert=True)
                return

            cid = int(cb_data.split("_")[-1])
            try:
                current_mode = await Seishiro.get_channel_mode(cid)
                new_mode = "off" if current_mode == "on" else "on"
                await Seishiro.set_channel_mode(cid, new_mode)
                await callback_query.answer(f"Switched to {'Request' if new_mode == 'on' else 'Normal'} mode")
            except Exception as e:
                await callback_query.answer(f"Error: {str(e)}", show_alert=True)
                return

            # Re-render the menu so the updated status is visible immediately
            text, buttons = await build_fsub_mode_menu(client)
            await callback_query.message.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup(buttons)
            )

        # Add Fsub Channel
        elif cb_data == "add_fsub_channel":
            if not is_admin_user:
                await callback_query.answer("Only admins can add channels!", show_alert=True)
                return
            
            btn = [[InlineKeyboardButton("back", callback_data="fsub_settings_menu")]]
            await callback_query.message.edit_text(
                "<b>Sᴇɴᴅ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ ID ᴡʜɪᴄʜ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴀᴅᴅ ɪɴ ғsᴜʙ (e.g., -100123456789):\n\n/cancel ᴛᴏ ᴄᴀɴᴄᴇʟ</b>",
                reply_markup=InlineKeyboardMarkup(btn)
            )
            
            try:
                msg = await client.listen(chat_id=callback_query.message.chat.id, timeout=300)
                temp = await msg.reply("<i>Pʟᴇᴀsᴇ ᴡᴀɪᴛ...</i>")
                await callback_query.message.delete()
                
                if msg.text == '/cancel':
                    await temp.edit("ᴄᴀɴᴄᴇʟʟᴇᴅ!", reply_markup=InlineKeyboardMarkup(btn))
                    return
                
                # Validate channel ID format
                if not re.match(r"^-100\d{10,}$", msg.text):
                    await temp.edit(
                        "<b><blockquote expandable>Iɴᴠᴀʟɪᴅ ᴄʜᴀɴɴᴇʟ ID. Mᴜsᴛ ʙᴇ ɪɴ ᴛʜᴇ ғᴏʀᴍᴀᴛ -100XXXXXXXXXX.</blockquote></b>",
                        reply_markup=InlineKeyboardMarkup(btn)
                    )
                    return
                
                channel_id = int(msg.text)
                
                # Check if bot is a member of the channel
                try:
                    chat_member = await client.get_chat_member(channel_id, client.me.id)
                    valid_statuses = [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
                    
                    if chat_member.status not in valid_statuses:
                        await temp.edit(
                            f"<b><blockquote expandable>I ᴀᴍ ɴᴏᴛ ᴀɴ ᴀᴅᴍɪɴ ᴏғ ᴛʜɪs ᴄʜᴀɴɴᴇʟ. Sᴛᴀᴛᴜs: {chat_member.status}. Pʟᴇᴀsᴇ ᴍᴀᴋᴇ ᴍᴇ ᴀᴅᴍɪɴ ᴀɴᴅ ᴛʀʏ ᴀɢᴀɪɴ.</blockquote></b>",
                            reply_markup=InlineKeyboardMarkup(btn)
                        )
                        return
                except UserNotParticipant:
                    await temp.edit(
                        "<b><blockquote expandable>I ᴀᴍ ɴᴏᴛ ᴀ ᴍᴇᴍʙᴇʀ ᴏғ ᴛʜɪs ᴄʜᴀɴɴᴇʟ. Pʟᴇᴀsᴇ ᴀᴅᴅ ᴍᴇ ᴀɴᴅ ᴛʀʏ ᴀɢᴀɪɴ.</blockquote></b>",
                        reply_markup=InlineKeyboardMarkup(btn)
                    )
                    return
                except RPCError as e:
                    if "CHANNEL_INVALID" in str(e):
                        await temp.edit(
                            "<b><blockquote expandable>Iɴᴠᴀʟɪᴅ ᴄʜᴀɴɴᴇʟ ID ᴏʀ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ ᴅᴏᴇs ɴᴏᴛ ᴇxɪsᴛ. Pʟᴇᴀsᴇ ᴄʜᴇᴄᴋ ᴛʜᴇ ID ᴀɴᴅ ᴛʀʏ ᴀɢᴀɪɴ.</blockquote></b>",
                            reply_markup=InlineKeyboardMarkup(btn)
                        )
                        return
                    print(f"RPC Error checking membership for channel {channel_id}: {e}")
                    await temp.edit(
                        f"<b><blockquote expandable>Fᴀɪʟᴇᴅ ᴛᴏ ᴠᴇʀɪғʏ ᴍᴇᴍʙᴇʀsʜɪᴘ. Eʀʀᴏʀ: {str(e)}.</blockquote></b>",
                        reply_markup=InlineKeyboardMarkup(btn)
                    )
                    return
                
                # Fetch chat details
                try:
                    chat = await client.get_chat(channel_id)
                except RPCError as e:
                    print(f"Error fetching chat {channel_id}: {e}")
                    await temp.edit(
                        f"<b><blockquote expandable>Fᴀɪʟᴇᴅ ᴛᴏ ᴀᴄᴄᴇss ᴄʜᴀɴɴᴇʟ. Eʀʀᴏʀ: {str(e)}.</blockquote></b>",
                        reply_markup=InlineKeyboardMarkup(btn)
                    )
                    return
                
                # Get invite link
                try:
                    link = await client.export_chat_invite_link(chat.id)
                except Exception:
                    link = f"https://t.me/{chat.username}" if chat.username else f"https://t.me/c/{str(chat.id)[4:]}"
                
                # Add to fsub
                await Seishiro.add_fsub_channel(channel_id)
                
                await temp.edit(
                    f"<b>Fᴏʀᴄᴇ-sᴜʙ ᴄʜᴀɴɴᴇʟ ᴀᴅᴅᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n\n"
                    f"<b>Nᴀᴍᴇ:</b> <a href='{link}'>{chat.title}</a>\n"
                    f"<b>Iᴅ:</b> <code>{channel_id}</code>\n"
                    f"<b>Mᴏᴅᴇ:</b> Rᴇǫᴜᴇsᴛ (auto)",
                    disable_web_page_preview=True,
                    reply_markup=InlineKeyboardMarkup(btn)
                )
            except asyncio.TimeoutError:
                await callback_query.message.reply(
                    "<b>Tɪᴍᴇᴏᴜᴛ! Pʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ.</b>",
                    reply_markup=InlineKeyboardMarkup(btn)
                )
            except Exception as e:
                print(f"Error adding fsub channel: {e}")
                await temp.edit(
                    f"<b>Failed to add channel:</b>\n<code>{channel_id}</code>\n\n<i>{e}</i>",
                    reply_markup=InlineKeyboardMarkup(btn)
                )

        # Remove Fsub Channel
        elif cb_data == "delete_fsub_channel":
            if not is_admin_user:
                await callback_query.answer("Only admins can delete channels!", show_alert=True)
                return
            
            btn = [[InlineKeyboardButton("back", callback_data="fsub_settings_menu")]]
            await callback_query.message.edit_text(
                "<b>Sᴇɴᴅ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ ID ᴛᴏ ʀᴇᴍᴏᴠᴇ ғʀᴏᴍ ғsᴜʙ (e.g., -100123456789):\n\n/cancel ᴛᴏ ᴄᴀɴᴄᴇʟ</b>",
                reply_markup=InlineKeyboardMarkup(btn)
            )
            
            try:
                msg = await client.listen(chat_id=callback_query.message.chat.id, timeout=300)
                await callback_query.message.delete()
                
                if msg.text == '/cancel':
                    await msg.reply("ᴄᴀɴᴄᴇʟʟᴇᴅ!", reply_markup=InlineKeyboardMarkup(btn))
                    return
                
                channel_id = int(msg.text)
                # Pehle join/request link revoke karo (jis link se members is channel
                # mein aaye the), fir hi fsub list se channel remove karo.
                await revoke_fsub_channel_link(client, channel_id)
                await Seishiro.remove_fsub_channel(channel_id)
                await msg.reply(
                    f"<b><blockquote expandable>Cʜᴀɴɴᴇʟ {channel_id} ʜᴀs ʙᴇᴇɴ ʀᴇᴍᴏᴠᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ.\n"
                    f"Iᴛs ɪɴᴠɪᴛᴇ/ʀᴇǫᴜᴇsᴛ ʟɪɴᴋ ʜᴀs ʙᴇᴇɴ ʀᴇᴠᴏᴋᴇᴅ.</blockquote></b>",
                    reply_markup=InlineKeyboardMarkup(btn)
                )
            except (ValueError, IndexError):
                await msg.reply(
                    "<b><blockquote expandable>Iɴᴠᴀʟɪᴅ ᴄʜᴀɴɴᴇʟ ID. Pʟᴇᴀsᴇ sᴇɴᴅ ᴀ ᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ.</blockquote></b>",
                    reply_markup=InlineKeyboardMarkup(btn)
                )
            except Exception as e:
                print(f"Error deleting channel {msg.text}: {e}")
                await msg.reply(f"Unexpected Error: {str(e)}", reply_markup=InlineKeyboardMarkup(btn))

        # ✏️ Rename FSub Channel Button Text
        elif cb_data == "rename_fsub_channel":
            if not is_admin_user:
                await callback_query.answer("Only admins can rename channels!", show_alert=True)
                return

            btn = [[InlineKeyboardButton("back", callback_data="fsub_settings_menu")]]
            await callback_query.message.edit_text(
                "<b>✏️ FSub Button Rename</b>\n\n"
                "<blockquote>Channel ID bhejo jiska button rename karna hai.\n"
                "(e.g., -100123456789)\n\n"
                "/cancel to cancel</blockquote>",
                reply_markup=InlineKeyboardMarkup(btn)
            )

            try:
                msg_id = await client.listen(chat_id=callback_query.message.chat.id, timeout=300)
                await callback_query.message.delete()

                if msg_id.text == '/cancel':
                    await msg_id.reply("ᴄᴀɴᴄᴇʟʟᴇᴅ!", reply_markup=InlineKeyboardMarkup(btn))
                    return

                if not re.match(r"^-100\d{10,}$", msg_id.text.strip()):
                    await msg_id.reply(
                        "<b><blockquote expandable>Invalid channel ID format. Must be -100XXXXXXXXXX</blockquote></b>",
                        reply_markup=InlineKeyboardMarkup(btn)
                    )
                    return

                channel_id = int(msg_id.text.strip())

                # Verify channel exists in fsub
                channels = await Seishiro.get_fsub_channels()
                if channel_id not in channels:
                    await msg_id.reply(
                        "<b><blockquote expandable>⚠️ Yeh channel FSub mein nahi hai. Pehle add karo.</blockquote></b>",
                        reply_markup=InlineKeyboardMarkup(btn)
                    )
                    return

                await msg_id.reply(
                    "<b>Ab naya button naam bhejo:</b>\n<blockquote>Jo bhi text likhoge wahi button pe dikhega.</blockquote>\n\n/cancel to cancel",
                    reply_markup=InlineKeyboardMarkup(btn)
                )

                msg_name = await client.listen(chat_id=callback_query.message.chat.id, timeout=300)

                if msg_name.text == '/cancel':
                    await msg_name.reply("ᴄᴀɴᴄᴇʟʟᴇᴅ!", reply_markup=InlineKeyboardMarkup(btn))
                    return

                new_name = msg_name.text.strip()
                if len(new_name) > 50:
                    await msg_name.reply(
                        "<b><blockquote expandable>⚠️ Name too long! 50 characters se kam rakho.</blockquote></b>",
                        reply_markup=InlineKeyboardMarkup(btn)
                    )
                    return

                await Seishiro.set_fsub_channel_name(channel_id, new_name)
                await msg_name.reply(
                    f"<b>✅ Done!</b>\n\n"
                    f"<blockquote>Channel <code>{channel_id}</code> ka button ab dikhega:\n"
                    f"<b>» {new_name} «</b></blockquote>",
                    reply_markup=InlineKeyboardMarkup(btn)
                )

            except asyncio.TimeoutError:
                await callback_query.message.reply(
                    "<b>Timeout! Please try again.</b>",
                    reply_markup=InlineKeyboardMarkup(btn)
                )
            except Exception as e:
                await callback_query.message.reply(
                    f"<b>Error: {e}</b>",
                    reply_markup=InlineKeyboardMarkup(btn)
                )

        # List Fsub Channels - NEW FEATURE
        elif cb_data == "list_fsub_channels":
            if not is_admin_user:
                await callback_query.answer("Only admins can view fsub channels!", show_alert=True)
                return
            
            await callback_query.answer("Fᴇᴛᴄʜɪɴɢ ғsᴜʙ ᴄʜᴀɴɴᴇʟs...")
            
            try:
                fsub_channels = await Seishiro.get_fsub_channels()
                
                btn = [[InlineKeyboardButton("back", callback_data="fsub_settings_menu")]]
                
                if not fsub_channels:
                    await callback_query.message.edit_text(
                        "<b>Nᴏ ғsᴜʙ ᴄʜᴀɴɴᴇʟs ғᴏᴜɴᴅ.\n\nPʟᴇᴀsᴇ ᴀᴅᴅ ᴄʜᴀɴɴᴇʟs ᴜsɪɴɢ 'Aᴅᴅ Fsᴜʙ Cʜᴀɴɴᴇʟ' ᴏᴘᴛɪᴏɴ.</b>",
                        reply_markup=InlineKeyboardMarkup(btn)
                    )
                    return
                
                fsub_list = "<b>Fsᴜʙ Cʜᴀɴɴᴇʟs Lɪsᴛ:</b>\n\n"
                
                for idx, channel_id in enumerate(fsub_channels, 1):
                    try:
                        chat = await client.get_chat(channel_id)
                        mode = await Seishiro.get_channel_mode(channel_id)
                        status_emoji = "ON" if mode == "on" else "OFF"
                        status_text = "Rᴇǫᴜᴇsᴛ ON" if mode == "on" else "Rᴇǫᴜᴇsᴛ OFF"
                        
                        # Invite link ke liye ab naya link generate NAHI karte (export_chat_invite_link
                        # har baar ek NAYA primary link bana deta hai jo purana link invalid kar deta hai).
                        # Isके bajaye wahi CACHED/SHARED link dikhao jo fsub gate sab users ko deta hai.
                        if chat.username:
                            link = f"https://t.me/{chat.username}"
                            fsub_list += f"{idx}. <a href='{link}'>{chat.title}</a> {status_emoji}\n"
                        else:
                            cached = await Seishiro.get_current_invite_link(channel_id)
                            if cached:
                                fsub_list += f"{idx}. <a href='{cached['invite_link']}'>{chat.title}</a> {status_emoji}\n"
                            else:
                                fsub_list += f"{idx}. {chat.title} {status_emoji}\n"

                        stats = await Seishiro.get_fsub_stats(channel_id)
                        fsub_list += f"    <code>{channel_id}</code> - {status_text}\n"
                        fsub_list += (
                            f"    👥 Jᴏɪɴᴇᴅ: <b>{stats['join_count']}</b> | "
                            f"📥 Rᴇǫᴜᴇsᴛs: <b>{stats['request_count']}</b>\n\n"
                        )
                        
                    except Exception as e:
                        print(f"Error fetching channel {channel_id}: {e}")
                        fsub_list += f"{idx}. <code>{channel_id}</code> (Error fetching info)\n\n"
                
                fsub_list += f"<b>Tᴏᴛᴀʟ Fsᴜʙ Cʜᴀɴɴᴇʟs: {len(fsub_channels)}</b>\n"
                fsub_list += "\n<i>ON = Request Mode ON | OFF = Request Mode OFF</i>"
                
                await callback_query.message.edit_text(
                    fsub_list,
                    reply_markup=InlineKeyboardMarkup(btn),
                    disable_web_page_preview=True
                )
            except Exception as e:
                btn = [[InlineKeyboardButton("back", callback_data="fsub_settings_menu")]]
                await callback_query.message.edit_text(
                    f"<b>Eʀʀᴏʀ ғᴇᴛᴄʜɪɴɢ ғsᴜʙ ᴄʜᴀɴɴᴇʟs:</b> {str(e)}",
                    reply_markup=InlineKeyboardMarkup(btn)
                )

        # Admin Panel
        elif cb_data == "admin_bna_system":
            if not is_admin_user:
                await callback_query.answer("Only admins can access this!", show_alert=True)
                return
            
            btn = [
                [InlineKeyboardButton("Aᴅᴅ ᴀᴅᴍɪɴ", callback_data="admin_bna"), 
                 InlineKeyboardButton("Rᴇᴍᴏᴠᴇ Aᴅᴍɪɴ", callback_data="admin_hta")],
                [InlineKeyboardButton("Lɪsᴛ Aᴅᴍɪɴs", callback_data="admin_list")],
                [InlineKeyboardButton("back", callback_data="settings_main")]
            ]
            await callback_query.message.edit_text(
                "<blockquote><b><i>Iɴ ᴛʜɪs ʏᴏᴜ ᴄᴀɴ ᴀᴅᴅ, ʀᴇᴍᴏᴠᴇ ᴀɴᴅ sᴇᴇ ᴛʜᴇ ᴘʀᴇsᴇɴᴛ ᴘʀᴏᴍᴏᴛᴇᴅ ᴜsᴇʀs.</i></b></blockquote>",
                reply_markup=InlineKeyboardMarkup(btn)
            )

        # List Admins - FIXED: Removed reply_markup from answer()
        elif cb_data == "admin_list":
            if not is_admin_user:
                await callback_query.answer("Only admins can view admin list!", show_alert=True)
                return
            
            await callback_query.answer("Fᴇᴛᴄʜɪɴɢ ᴀᴅᴍɪɴ ʟɪsᴛ...")
            
            try:
                admin_ids = await Seishiro.list_admins()
                
                btn = [[InlineKeyboardButton("back", callback_data="admin_bna_system")]]
                
                if not admin_ids:
                    await callback_query.message.edit_text(
                        "<b>Nᴏ ᴀᴅᴍɪɴs ғᴏᴜɴᴅ.</b>",
                        reply_markup=InlineKeyboardMarkup(btn)
                    )
                    return
                
                admin_list = "<b>Aᴅᴍɪɴ Lɪsᴛ:</b>\n\n"
                for idx, admin_id in enumerate(admin_ids, 1):
                    try:
                        user = await client.get_users(admin_id)
                        admin_list += f"{idx}. {user.mention} (<code>{admin_id}</code>)\n"
                    except Exception:
                        admin_list += f"{idx}. <code>{admin_id}</code>\n"
                
                await callback_query.message.edit_text(
                    admin_list,
                    reply_markup=InlineKeyboardMarkup(btn)
                )
            except Exception as e:
                btn = [[InlineKeyboardButton("back", callback_data="admin_bna_system")]]
                await callback_query.message.edit_text(
                    f"<b>Eʀʀᴏʀ ғᴇᴛᴄʜɪɴɢ ᴀᴅᴍɪɴ ʟɪsᴛ:</b> {str(e)}",
                    reply_markup=InlineKeyboardMarkup(btn)
                )
        
        elif cb_data == "add_channel":
            if not is_admin_user:
                await callback_query.answer("Only admins can add channels!", show_alert=True)
                return
                
            btn = [[InlineKeyboardButton("back", callback_data="settings_main")]]
            await callback_query.message.edit_text(
                "<b>Sᴇɴᴅ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ ID ᴛᴏ ᴀᴅᴅ (e.g., -100123456789):\n\n/cancel ᴛᴏ ᴄᴀɴᴄᴇʟ</b>",
                reply_markup=InlineKeyboardMarkup(btn)
            )
                
            try:
                msg = await client.listen(chat_id=callback_query.message.chat.id, timeout=300)
                temp = await msg.reply("<i>Pʀᴏᴄᴇssɪɴɢ...</i>")
                await callback_query.message.delete()
                    
                if msg.text == '/cancel':
                    await temp.edit("ᴄᴀɴᴄᴇʟʟᴇᴅ!", reply_markup=InlineKeyboardMarkup(btn))
                    return
                        
                if not re.match(r"^-100\d{10,}$", msg.text):
                    await temp.edit(
                        "<b><blockquote expandable>Iɴᴠᴀʟɪᴅ ᴄʜᴀɴɴᴇʟ ID. Mᴜsᴛ ʙᴇ ɪɴ ᴛʜᴇ ғᴏʀᴍᴀᴛ -100XXXXXXXXXX.</blockquote></b>",
                        reply_markup=InlineKeyboardMarkup(btn)
                    )
                    return
                            
                channel_id = int(msg.text)
                            
                try:
                    chat_member = await client.get_chat_member(channel_id, client.me.id)
                    valid_statuses = [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
                                
                    if chat_member.status not in valid_statuses:
                        await temp.edit(
                            f"<b><blockquote expandable>I ᴀᴍ ɴᴏᴛ ᴀɴ ᴀᴅᴍɪɴ ᴏғ ᴛʜɪs ᴄʜᴀɴɴᴇʟ. Pʟᴇᴀsᴇ ᴍᴀᴋᴇ ᴍᴇ ᴀᴅᴍɪɴ ᴀɴᴅ ᴛʀʏ ᴀɢᴀɪɴ.</blockquote></b>",
                            reply_markup=InlineKeyboardMarkup(btn)
                        )
                        return
                except UserNotParticipant:
                    await temp.edit(
                        "<b><blockquote expandable>I ᴀᴍ ɴᴏᴛ ᴀ ᴍᴇᴍʙᴇʀ ᴏғ ᴛʜɪs ᴄʜᴀɴɴᴇʟ. Pʟᴇᴀsᴇ ᴀᴅᴅ ᴍᴇ ᴀɴᴅ ᴛʀʏ ᴀɢᴀɪɴ.</blockquote></b>",
                        reply_markup=InlineKeyboardMarkup(btn)
                    )
                    return
                except RPCError as e:
                    if "CHANNEL_INVALID" in str(e):
                        await temp.edit(
                            "<b><blockquote expandable>Iɴᴠᴀʟɪᴅ ᴄʜᴀɴɴᴇʟ ID. Pʟᴇᴀsᴇ ᴄʜᴇᴄᴋ ᴀɴᴅ ᴛʀʏ ᴀɢᴀɪɴ.</blockquote></b>",
                            reply_markup=InlineKeyboardMarkup(btn)
                        )
                        return
                    await temp.edit(
                        f"<b><blockquote expandable>Eʀʀᴏʀ: {str(e)}</blockquote></b>",
                        reply_markup=InlineKeyboardMarkup(btn)
                    )
                    return
                                    
                try:
                    chat = await client.get_chat(channel_id)
                except RPCError as e:
                    await temp.edit(
                        f"<b><blockquote expandable>Fᴀɪʟᴇᴅ ᴛᴏ ᴀᴄᴄᴇss ᴄʜᴀɴɴᴇʟ: {str(e)}</blockquote></b>",
                        reply_markup=InlineKeyboardMarkup(btn)
                    )
                    return
                                        
                await Seishiro.save_channel(channel_id)
                                        
                base64_invite = await encode(str(channel_id))
                await Seishiro.save_encoded_link(channel_id)
                                        
                base64_request = await encode(str(channel_id))
                await Seishiro.save_encoded_link2(channel_id, base64_request)
                                        
                normal_link = f"https://t.me/{client.username}?start={base64_invite}"
                request_link = f"https://t.me/{client.username}?start=req_{base64_request}"
                reply_text = (f"<b>Cʜᴀɴɴᴇʟ {chat.title} {channel_id} ʜᴀs ʙᴇᴇɴ ᴀᴅᴅᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ.</b>\n\n\n"
                              f"<blockquote><i>Nᴏᴡ ᴜsᴇ /genlink ᴏʀ /batch ᴄᴍᴅs ᴛᴏ ᴄʀᴇᴀᴛᴇ ɴᴏʀᴍᴀʟ ʟɪɴᴋs ᴀɴᴅ ʀᴇǫᴜᴇsᴛ ʟɪɴᴋs.</i></blockquote>")
                await temp.edit(reply_text, reply_markup=InlineKeyboardMarkup(btn))
                                    
            except asyncio.TimeoutError:
                await callback_query.message.reply(
                    "<b>Tɪᴍᴇᴏᴜᴛ! Pʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ.</b>",
                    reply_markup=InlineKeyboardMarkup(btn)
                )
            except Exception as e:
                print(f"Unexpected Error adding channel: {e}")
                await temp.edit(f"Unexpected Error: {str(e)}", reply_markup=InlineKeyboardMarkup(btn))
        
        # Delete Channel
        elif cb_data == "delete_channel":
            if not is_admin_user:
                await callback_query.answer("Only admins can delete channels!", show_alert=True)
                return
            
            btn = [[InlineKeyboardButton("back", callback_data="settings_main")]]
            await callback_query.message.edit_text(
                "<b>Sᴇɴᴅ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ ID ᴛᴏ ᴅᴇʟᴇᴛᴇ (e.g., -100123456789):\n\n/cancel ᴛᴏ ᴄᴀɴᴄᴇʟ</b>",
                reply_markup=InlineKeyboardMarkup(btn)
            )
            
            try:
                msg = await client.listen(chat_id=callback_query.message.chat.id, timeout=300)
                await callback_query.message.delete()
                
                if msg.text == '/cancel':
                    await msg.reply("ᴄᴀɴᴄᴇʟʟᴇᴅ!", reply_markup=InlineKeyboardMarkup(btn))
                    return
                
                channel_id = int(msg.text)
                await Seishiro.delete_channel(channel_id)
                await msg.reply(
                    f"<b><blockquote expandable>Cʜᴀɴɴᴇʟ {channel_id} ʜᴀs ʙᴇᴇɴ ʀᴇᴍᴏᴠᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ.</blockquote></b>",
                    reply_markup=InlineKeyboardMarkup(btn)
                )
            except (ValueError, IndexError):
                await msg.reply(
                    "<b><blockquote expandable>Iɴᴠᴀʟɪᴅ ᴄʜᴀɴɴᴇʟ ID. Pʟᴇᴀsᴇ sᴇɴᴅ ᴀ ᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ.</blockquote></b>",
                    reply_markup=InlineKeyboardMarkup(btn)
                )
            except Exception as e:
                print(f"Error deleting channel {msg.text}: {e}")
                await msg.reply(f"Unexpected Error: {str(e)}", reply_markup=InlineKeyboardMarkup(btn))
                
        elif cb_data == "channel_links":
            if not is_admin_user:
                await callback_query.answer("Only admins can access this!", show_alert=True)
                return
                
            channels = await Seishiro.get_channels()
            print(f"DEBUG: Found {len(channels)} channels for normal links: {channels}")
            
            if not channels:
                await callback_query.message.edit_text(
                    "<b><blockquote expandable>Nᴏ ᴄʜᴀɴɴᴇʟs ᴀʀᴇ ᴀᴠᴀɪʟᴀʙʟᴇ. Pʟᴇᴀsᴇ ᴜsᴇ 'Aᴅᴅ Cʜᴀɴɴᴇʟ' ᴛᴏ ᴀᴅᴅ ᴀ ᴄʜᴀɴɴᴇʟ.</blockquote></b>",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("back", callback_data="link_share")]])
                )
                return
            
            # Use edit=True to edit the existing message instead of sending new one
            await send_channel_page(client, callback_query.message, channels, page=0, edit=True)
            await callback_query.answer()
            
        elif cb_data == "request_links":
            if not is_admin_user:
                await callback_query.answer("Only admins can access this!", show_alert=True)
                return
                
            channels = await Seishiro.get_channels()
            print(f"DEBUG: Found {len(channels)} channels for request links: {channels}")
            
            if not channels:
                await callback_query.message.edit_text(
                    "<b><blockquote expandable>Nᴏ ᴄʜᴀɴɴᴇʟs ᴀʀᴇ ᴀᴠᴀɪʟᴀʙʟᴇ. Pʟᴇᴀsᴇ ᴜsᴇ 'Aᴅᴅ Cʜᴀɴɴᴇʟ' ᴛᴏ ᴀᴅᴅ ᴀ ᴄʜᴀɴɴᴇʟ.</blockquote></b>",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("back", callback_data="link_share")]])
                )
                return
            
            # Use edit=True to edit the existing message instead of sending new one
            await send_request_page(client, callback_query.message, channels, page=0, edit=True)
            await callback_query.answer()
        
        elif cb_data == "list_channels":
            channels = await Seishiro.get_channels()
            if not channels:
                await callback_query.answer(
                    "Nᴏ ᴄʜᴀɴɴᴇʟs ᴀʀᴇ ᴀᴠᴀɪʟᴀʙʟᴇ. Pʟᴇᴀsᴇ ᴜsᴇ 'Aᴅᴅ Cʜᴀɴɴᴇʟ' ᴛᴏ ᴀᴅᴅ ᴀ ᴄʜᴀɴɴᴇʟ.", show_alert=True
                )
                return
            status_msg = await callback_query.message.edit_text("<i>Please wait...</i>")
            await send_channel_ids_page(client, callback_query.message, channels, page=0, status_msg=status_msg)
            await callback_query.answer()
            
        # Channel Links Pagination
        elif cb_data.startswith("channelpage_"):
            page = int(cb_data.split("_")[1])
            channels = await Seishiro.get_channels()
            await send_channel_page(client, callback_query.message, channels, page, edit=True)
            await callback_query.answer()

        # Request Links Pagination
        elif cb_data.startswith("reqpage_"):
            page = int(cb_data.split("_")[1])
            channels = await Seishiro.get_channels()
            await send_request_page(client, callback_query.message, channels, page, edit=True)
            await callback_query.answer()

        # Channel IDs Pagination
        elif cb_data.startswith("channelids_"):
            page = int(cb_data.split("_")[1])
            channels = await Seishiro.get_channels()
            await send_channel_ids_page(client, callback_query.message, channels, page, edit=True)
            await callback_query.answer()

        # Add Admin
        elif cb_data == "admin_bna":
            if not is_admin_user:
                await callback_query.answer("Only admins can add admins!", show_alert=True)
                return
            
            btn = [[InlineKeyboardButton("back", callback_data="admin_bna_system")]]
            await callback_query.message.edit_text(
                "<b>Sᴇɴᴅ ᴛʜᴇ ᴜsᴇʀ ID ᴡʜɪᴄʜ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴍᴀᴋᴇ ᴀᴅᴍɪɴ (e.g., 123456789):\n\n/cancel ᴛᴏ ᴄᴀɴᴄᴇʟ</b>",
                reply_markup=InlineKeyboardMarkup(btn)
            )
            
            try:
                msg = await client.listen(chat_id=callback_query.message.chat.id, timeout=300)
                await callback_query.message.delete()
                
                if msg.text == '/cancel':
                    await msg.reply("ᴄᴀɴᴄᴇʟʟᴇᴅ!", reply_markup=InlineKeyboardMarkup(btn))
                    return
                
                user_id = int(msg.text)
                await Seishiro.add_admin(user_id)
                await msg.reply(
                    f"<b>Tʜɪs ɪᴅ {user_id} sᴜᴄᴄᴇssғᴜʟʟʏ ᴘʀᴏᴍᴏᴛᴇᴅ ᴛᴏ ᴀᴅᴍɪɴ. Success</b>",
                    reply_markup=InlineKeyboardMarkup(btn)
                )
            except (ValueError, IndexError):
                await msg.reply(
                    "<b><blockquote expandable>Iɴᴠᴀʟɪᴅ ᴜsᴇʀ ID. Pʟᴇᴀsᴇ sᴇɴᴅ ᴀ ᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ.</blockquote></b>",
                    reply_markup=InlineKeyboardMarkup(btn)
                )
            except Exception as e:
                print(f"Error in promoting admin: {e}")
                await msg.reply(f"Uɴᴇxᴘᴇᴄᴛᴇᴅ Eʀʀᴏʀ: {str(e)}", reply_markup=InlineKeyboardMarkup(btn))

        # Remove Admin
        elif cb_data == "admin_hta":
            if not is_admin_user:
                await callback_query.answer("Only admins can remove admins!", show_alert=True)
                return
            
            btn = [[InlineKeyboardButton("back", callback_data="admin_bna_system")]]
            await callback_query.message.edit_text(
                "<b>Sᴇɴᴅ ᴛʜᴇ ᴜsᴇʀ ID ᴛᴏ ʀᴇᴍᴏᴠᴇ ғʀᴏᴍ ᴀᴅᴍɪɴ (e.g., 123456789):\n\n/cancel ᴛᴏ ᴄᴀɴᴄᴇʟ</b>",
                reply_markup=InlineKeyboardMarkup(btn)
            )
            
            try:
                msg = await client.listen(chat_id=callback_query.message.chat.id, timeout=300)
                await callback_query.message.delete()
                
                if msg.text == '/cancel':
                    await msg.reply("ᴄᴀɴᴄᴇʟʟᴇᴅ!", reply_markup=InlineKeyboardMarkup(btn))
                    return

                user_id = int(msg.text)
                await Seishiro.remove_admin(user_id)
                await msg.reply(
                    f"<b>Tʜɪs ɪᴅ {user_id} sᴜᴄᴄᴇssғᴜʟʟʏ ᴅᴇᴘʀᴏᴍᴏᴛᴇᴅ ғʀᴏᴍ ᴀᴅᴍɪɴ. Success</b>",
                    reply_markup=InlineKeyboardMarkup(btn)
                )
            except (ValueError, IndexError):
                await msg.reply(
                    "<b><blockquote expandable>Iɴᴠᴀʟɪᴅ ᴜsᴇʀ ID. Pʟᴇᴀsᴇ sᴇɴᴅ ᴀ ᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ.</blockquote></b>",
                    reply_markup=InlineKeyboardMarkup(btn)
                )
            except Exception as e:
                print(f"Error in depromoting admin: {e}")
                await msg.reply(f"Uɴᴇxᴘᴇᴄᴛᴇᴅ Eʀʀᴏʀ: {str(e)}", reply_markup=InlineKeyboardMarkup(btn))

        else:
            # Unknown callback — silently ignore, let other handlers deal with it
            await callback_query.answer()
            return

    except Exception as e:
        print(f"Error in callback: {e}")
        await callback_query.message.edit_text(
            f"Unexpected Error: {str(e)}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("back", callback_data="settings_main")]])
        )
        
# Replace the send_channel_page function:

async def send_channel_page(client, message, channels, page, edit=False):
    """Display normal invite links for channels with pagination"""
    total_pages = max(1, (len(channels) + PAGE_SIZE - 1) // PAGE_SIZE)
    start_idx = page * PAGE_SIZE
    end_idx = start_idx + PAGE_SIZE
    buttons = []
    
    print(f"\n=== CHANNEL PAGE DEBUG ===")
    print(f"Total channels: {len(channels)}")
    print(f"Page: {page + 1}/{total_pages}")
    print(f"Processing channels: {channels[start_idx:end_idx]}")

    row = []
    for channel_id in channels[start_idx:end_idx]:
        try:
            print(f"\nProcessing channel: {channel_id}")
            
            # First, get the chat info
            try:
                chat = await client.get_chat(channel_id)
                print(f"Chat found: {chat.title}")
            except Exception as e:
                print(f"Error getting chat {channel_id}: {e}")
                continue
            
            # Get or create encoded link
            try:
                base64_invite = await Seishiro.get_encoded_link(channel_id)
                print(f"Retrieved encoded link: {base64_invite}")
            except Exception as e:
                print(f"Error getting encoded link: {e}")
                base64_invite = None
            
            if not base64_invite:
                print(f"No encoded link found, creating new one...")
                try:
                    base64_invite = await encode(str(channel_id))
                    await Seishiro.save_encoded_link(channel_id, base64_invite)
                    print(f"Created and saved new encoded link: {base64_invite}")
                except Exception as e:
                    print(f"Error creating encoded link: {e}")
                    continue
            
            # Create button link
            button_link = f"https://t.me/{client.username}?start={base64_invite}"
            print(f"Button link: {button_link}")
            
            # Add button to row
            button = InlineKeyboardButton(chat.title, url=button_link)
            row.append(button)
            print(f"Added button for {chat.title}")
            
            # When we have 2 buttons, add the row and start a new one
            if len(row) == 2:
                buttons.append(row)
                print(f"Added row with 2 buttons")
                row = []
                
        except Exception as e:
            print(f"FATAL Error for channel {channel_id}: {e}")
            import traceback
            traceback.print_exc()
            continue

    # Add remaining button if odd number of channels
    if row:
        buttons.append(row)
        print(f"Added final row with {len(row)} button(s)")

    print(f"\nTotal button rows created: {len(buttons)}")

    # Navigation buttons - only show if there are multiple pages
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◄ Pʀᴇᴠɪᴏᴜs", callback_data=f"channelpage_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Nᴇxᴛ ►", callback_data=f"channelpage_{page+1}"))
    
    # Only add navigation row if there are navigation buttons (more than 1 page)
    if nav_buttons:
        buttons.append(nav_buttons)
    
    # Back button only
    buttons.append([InlineKeyboardButton("‹ Bᴀᴄᴋ", callback_data="link_share")])

    reply_markup = InlineKeyboardMarkup(buttons)
    
    message_text = (
        f"<b>📢 Nᴏʀᴍᴀʟ Iɴᴠɪᴛᴇ Lɪɴᴋs</b>\n\n"
        f"<i>Cʟɪᴄᴋ ᴏɴ ᴀ ᴄʜᴀɴɴᴇʟ ʙᴜᴛᴛᴏɴ ᴛᴏ ɢᴇᴛ ɪᴛs ʟɪɴᴋ:</i>\n\n"
        f"<b>Pᴀɢᴇ {page + 1} ᴏғ {total_pages}</b>"
    )
    
    print(f"Sending message with {len(buttons)} button rows")
    
    try:
        if edit:
            await message.edit_text(message_text, reply_markup=reply_markup)
        else:
            await message.reply(message_text, reply_markup=reply_markup)
        print("Message sent successfully!")
    except Exception as e:
        print(f"Error sending message: {e}")
        raise


# Replace the send_request_page function:

async def send_request_page(client, message, channels, page, edit=False):
    """Display request invite links for channels with pagination"""
    total_pages = max(1, (len(channels) + PAGE_SIZE - 1) // PAGE_SIZE)
    start_idx = page * PAGE_SIZE
    end_idx = start_idx + PAGE_SIZE
    buttons = []
    
    print(f"\n=== REQUEST PAGE DEBUG ===")
    print(f"Total channels: {len(channels)}")
    print(f"Page: {page + 1}/{total_pages}")
    print(f"Processing channels: {channels[start_idx:end_idx]}")

    row = []
    for channel_id in channels[start_idx:end_idx]:
        try:
            print(f"\nProcessing request link for channel: {channel_id}")
            
            # First, get the chat info
            try:
                chat = await client.get_chat(channel_id)
                print(f"Chat found: {chat.title}")
            except Exception as e:
                print(f"Error getting chat {channel_id}: {e}")
                continue
            
            # Get or create encoded request link
            try:
                base64_request = await Seishiro.get_encoded_link2(channel_id)
                print(f"Retrieved encoded request link: {base64_request}")
            except Exception as e:
                print(f"Error getting encoded request link: {e}")
                base64_request = None
            
            if not base64_request:
                print(f"No encoded request link found, creating new one...")
                try:
                    base64_request = await encode(str(channel_id))
                    await Seishiro.save_encoded_link2(channel_id, base64_request)
                    print(f"Created and saved new request link: {base64_request}")
                except Exception as e:
                    print(f"Error creating encoded request link: {e}")
                    continue
            
            # Create button link with 'req_' prefix
            button_link = f"https://t.me/{client.username}?start=req_{base64_request}"
            print(f"Request button link: {button_link}")
            
            # Add button to row
            button = InlineKeyboardButton(chat.title, url=button_link)
            row.append(button)
            print(f"Added request button for {chat.title}")
            
            # When we have 2 buttons, add the row and start a new one
            if len(row) == 2:
                buttons.append(row)
                print(f"Added row with 2 buttons")
                row = []
                
        except Exception as e:
            print(f"FATAL Error for channel {channel_id}: {e}")
            import traceback
            traceback.print_exc()
            continue

    # Add remaining button if odd number of channels
    if row:
        buttons.append(row)
        print(f"Added final row with {len(row)} button(s)")

    print(f"\nTotal button rows created: {len(buttons)}")

    # Navigation buttons - only show if there are multiple pages
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◄ Pʀᴇᴠɪᴏᴜs", callback_data=f"reqpage_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Nᴇxᴛ ►", callback_data=f"reqpage_{page+1}"))
    
    # Only add navigation row if there are navigation buttons (more than 1 page)
    if nav_buttons:
        buttons.append(nav_buttons)
    
    # Back button only
    buttons.append([InlineKeyboardButton("‹ Bᴀᴄᴋ", callback_data="link_share")])

    reply_markup = InlineKeyboardMarkup(buttons)
    
    message_text = (
        f"<b>📩 Rᴇǫᴜᴇsᴛ Iɴᴠɪᴛᴇ Lɪɴᴋs</b>\n\n"
        f"<i>Cʟɪᴄᴋ ᴏɴ ᴀ ᴄʜᴀɴɴᴇʟ ʙᴜᴛᴛᴏɴ ᴛᴏ ɢᴇᴛ ɪᴛs ʀᴇǫᴜᴇsᴛ ʟɪɴᴋ:</i>\n\n"
        f"<b>Pᴀɢᴇ {page + 1} ᴏғ {total_pages}</b>"
    )
    
    print(f"Sending message with {len(buttons)} button rows")
    
    try:
        if edit:
            await message.edit_text(message_text, reply_markup=reply_markup)
        else:
            await message.reply(message_text, reply_markup=reply_markup)
        print("Message sent successfully!")
    except Exception as e:
        print(f"Error sending message: {e}")
        raise


# Replace send_channel_ids_page function:

async def send_channel_ids_page(client, message, channels, page, status_msg=None, edit=False):
    """Display channel IDs with names - paginated"""
    PAGE_SIZE_IDS = 10
    total_pages = max(1, (len(channels) + PAGE_SIZE_IDS - 1) // PAGE_SIZE_IDS)
    start_idx = page * PAGE_SIZE_IDS
    end_idx = start_idx + PAGE_SIZE_IDS
    
    text = "<b>📋 Cᴏɴɴᴇᴄᴛᴇᴅ Cʜᴀɴɴᴇʟs (ID & Nᴀᴍᴇ):</b>\n\n"
    
    for idx, channel_id in enumerate(channels[start_idx:end_idx], start=start_idx + 1):
        try:
            chat = await client.get_chat(channel_id)
            text += f"<b>{idx}. {chat.title}</b>\n<code>{channel_id}</code>\n\n"
        except Exception as e:
            text += f"<b>{idx}. Channel {channel_id}</b> (Error: {str(e)[:20]})\n\n"
    
    text += f"<b>Pᴀɢᴇ {page + 1} ᴏғ {total_pages}</b>"
    
    # Navigation buttons
    buttons = []
    nav_buttons = []
    
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◄ Pʀᴇᴠɪᴏᴜs", callback_data=f"channelids_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Nᴇxᴛ ►", callback_data=f"channelids_{page+1}"))
    
    if nav_buttons:
        buttons.append(nav_buttons)
    
    buttons.append([InlineKeyboardButton("‹ Bᴀᴄᴋ", callback_data="link_share")])
    
    reply_markup = InlineKeyboardMarkup(buttons)
    
    try:
        if edit:
            await message.edit_text(text, reply_markup=reply_markup)
        else:
            await message.reply(text, reply_markup=reply_markup)
        
        # Delete status message if provided
        if status_msg:
            try:
                await status_msg.delete()
            except:
                pass
    except Exception as e:
        print(f"Error in send_channel_ids_page: {e}")
        if status_msg:
            try:
                await status_msg.delete()
            except:
                pass
                
@Bot.on_message(filters.command('genlink') & filters.private & is_owner_or_admin)
async def gen_link_cmd(client: Bot, message: Message):
    if len(message.command) < 2:
        return await message.reply(
            "<b><blockquote expandable>ᴜsᴀɢᴇ: <code>/genlink -100123456789</code></blockquote></b>"
        )

    try:
        channel_id = int(message.command[1])

        # Check if channel is added
        if not await Seishiro.reqChannel_exist(channel_id):
            return await message.reply(
                "<b><blockquote expandable>ᴄʜᴀɴɴᴇʟ ɴᴏᴛ ғᴏᴜɴᴅ ɪɴ ᴀᴅᴅᴇᴅ ʟɪsᴛ.\n\n"
                "ғɪʀsᴛʟʏ ᴀᴅᴅ ʏᴏᴜʀ ᴄʜᴀɴɴᴇʟ ᴜsɪɴɢ <code>/settings →Lɪɴᴋ ᴍᴇɴᴜ → ᴀᴅᴅ ᴄʜᴀɴɴᴇʟ</code>\n"
                "ᴛʜᴇɴ ʏᴏᴜ ᴡɪʟʟ ʙᴇ ᴀʙʟᴇ ᴛᴏ ᴄʀᴇᴀᴛᴇ ʟɪɴᴋs ғᴏʀ ᴛʜᴀᴛ ɪᴅ.</blockquote></b>"
            )

        chat = await client.get_chat(channel_id)

        # Normal link
        base64_invite = await encode(str(channel_id))
        await Seishiro.save_encoded_link(channel_id)
        normal_link = f"https://t.me/{client.username}?start={base64_invite}"

        # Request link
        base64_request = await encode(str(channel_id))
        await Seishiro.save_encoded_link2(channel_id, base64_request)
        request_link = f"https://t.me/{client.username}?start=req_{base64_request}"

        reply_text = (
            f"<b><u>ʟɪɴᴋs ɢᴇɴᴇʀᴀᴛᴇᴅ:</u></b>\n\n"
            f"<b>ᴄʜᴀɴɴᴇʟ:</b> {chat.title}\n"
            f"<code>{channel_id}</code>\n\n"
            f"<b>ɴᴏʀᴍᴀʟ ʟɪɴᴋ:</b>\n<code>{normal_link}</code>\n\n"
            f"<b>ʀᴇǫᴜᴇsᴛ ʟɪɴᴋ:</b>\n<code>{request_link}</code>"
        )
        await message.reply(reply_text)

    except ValueError:
        await message.reply(
            "<b><blockquote expandable>ɪɴᴠᴀʟɪᴅ ᴄʜᴀɴɴᴇʟ ɪᴅ!\nᴜsᴇ ғᴏʀᴍᴀᴛ: <code>/genlink -100123456789</code></blockquote></b>"
        )
    except Exception as e:
        await message.reply(f"<b>ᴇʀʀᴏʀ:</b> <code>{str(e)}</code>")


# ═══════════════════════════════════════════════════════
# /linkalias - Channel Alias System
# Purana channel ban ho jaye → naye channel pe redirect
# ═══════════════════════════════════════════════════════

@Bot.on_message(filters.command('linkalias') & filters.private & is_owner_or_admin)
async def linkalias_cmd(client: Bot, message: Message):
    """
    Commands:
      /linkalias set <purana_id> <naya_id>   → Alias set karo
      /linkalias remove <purana_id>           → Alias hatao
      /linkalias list                         → Saare aliases dekho
    
    Example:
      /linkalias set -1003993344945 -1007282929287
    """
    args = message.command[1:]

    if not args:
        return await message.reply(
            "<b>🔀 Channel Alias System</b>\n\n"
            "<blockquote>"
            "Jab purana channel ban ho jaye, naye channel pe redirect karo.\n"
            "Purana wala link kaam karta rahega — users ko pata bhi nahi chalega!\n\n"
            "<b>Commands:</b>\n"
            "• <code>/linkalias set -100OLD_ID -100NEW_ID</code>\n"
            "• <code>/linkalias remove -100OLD_ID</code>\n"
            "• <code>/linkalias list</code>"
            "</blockquote>"
        )

    sub = args[0].lower()

    # ── SET ──────────────────────────────────────────────
    if sub == "set":
        if len(args) < 3:
            return await message.reply(
                "<b>Usage:</b> <code>/linkalias set -100OLD_ID -100NEW_ID</code>"
            )
        try:
            old_id = int(args[1])
            new_id = int(args[2])
        except ValueError:
            return await message.reply("<b>❌ Invalid channel IDs. Format: -100XXXXXXXXXX</b>")

        # Verify new channel accessible hai
        try:
            new_chat = await client.get_chat(new_id)
        except Exception as e:
            return await message.reply(
                f"<b>❌ New channel access nahi hua:</b> <code>{e}</code>\n\n"
                "<i>Bot ko new channel mein admin banana mat bhoolo!</i>"
            )

        # Old channel title try karo (banned ho sakta hai)
        try:
            old_chat = await client.get_chat(old_id)
            old_title = old_chat.title
        except Exception:
            old_title = str(old_id)

        ok = await Seishiro.set_channel_alias(old_id, new_id)
        if ok:
            await message.reply(
                f"<b>✅ Alias Set!</b>\n\n"
                f"<blockquote>"
                f"<b>Purana Channel:</b> {old_title}\n"
                f"<code>{old_id}</code>\n\n"
                f"<b>Naya Channel:</b> {new_chat.title}\n"
                f"<code>{new_id}</code>\n\n"
                f"Ab jo bhi purane link se aayega, naye channel ka invite milega.\n"
                f"<i>Purane links share karne ki zarurat nahi!</i>"
                f"</blockquote>"
            )
        else:
            await message.reply("<b>❌ Alias save karne mein error. Dobara try karo.</b>")

    # ── REMOVE ───────────────────────────────────────────
    elif sub == "remove":
        if len(args) < 2:
            return await message.reply(
                "<b>Usage:</b> <code>/linkalias remove -100OLD_ID</code>"
            )
        try:
            old_id = int(args[1])
        except ValueError:
            return await message.reply("<b>❌ Invalid channel ID.</b>")

        ok = await Seishiro.remove_channel_alias(old_id)
        if ok:
            await message.reply(
                f"<b>✅ Alias removed for <code>{old_id}</code></b>\n\n"
                f"<i>Ab purane link se koi redirect nahi hoga.</i>"
            )
        else:
            await message.reply(f"<b>⚠️ <code>{old_id}</code> ka koi alias nahi mila.</b>")

    # ── LIST ─────────────────────────────────────────────
    elif sub == "list":
        aliases = await Seishiro.list_channel_aliases()
        if not aliases:
            return await message.reply(
                "<b>📋 Koi alias set nahi hai.</b>\n\n"
                "<i>Use <code>/linkalias set</code> to add one.</i>"
            )

        text = "<b>🔀 Active Channel Aliases:</b>\n\n"
        for i, doc in enumerate(aliases, 1):
            # Try to get titles
            try:
                old_chat = await client.get_chat(doc['old_channel_id'])
                old_name = old_chat.title
            except Exception:
                old_name = "—"
            try:
                new_chat = await client.get_chat(doc['new_channel_id'])
                new_name = new_chat.title
            except Exception:
                new_name = "—"

            text += (
                f"<b>{i}.</b> <code>{doc['old_channel_id']}</code> ({old_name})\n"
                f"    ➜ <code>{doc['new_channel_id']}</code> ({new_name})\n\n"
            )

        await message.reply(text)

    else:
        await message.reply(
            "<b>❌ Unknown subcommand.</b>\n\n"
            "Use: <code>set</code>, <code>remove</code>, or <code>list</code>"
        )


@Bot.on_message(filters.command('batch') & is_owner_or_admin)
async def batch(client: Bot, message: Message):
    if len(message.command) < 2:
        return await message.reply(
            "<b><blockquote expandable>ᴜsᴀɢᴇ: <code>/batch -100123456789 -100987654321</code></blockquote></b>"
        )

    ids = message.command[1:]
    reply_text = "<b><u>ʙᴀᴛᴄʜ ʟɪɴᴋ ɢᴇɴᴇʀᴀᴛɪᴏɴ:</u></b>\n\n"

    for idx, id_str in enumerate(ids, start=1):
        try:
            channel_id = int(id_str)

            # Check if channel is added
            if not await Seishiro.reqChannel_exist(channel_id):
                reply_text += (
                    f"<b>{idx}. <code>{channel_id}</code></b>\n"
                    "<blockquote expandable>ᴄʜᴀɴɴᴇʟ ɴᴏᴛ ᴀᴅᴅᴇᴅ!\n"
                    "ᴜsᴇ <code>/settings →Lɪɴᴋ ᴍᴇɴᴜ → ᴀᴅᴅ ᴄʜᴀɴɴᴇʟ</code> ғɪʀsᴛ.</blockquote>\n\n"
                )
                continue

            chat = await client.get_chat(channel_id)

            # Normal link
            base64_invite = await encode(str(channel_id))
            await Seishiro.save_encoded_link(channel_id)
            normal_link = f"https://t.me/{client.username}?start={base64_invite}"

            # Request link
            base64_request = await encode(str(channel_id))
            await Seishiro.save_encoded_link2(channel_id, base64_request)
            request_link = f"https://t.me/{client.username}?start=req_{base64_request}"

            reply_text += (
                f"<b>{idx}. {chat.title}</b>\n"
                f"<code>{channel_id}</code>\n"
                f"<b>ɴᴏʀᴍᴀʟ:</b> <code>{normal_link}</code>\n"
                f"<b>ʀᴇǫᴜᴇsᴛ:</b> <code>{request_link}</code>\n\n"
            )

        except Exception as e:
            reply_text += f"<b>{idx}. {id_str}</b> - ᴇʀʀᴏʀ: <code>{str(e)}</code>\n\n"

    await message.reply(reply_text)


# ==================== FAKE LINK COMMANDS ====================
# Jojo multi-link system: multiple fake links, row positioning
# Commands: /setfakelink, /deletefakelink, /listfakelink
# Legacy (single-link): /removefakelink, /viewfakelink  ← pehle wale still work karte hain

@Bot.on_message(filters.command("setfakelink") & filters.private & is_owner_or_admin)
async def set_fake_link_command(client: Client, message: Message):
    """
    /setfakelink <url> <button_text> [row]
    Example: /setfakelink https://t.me/channel Join Mera Channel 2
    Row optional hai (default 1). Multiple links add ho sakte hain.
    """
    try:
        parts = message.text.split(maxsplit=2)

        if len(parts) < 3:
            await message.reply_text(
                "<b>❌ Gᴀʟᴀᴛ ғᴏʀᴍᴀᴛ!</b>\n\n"
                "<b>Usᴀɢᴇ:</b>\n"
                "<code>/setfakelink [URL] [Button Text] [Row]</code>\n\n"
                "<b>Exᴀᴍᴘʟᴇs:</b>\n"
                "<code>/setfakelink https://t.me/channel Join Mera Channel</code>\n"
                "<code>/setfakelink https://t.me/channel2 Another Button 2</code>\n\n"
                "<i>💡 Row optional (default 1). Multiple buttons add kar sakte ho!\n"
                "List dekhne ke liye /listfakelink</i>",
                parse_mode=ParseMode.HTML
            )
            return

        url = parts[1]
        rest = parts[2]

        # Last word row number hai agar integer ho
        row = 1
        rest_parts = rest.rsplit(maxsplit=1)
        if len(rest_parts) == 2 and rest_parts[1].isdigit():
            button_text = rest_parts[0]
            row = max(1, int(rest_parts[1]))
        else:
            button_text = rest

        if not url.startswith(('http://', 'https://', 't.me/')):
            await message.reply_text(
                "<b>❌ Iɴᴠᴀʟɪᴅ URL!</b>\n\n"
                "URL <code>http://</code>, <code>https://</code> ya <code>t.me/</code> se shuru hona chahiye.",
                parse_mode=ParseMode.HTML
            )
            return

        success = await Seishiro.add_fake_link(url, button_text, row)

        if success:
            total = len(await Seishiro.get_fake_links())
            await message.reply_text(
                "<b>✅ Fᴀᴋᴇ Lɪɴᴋ Aᴅᴅ Hᴏ Gᴀʏᴀ!</b>\n\n"
                f"<b>Bᴜᴛᴛᴏɴ Tᴇxᴛ:</b> <code>{button_text}</code>\n"
                f"<b>URL:</b> <code>{url}</code>\n"
                f"<b>Row:</b> <code>{row}</code>\n\n"
                f"<i>Total fake links: {total}. List ke liye /listfakelink</i>",
                parse_mode=ParseMode.HTML
            )
        else:
            await message.reply_text(
                "<b>❌ Eʀʀᴏʀ!</b> Fake link save nahi hua. Dobara try karo.",
                parse_mode=ParseMode.HTML
            )

    except Exception as e:
        logger.error(f"Error in set_fake_link_command: {e}")
        await message.reply_text(
            f"<b>❌ Eʀʀᴏʀ:</b>\n<code>{str(e)}</code>",
            parse_mode=ParseMode.HTML
        )


@Bot.on_message(filters.command("deletefakelink") & filters.private & is_owner_or_admin)
async def delete_fake_link_command(client: Client, message: Message):
    """
    /deletefakelink <number>
    Number /listfakelink se lo.
    """
    try:
        if len(message.command) < 2 or not message.command[1].isdigit():
            return await message.reply_text(
                "<b>❌ Usage:</b> <code>/deletefakelink [number]</code>\n\n"
                "Number dekhne ke liye <code>/listfakelink</code> use karo.",
                parse_mode=ParseMode.HTML
            )

        index = int(message.command[1])
        success = await Seishiro.remove_fake_link_by_index(index)

        if success:
            await message.reply_text(
                f"<b>✅ Fᴀᴋᴇ Lɪɴᴋ #{index} Hᴀᴛᴀ Dɪʏᴀ!</b>\n\n"
                "<i>Baki fake links jaise the waise hi hain.</i>",
                parse_mode=ParseMode.HTML
            )
        else:
            await message.reply_text(
                f"<b>❌ Fᴀᴋᴇ Lɪɴᴋ #{index} Nᴀʜɪ Mɪʟᴀ!</b>\n\n"
                "Valid number ke liye /listfakelink dekho.",
                parse_mode=ParseMode.HTML
            )

    except Exception as e:
        logger.error(f"Error in delete_fake_link_command: {e}")
        await message.reply_text(
            f"<b>❌ Eʀʀᴏʀ:</b>\n<code>{str(e)}</code>",
            parse_mode=ParseMode.HTML
        )


@Bot.on_message(filters.command("listfakelink") & filters.private & is_owner_or_admin)
async def list_fake_link_command(client: Client, message: Message):
    """View all fake links with index numbers."""
    try:
        fakes = await Seishiro.get_fake_links()

        if not fakes:
            return await message.reply_text(
                "<b>❌ Kᴏɪ Fᴀᴋᴇ Lɪɴᴋ Sᴇᴛ Nᴀʜɪ Hᴀɪ!</b>\n\n"
                "Set karne ke liye:\n"
                "<code>/setfakelink https://t.me/channel Button Text [row]</code>",
                parse_mode=ParseMode.HTML
            )

        lines = ["<b>📝 Fᴀᴋᴇ Lɪɴᴋs:</b>\n"]
        for i, fake in enumerate(fakes, 1):
            lines.append(
                f"<b>{i}.</b> <code>{fake['button_text']}</code>\n"
                f"   🔗 <code>{fake['url']}</code>\n"
                f"   📍 Row: <code>{fake['row']}</code>"
            )

        lines.append("\n<i>Delete karne ke liye: /deletefakelink (number)</i>")
        await message.reply_text("\n\n".join(lines), parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.error(f"Error in list_fake_link_command: {e}")
        await message.reply_text(
            f"<b>❌ Eʀʀᴏʀ:</b>\n<code>{str(e)}</code>",
            parse_mode=ParseMode.HTML
        )


# ── Legacy single-link commands (pehle wale — still work karte hain) ──

@Bot.on_message(filters.command("removefakelink") & filters.private & is_owner_or_admin)
async def remove_fake_link_command(client: Client, message: Message):
    """Legacy: sabhi fake links ek saath remove karo (purani wali DB bhi)."""
    try:
        # Purani single-link DB
        old_success = await Seishiro.remove_fake_link()
        # Nayi multi-link DB se bhi sab delete karo
        fakes = await Seishiro.get_fake_links()
        multi_success = False
        for i in range(len(fakes), 0, -1):
            await Seishiro.remove_fake_link_by_index(i)
            multi_success = True

        if old_success or multi_success:
            await message.reply_text(
                "<b>✅ Sᴀʙʜɪ Fᴀᴋᴇ Lɪɴᴋs Rᴇᴍᴏᴠᴇ Hᴏ Gᴀʏᴇ!</b>",
                parse_mode=ParseMode.HTML
            )
        else:
            await message.reply_text(
                "<b>❌ Kᴏɪ Fᴀᴋᴇ Lɪɴᴋ Sᴇᴛ Nᴀʜɪ Tʜᴀ!</b>",
                parse_mode=ParseMode.HTML
            )

    except Exception as e:
        logger.error(f"Error in remove_fake_link_command: {e}")
        await message.reply_text(
            f"<b>❌ Eʀʀᴏʀ:</b>\n<code>{str(e)}</code>",
            parse_mode=ParseMode.HTML
        )


@Bot.on_message(filters.command("viewfakelink") & filters.private & is_owner_or_admin)
async def view_fake_link_command(client: Client, message: Message):
    """Legacy alias for /listfakelink — multi links dikhata hai."""
    try:
        fakes = await Seishiro.get_fake_links()

        if fakes:
            lines = ["<b>📝 Fᴀᴋᴇ Lɪɴᴋ Sᴇᴛᴛɪɴɢs:</b>\n"]
            for i, fake in enumerate(fakes, 1):
                lines.append(
                    f"<b>{i}.</b> <code>{fake['button_text']}</code>\n"
                    f"   🔗 <code>{fake['url']}</code>\n"
                    f"   📍 Row: <code>{fake['row']}</code>"
                )
            lines.append("\n<i>Delete: /deletefakelink (number) | List: /listfakelink</i>")
            await message.reply_text("\n\n".join(lines), parse_mode=ParseMode.HTML)
        else:
            await message.reply_text(
                "<b>❌ Kᴏɪ Fᴀᴋᴇ Lɪɴᴋ Sᴇᴛ Nᴀʜɪ Hᴀɪ!</b>\n\n"
                "<i>Use <code>/setfakelink</code> to set a fake link.</i>",
                parse_mode=ParseMode.HTML
            )

    except Exception as e:
        logger.error(f"Error in view_fake_link_command: {e}")
        await message.reply_text(
            f"<b>❌ Eʀʀᴏʀ:</b>\n<code>{str(e)}</code>",
            parse_mode=ParseMode.HTML
        )


# ============================================================================
# CHANNEL REFRESH & CLEANUP COMMANDS
# ============================================================================

@Bot.on_message(filters.command('refresh_channels') & filters.private & is_owner_or_admin)
async def refresh_channels_command(client: Bot, message: Message):
    """Force refresh all channels to populate session cache"""
    
    status_msg = await message.reply_text(
        "<b>🔄 Rᴇғʀᴇsʜɪɴɢ ᴀʟʟ ᴄʜᴀɴɴᴇʟs...</b>\n\n"
        "<i>Tʜɪs ᴡɪʟʟ ғɪx 'Pᴇᴇʀ ɪᴅ ɪɴᴠᴀʟɪᴅ' ᴇʀʀᴏʀs</i>",
        parse_mode=ParseMode.HTML
    )
    
    try:
        channels = await Seishiro.get_channels()
        
        if not channels:
            return await status_msg.edit_text(
                "<b>❌ Nᴏ ᴄʜᴀɴɴᴇʟs ғᴏᴜɴᴅ ɪɴ ᴅᴀᴛᴀʙᴀsᴇ.</b>",
                parse_mode=ParseMode.HTML
            )
        
        resolved = 0
        failed = 0
        failed_list = []
        
        for idx, channel_id in enumerate(channels, 1):
            try:
                chat = await client.get_chat(channel_id)
                member = await client.get_chat_member(channel_id, "me")
                resolved += 1
                
                if idx % 5 == 0 or idx == len(channels):
                    await status_msg.edit_text(
                        f"<b>🔄 Rᴇғʀᴇsʜɪɴɢ... {(idx*100)//len(channels)}%</b>\n\n"
                        f"<i>Pʀᴏᴄᴇssᴇᴅ: {idx}/{len(channels)}</i>\n"
                        f"<i>✓ Sᴜᴄᴄᴇss: {resolved}</i>\n"
                        f"<i>✗ Fᴀɪʟᴇᴅ: {failed}</i>",
                        parse_mode=ParseMode.HTML
                    )
                    
            except PeerIdInvalid:
                failed += 1
                failed_list.append(f"{channel_id} (Peer invalid)")
            except Exception as e:
                failed += 1
                failed_list.append(f"{channel_id} ({str(e)[:30]})")
        
        summary = (
            f"<b>✅ Rᴇғʀᴇsʜ Cᴏᴍᴘʟᴇᴛᴇ!</b>\n\n"
            f"<b>📊 Rᴇsᴜʟᴛs:</b>\n"
            f"  • Tᴏᴛᴀʟ: {len(channels)}\n"
            f"  • ✓ Sᴜᴄᴄᴇss: {resolved}\n"
            f"  • ✗ Fᴀɪʟᴇᴅ: {failed}\n"
        )
        
        if failed_list:
            summary += f"\n<b>⚠️ Fᴀɪʟᴇᴅ ({len(failed_list)}):</b>\n"
            for item in failed_list[:5]:
                summary += f"  • {item}\n"
            if len(failed_list) > 5:
                summary += f"  • ...ᴀɴᴅ {len(failed_list)-5} ᴍᴏʀᴇ\n"
            summary += f"\n<i>Usᴇ /cleanup_db ᴛᴏ ʀᴇᴍᴏᴠᴇ ɪɴᴠᴀʟɪᴅ ᴄʜᴀɴɴᴇʟs</i>"
        
        await status_msg.edit_text(summary, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        await status_msg.edit_text(
            f"<b>❌ Eʀʀᴏʀ:</b>\n<code>{str(e)}</code>",
            parse_mode=ParseMode.HTML
        )


@Bot.on_message(filters.command('cleanup_db') & filters.private & is_owner_or_admin)
async def cleanup_database_command(client: Bot, message: Message):
    """Remove all invalid channels from database"""
    
    status_msg = await message.reply_text(
        "<b>🔄 Sᴄᴀɴɴɪɴɢ ᴅᴀᴛᴀʙᴀsᴇ...</b>",
        parse_mode=ParseMode.HTML
    )
    
    try:
        channels = await Seishiro.get_channels()
        
        if not channels:
            return await status_msg.edit_text(
                "<b>✅ Nᴏ ᴄʜᴀɴɴᴇʟs ғᴏᴜɴᴅ.</b>",
                parse_mode=ParseMode.HTML
            )
        
        valid_channels = []
        invalid_channels = []
        
        for idx, channel_id in enumerate(channels, 1):
            try:
                chat = await client.get_chat(channel_id)
                member = await client.get_chat_member(channel_id, "me")
                
                if member.status in ["administrator", "creator"]:
                    valid_channels.append(channel_id)
                else:
                    invalid_channels.append((channel_id, chat.title, f"Not admin"))
                    
            except PeerIdInvalid:
                invalid_channels.append((channel_id, "Unknown", "Peer invalid"))
            except Exception as e:
                invalid_channels.append((channel_id, "Unknown", str(e)[:40]))
            
            if idx % 10 == 0 or idx == len(channels):
                await status_msg.edit_text(
                    f"<b>🔄 Sᴄᴀɴɴɪɴɢ... {(idx*100)//len(channels)}%</b>\n\n"
                    f"<i>Pʀᴏᴄᴇssᴇᴅ: {idx}/{len(channels)}</i>",
                    parse_mode=ParseMode.HTML
                )
        
        if not invalid_channels:
            return await status_msg.edit_text(
                f"<b>✅ Aʟʟ {len(valid_channels)} ᴄʜᴀɴɴᴇʟs ᴀʀᴇ ᴠᴀʟɪᴅ!</b>",
                parse_mode=ParseMode.HTML
            )
        
        # Remove invalid channels automatically
        await status_msg.edit_text(
            f"<b>🗑️ Rᴇᴍᴏᴠɪɴɢ {len(invalid_channels)} ɪɴᴠᴀʟɪᴅ ᴄʜᴀɴɴᴇʟs...</b>",
            parse_mode=ParseMode.HTML
        )
        
        removed = 0
        for channel_id, _, _ in invalid_channels:
            try:
                await Seishiro.channel_data.delete_one({"channel_id": channel_id})
                removed += 1
            except Exception as e:
                print(f"Failed to remove {channel_id}: {e}")
        
        invalid_list = "\n".join([
            f"  • {name[:25]}... ({reason})"
            for _, name, reason in invalid_channels[:10]
        ])
        
        await status_msg.edit_text(
            f"<b>✅ Cʟᴇᴀɴᴜᴘ Cᴏᴍᴘʟᴇᴛᴇ!</b>\n\n"
            f"<b>Rᴇᴍᴏᴠᴇᴅ:</b> {removed} ᴄʜᴀɴɴᴇʟs\n"
            f"<b>Rᴇᴍᴀɪɴɪɴɢ:</b> {len(valid_channels)} ᴄʜᴀɴɴᴇʟs\n\n"
            f"<b>Rᴇᴍᴏᴠᴇᴅ (ғɪʀsᴛ 10):</b>\n{invalid_list}\n"
            f"{('...ᴀɴᴅ ' + str(len(invalid_channels)-10) + ' ᴍᴏʀᴇ') if len(invalid_channels) > 10 else ''}",
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        await status_msg.edit_text(
            f"<b>❌ Eʀʀᴏʀ:</b>\n<code>{str(e)}</code>",
            parse_mode=ParseMode.HTML
        )
