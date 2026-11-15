"""
plugins/sync_admin.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Senpai Sync — admin panel (/settings -> Senpai Sync Menu, ya /sync)

  • ON/OFF, har reward/limit ka value (button -> number bhejo)
  • Stats, pending withdrawals
  • Withdrawal: "Mark Paid" ya "Reject + Refund" (user ko bot message jata hai)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import datetime
import logging

from bson import ObjectId
from pyrogram import filters, StopPropagation
from pyrogram.errors import MessageNotModified
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from bot import Bot
from config import OWNER_ID
from database.database import Seishiro
from plugins.premium import _set_bot_config
from plugins.sync_app import SYNC_SETTINGS, get_sync_settings, sync_stats, _col, _tx

logger = logging.getLogger(__name__)


async def _admin_ok(uid: int) -> bool:
    return uid == OWNER_ID or await Seishiro.is_admin(uid)


def _menu_text(st: dict) -> str:
    lines = "\n".join(f"• {SYNC_SETTINGS[k][1]}: <b>{st[k]}</b>" for k in SYNC_SETTINGS)
    return (
        "<b>Senpai Sync Menu</b>\n\n"
        f"• Status: <b>{'ON' if st['enabled'] else 'OFF'}</b>\n{lines}\n\n"
        "<i>SP = Sync Points. Rs value = points / Points per Rs.</i>"
    )


def _menu_kb(st: dict) -> InlineKeyboardMarkup:
    keys = list(SYNC_SETTINGS)
    rows = [[InlineKeyboardButton("Turn OFF" if st["enabled"] else "Turn ON", callback_data="sync_toggle")]]
    for i in range(0, len(keys), 2):
        rows.append([InlineKeyboardButton(SYNC_SETTINGS[k][1].split(" (")[0], callback_data=f"sync_set:{k}")
                     for k in keys[i:i + 2]])
    rows.append([InlineKeyboardButton("Withdrawals", callback_data="sync_wd"),
                 InlineKeyboardButton("Stats", callback_data="sync_stats")])
    rows.append([InlineKeyboardButton("back", callback_data="settings_main")])
    return InlineKeyboardMarkup(rows)


async def _show_menu(msg):
    st = await get_sync_settings()
    await msg.edit_text(_menu_text(st), reply_markup=_menu_kb(st))


@Bot.on_message(filters.command("sync") & filters.private)
async def cmd_sync(client: Bot, msg: Message):
    if not await _admin_ok(msg.from_user.id):
        return await msg.reply("Only admins can use this.")
    st = await get_sync_settings()
    await msg.reply(_menu_text(st), reply_markup=_menu_kb(st))


@Bot.on_callback_query(filters.regex(r"^sync_"), group=-1)
async def sync_callbacks(client: Bot, cq: CallbackQuery):
    if not await _admin_ok(cq.from_user.id):
        await cq.answer("Admins only", show_alert=True)
        raise StopPropagation
    parts = cq.data.split(":")
    cmd = parts[0]
    try:
        if cmd == "sync_menu":
            await _show_menu(cq.message)

        elif cmd == "sync_toggle":
            st = await get_sync_settings()
            await _set_bot_config("sync_enabled", not st["enabled"])
            await cq.answer("Senpai Sync ON" if not st["enabled"] else "Senpai Sync OFF")
            await _show_menu(cq.message)

        elif cmd == "sync_set":
            key = parts[1]
            if key not in SYNC_SETTINGS:
                raise StopPropagation
            default, label, lo, hi = SYNC_SETTINGS[key]
            st = await get_sync_settings()
            await cq.message.edit_text(
                f"<b>{label}</b>\n\nAbhi: <b>{st[key]}</b>\nAllowed: {lo} - {hi}\n\n"
                "Naya number bhejo.\n<i>/cancel — cancel</i>",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("back", callback_data="sync_menu")]]),
            )
            try:
                resp = await client.listen(chat_id=cq.message.chat.id, timeout=300)
            except Exception:
                resp = None
            if resp:
                txt = (resp.text or "").strip()
                try:
                    await resp.delete()
                except Exception:
                    pass
                if txt.isdigit() and lo <= int(txt) <= hi:
                    await _set_bot_config(f"sync_{key}", int(txt))
                elif txt.lower() != "/cancel":
                    await cq.message.reply(f"Number {lo} se {hi} ke beech hona chahiye.")
            await _show_menu(cq.message)

        elif cmd == "sync_stats":
            s = await sync_stats()
            st = await get_sync_settings()
            await cq.message.edit_text(
                "<b>Senpai Sync Stats</b>\n\n"
                f"• Users: <b>{s['users']}</b>\n"
                f"• Total points issued: <b>{s['earned_pts']}</b> SP\n"
                f"• Points balance (liability): <b>{s['balance_pts']}</b> SP "
                f"(~Rs {round(s['balance_pts'] / st['points_per_inr'], 2)})\n"
                f"• Pending withdrawals: <b>{s['pending']}</b>\n"
                f"• Paid so far: <b>Rs {s['paid_inr']}</b>\n\n"
                "<i>Liability = users ko dena hoga agar sab withdraw karein. "
                "Ise Monetag earnings se kam rakho.</i>",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("back", callback_data="sync_menu")]]),
            )

        elif cmd == "sync_wd":
            rows = await _col("sync_withdrawals").find({"status": "pending"}).sort("created", 1).limit(8).to_list(8)
            if not rows:
                await cq.answer("Koi pending withdrawal nahi", show_alert=True)
                raise StopPropagation
            kb = [[InlineKeyboardButton(f"Rs {r['inr']} - {r.get('name', '')[:14]}", callback_data=f"sync_wdv:{r['_id']}")]
                  for r in rows]
            kb.append([InlineKeyboardButton("back", callback_data="sync_menu")])
            await cq.message.edit_text("<b>Pending withdrawals</b>\n\nEk chuno:", reply_markup=InlineKeyboardMarkup(kb))

        elif cmd == "sync_wdv":
            r = await _col("sync_withdrawals").find_one({"_id": ObjectId(parts[1])})
            if not r:
                await cq.answer("Nahi mila", show_alert=True)
                raise StopPropagation
            await cq.message.edit_text(
                f"<b>Withdrawal</b>\n\n<blockquote><b>User:</b> {r.get('name', '')} (<code>{r['uid']}</code>)\n"
                f"<b>Amount:</b> Rs {r['inr']} ({r['points']} SP)\n<b>UPI:</b> <code>{r['upi']}</code>\n"
                f"<b>Status:</b> {r['status']}</blockquote>",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Mark Paid", callback_data=f"syncwd_ok:{r['_id']}"),
                     InlineKeyboardButton("Reject + Refund", callback_data=f"syncwd_no:{r['_id']}")],
                    [InlineKeyboardButton("back", callback_data="sync_wd")],
                ]) if r["status"] == "pending" else InlineKeyboardMarkup(
                    [[InlineKeyboardButton("back", callback_data="sync_wd")]]),
            )
        else:
            await cq.answer()
    except StopPropagation:
        raise
    except MessageNotModified:
        pass
    except Exception as e:
        logger.error(f"sync admin callback error ({cq.data}): {e}", exc_info=True)
        try:
            await cq.answer("Error, dobara try karo", show_alert=True)
        except Exception:
            pass
    try:
        await cq.answer()
    except Exception:
        pass
    raise StopPropagation


@Bot.on_callback_query(filters.regex(r"^syncwd_(ok|no):"), group=-1)
async def withdrawal_decision(client: Bot, cq: CallbackQuery):
    if not await _admin_ok(cq.from_user.id):
        await cq.answer("Admins only", show_alert=True)
        raise StopPropagation
    action, wd_id = cq.data.split(":", 1)
    approve = action == "syncwd_ok"
    try:
        # atomic: sirf pending ko hi badlo (double-click safe)
        wd = await _col("sync_withdrawals").find_one_and_update(
            {"_id": ObjectId(wd_id), "status": "pending"},
            {"$set": {"status": "paid" if approve else "rejected",
                      "decided": datetime.datetime.utcnow(), "decided_by": cq.from_user.id}})
        if not wd:
            await cq.answer("Ye request pehle hi process ho chuki hai", show_alert=True)
            raise StopPropagation
        if approve:
            text = f"<b>Withdrawal paid:</b> Rs {wd['inr']} sent to <code>{wd['upi']}</code>. Thank you for using Senpai Sync."
        else:
            await _col("sync_users").update_one({"_id": wd["uid"]}, {"$inc": {"points": wd["points"]}})
            await _tx(wd["uid"], "refund", wd["points"], "Withdrawal rejected")
            text = f"<b>Withdrawal rejected:</b> Rs {wd['inr']} request was not approved. {wd['points']} SP refunded to your balance."
        try:
            await client.send_message(wd["uid"], text)
        except Exception:
            pass
        await cq.answer("Marked paid" if approve else "Rejected and refunded", show_alert=True)
        try:
            await cq.message.edit_text(
                f"<b>Withdrawal {'PAID' if approve else 'REJECTED'}</b>\n\n"
                f"<blockquote>{wd.get('name', '')} (<code>{wd['uid']}</code>) - Rs {wd['inr']}\n"
                f"UPI: <code>{wd['upi']}</code></blockquote>")
        except Exception:
            pass
    except StopPropagation:
        raise
    except Exception as e:
        logger.error(f"withdrawal decision error: {e}", exc_info=True)
        await cq.answer("Error", show_alert=True)
    raise StopPropagation
