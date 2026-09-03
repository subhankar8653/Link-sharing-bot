import base64
import re
import asyncio
from pyrogram import filters
from pyrogram.enums import ChatMemberStatus
from pyrogram.errors.exceptions.bad_request_400 import UserNotParticipant
from pyrogram.errors import FloodWait
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.filters import Filter
from config import *
from database.database import Seishiro

async def encode(string):
    string_bytes = string.encode("ascii")
    base64_bytes = base64.urlsafe_b64encode(string_bytes)
    base64_string = (base64_bytes.decode("ascii")).strip("=")
    return base64_string

async def decode(base64_string):
    base64_string = base64_string.strip("=")
    base64_bytes = (base64_string + "=" * (-len(base64_string) % 4)).encode("ascii")
    string_bytes = base64.urlsafe_b64decode(base64_bytes)
    string = string_bytes.decode("ascii")
    return string

async def revoke_fsub_channel_link(client, channel_id: int) -> bool:
    """
    Channel ko FSub se remove karte waqt call karo — jis invite link se
    members join/request kar rahe the (current_invite_link), usko Telegram
    par revoke kar do taaki purana link kaam na kare, aur cache clear kar do.
    Channel remove ho chuka ho ya bot admin na ho tab bhi silently continue karta hai.
    """
    try:
        cached = await Seishiro.get_current_invite_link(channel_id)
        if cached and cached.get("invite_link"):
            try:
                await client.revoke_chat_invite_link(channel_id, cached["invite_link"])
            except Exception:
                pass  # link already invalid/expired, or bot no longer admin — ignore
        await Seishiro.clear_invite_link(channel_id)
        return True
    except Exception:
        return False


def get_readable_time(seconds: int) -> str:
    count = 0
    up_time = ""
    time_list = []
    time_suffix_list = ["s", "m", "h", "days"]
    while count < 4:
        count += 1
        remainder, result = divmod(seconds, 60) if count < 3 else divmod(seconds, 24)
        if seconds == 0 and remainder == 0:
            break
        time_list.append(int(result))
        seconds = int(remainder)
    hmm = len(time_list)
    for x in range(hmm):
        time_list[x] = str(time_list[x]) + time_suffix_list[x]
    if len(time_list) == 4:
        up_time += f"{time_list.pop()}, "
    time_list.reverse()
    up_time += ":".join(time_list)
    return up_time
