"""
plugins/autodel_panel.py — /settings -> Auto Delete
Bot ke bheje saare private-chat messages kitne time baad delete hon (autodel.py).
"""
import logging

from pyrogram import filters, StopPropagation
from pyrogram.errors import MessageNotModified
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

import autodel
from bot import Bot
from config import OWNER_ID
from database.database import Seishiro
from plugins.premium import _set_bot_config

logger = logging.getLogger(__name__)
OPTIONS = [(0, "Off"), (120, "2 min"), (300, "5 min"), (600, "10 min"), (1800, "30 min"), (3600, "1 hour"), (21600, "6 hours")]


def _label(sec: int) -> str:
    for v, l in OPTIONS:
        if v == sec:
            return l
    return f"{sec}s"


@Bot.on_callback_query(filters.regex(r"^autodel_"), group=-1)
async def autodel_callbacks(client: Bot, cq: CallbackQuery):
    uid = cq.from_user.id
    if not (uid == OWNER_ID or await Seishiro.is_admin(uid)):
        await cq.answer("Admins only", show_alert=True)
        raise StopPropagation
    parts = cq.data.split(":")
    try:
        if parts[0] == "autodel_adm":
            doc = await Seishiro.database["bot_config"].find_one({"_id": "main"}) or {}
            await _set_bot_config("auto_delete_admins", not bool(doc.get("auto_delete_admins", False)))
            autodel.reset_cache()
            await cq.answer("Saved")
        if parts[0] == "autodel_set":
            await _set_bot_config("auto_delete_seconds", max(0, int(parts[1])))
            autodel.reset_cache()
            await cq.answer("Saved")
        cur = await autodel.get_delay() if parts[0] != "autodel_set" else int(parts[1])
        adm_on = bool(((await Seishiro.database["bot_config"].find_one({"_id": "main"})) or {}).get("auto_delete_admins", False))
        rows, row = [], []
        for v, l in OPTIONS:
            row.append(InlineKeyboardButton(("✅ " if v == cur else "") + l, callback_data=f"autodel_set:{v}"))
            if len(row) == 3:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([InlineKeyboardButton(("🟢 Admin chats mein bhi: ON" if adm_on else "⚪ Admin chats mein bhi: OFF"),
                                          callback_data="autodel_adm")])
        rows.append([InlineKeyboardButton("back", callback_data="settings_main")])
        await cq.message.edit_text(
            "<b>Auto Delete</b>\n\n"
            f"Abhi: <b>{_label(cur)}</b>\n\n"
            "Bot user ko jo bhi message bhejta hai (private chat) wo itne time baad apne aap delete ho jata hai, "
            "taaki bot chat saaf rahe. Restart ke baad bhi chalta hai.\n"
            "<i>Broadcast, group/channel messages aur admin ki withdrawal requests delete nahi hotin.</i>\n\n"
            f"<b>Admin chats:</b> {'ON — admin/owner ke messages bhi delete honge' if adm_on else 'OFF — admin/owner ke messages (genlink, add channel ka link, batch, Short Link) delete nahi honge'}",
            reply_markup=InlineKeyboardMarkup(rows),
        )
    except MessageNotModified:
        pass
    except StopPropagation:
        raise
    except Exception as e:
        logger.error(f"autodel panel error: {e}", exc_info=True)
    try:
        await cq.answer()
    except Exception:
        pass
    raise StopPropagation
