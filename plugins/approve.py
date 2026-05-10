import os
import asyncio
from bot import Bot
from config import *
from pyrogram import Client, filters
from pyrogram.types import Message, User, ChatJoinRequest, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, ChatAdminRequired, UserNotParticipant, UserAlreadyParticipant


async def _auto_send_files(client: Bot, user_id: int):
    """
    User ke join/approve ke baad uske pending link/files automatically bhejo.

    Flow:
    1. DB se user ka pending request doc lo (b64 encoded channel link)
    2. Uss b64 se fresh invite link banao
    3. User ko DM karo — koi button click nahi chahiye
    4. Purana 'HERE IS YOUR LINK' message delete karo (agar tha)
    """
    from database.database import Seishiro
    from helper_func import decode

    try:
        # Saare pending requests dhundo jis user ki abhi abhi join/approve hui
        pending_docs = await Seishiro.get_all_user_request_docs(user_id)

        if not pending_docs:
            # Koi pending request nahi — kuch nahi karna
            return

        for doc in pending_docs:
            channel_id  = doc.get("channel_id")
            invite_link = doc.get("invite_link")
            link_msg_id = doc.get("link_msg_id")
            link_chat_id = doc.get("link_chat_id")
            b64          = doc.get("b64")

            # ── Purana link message delete karo ──────────────────────
            if link_msg_id and link_chat_id:
                try:
                    await client.delete_messages(link_chat_id, link_msg_id)
                    print(f"🗑️ Deleted old link_msg {link_msg_id} for user {user_id}")
                except Exception as e:
                    print(f"⚠️ Could not delete old link_msg: {e}")

            # ── Invite link already saved hai toh use karo ───────────
            if not invite_link and channel_id:
                try:
                    # Fresh invite link banao
                    inv = await client.create_chat_invite_link(
                        chat_id=channel_id,
                        expire_date=None
                    )
                    invite_link = inv.invite_link
                except Exception as e:
                    print(f"⚠️ Could not create invite link for {channel_id}: {e}")

            # ── User ko DM bhejo ─────────────────────────────────────
            if invite_link:
                try:
                    # Channel title
                    try:
                        chat = await client.get_chat(channel_id)
                        ch_title = chat.title
                    except Exception:
                        ch_title = f"Channel ({channel_id})"

                    text = (
                        f"<b>✅ Yeh raha aapka link!</b>\n\n"
                        f"<blockquote>"
                        f"<b>Channel:</b> {ch_title}\n\n"
                        f"Niche button pe click karke channel join/access karein.\n"
                        f"<i>⚠️ Yeh message 5 minute mein auto-delete ho jayega.</i>"
                        f"</blockquote>"
                    )
                    buttons = [[InlineKeyboardButton("• ᴀᴄᴄᴇss ʟɪɴᴋ •", url=invite_link)]]

                    sent_msg = await client.send_message(
                        chat_id=user_id,
                        text=text,
                        reply_markup=InlineKeyboardMarkup(buttons)
                    )
                    print(f"✅ Auto-sent file/link to {user_id} for channel {channel_id}")

                    # 5 min baad cleanup
                    async def cleanup(msg=sent_msg, uid=user_id, cid=channel_id):
                        await asyncio.sleep(300)
                        try:
                            await msg.delete()
                        except Exception:
                            pass
                        try:
                            await Seishiro.delete_user_request_link(uid, cid)
                        except Exception:
                            pass

                    asyncio.create_task(cleanup())

                except Exception as e:
                    print(f"⚠️ Could not send auto-file to {user_id}: {e}")

            # DB cleanup
            try:
                await Seishiro.delete_user_request_link(user_id, channel_id)
            except Exception:
                pass

    except Exception as e:
        print(f"❌ _auto_send_files error for {user_id}: {e}")


@Client.on_chat_join_request((filters.group | filters.channel))
async def on_join_request(client: Bot, message: ChatJoinRequest):
    """
    🔥 SMART LOGIC:
    - FSub channels: Detect karo + DB mein save karo (auto-approve NAHI)
    - Normal channels: Auto-approve karo + files bhejo
    """
    from database.database import Seishiro

    chat = message.chat
    user = message.from_user

    print(f"📥 Join request from {user.first_name} ({user.id}) for {chat.title} ({chat.id})")

    try:
        is_fsub_channel = False
        fsub_channels = await Seishiro.get_fsub_channels()
        if chat.id in fsub_channels:
            is_fsub_channel = True
            print(f"✅ This is a FSUB channel")
        else:
            print(f"✅ This is a NORMAL channel")

        if is_fsub_channel:
            # FSub channel: sirf DB mein note karo — admin manually approve karega
            await Seishiro.req_user(chat.id, user.id)
            print(f"✅ FSUB: Added {user.id} to request database (NO auto-approve)")

        else:
            await asyncio.sleep(1)

            try:
                member = await client.get_chat_member(chat.id, user.id)
                if member.status in ["member", "administrator", "creator"]:
                    print(f"User {user.id} is already a member, skipping")
                    return
            except UserNotParticipant:
                pass
            except Exception as e:
                print(f"Error checking membership: {e}")
                return

            try:
                await client.approve_chat_join_request(chat_id=chat.id, user_id=user.id)
                print(f"✅ NORMAL: Auto-approved {user.first_name} ({user.id})")
                # ✅ Auto files bhejo — koi button click nahi chahiye
                await _auto_send_files(client, user.id)
            except UserAlreadyParticipant:
                print(f"User {user.id} is already a participant")
            except Exception as e:
                print(f"❌ Error approving: {e}")

    except Exception as e:
        print(f"❌ Error in on_join_request: {e}")


@Client.on_chat_member_updated((filters.group | filters.channel))
async def on_member_approved(client: Bot, update):
    """
    Jab koi bhi user channel join kare (direct ya admin approve kare):
    - DB cleanup karo
    - Automatically files/link bhej do — koi button click nahi chahiye
    """
    try:
        from database.database import Seishiro

        if not update.new_chat_member:
            return

        user = update.new_chat_member.user
        chat = update.chat

        old_status = update.old_chat_member.status if update.old_chat_member else None
        new_status = update.new_chat_member.status

        # Sirf tab trigger karo jab user newly joined ho
        if new_status in ["member", "administrator", "creator"] and old_status != new_status:
            print(f"📥 Member updated: {user.id} joined {chat.title} ({chat.id})")

            # FSub channel ka request DB cleanup
            try:
                exists = await Seishiro.req_user_exist(chat.id, user.id)
                if exists:
                    await Seishiro.del_req_user(chat.id, user.id)
                    print(f"✅ User {user.id} req DB se remove kiya for {chat.title}")
            except Exception as e:
                print(f"⚠️ Error cleaning request for {user.id}: {e}")

            # ✅ Automatically files/link bhej do — no button needed
            await _auto_send_files(client, user.id)

    except Exception as e:
        print(f"Error in on_member_approved: {e}")

