"""
plugins/fsub_extra.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FSub extras (Sufistobot se port) — /settings → Fsub Menu ke andar:

  • Button Layout     : 1 Row = 1 Button  /  1 Row = 2 Buttons
  • Edit Fsub Text    : fsub screen ka text + photo (placeholders, preview, reset)
  • Auto Remove / Link Rotate (per channel):
        - remove time   : kisi time par channel fsub se hat jaye
        - request target: itne NAYE requests/joins ke baad auto remove
        - link rotation : har N ghante naya invite link, purana expire
  • Maintenance loop  : har 60s mein upar ke rules check karta hai
Channel kisi bhi tarah fsub se hate (manual / auto) — uska invite link expire hota hai.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import asyncio
import html
import logging
import re
from datetime import datetime, timedelta

from pyrogram import filters, StopPropagation
from pyrogram.errors import FloodWait, MessageNotModified
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from bot import Bot
from config import OWNER_ID, FSUB_PIC
from database.database import Seishiro
from helper_func import revoke_fsub_channel_link

logger = logging.getLogger(__name__)

TZ_OFFSET = timedelta(minutes=330)   # IST (UTC+05:30)
TZ_LABEL = "UTC+05:30"
FSUB_TEXT_MAX = 700                   # photo caption limit (1024) se safe
ROTATE_OPTIONS = [("Off", 0), ("1h", 1), ("3h", 3), ("6h", 6), ("12h", 12), ("24h", 24)]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PURE HELPERS (start.py bhi use karta hai)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fmt_local(dt_utc: datetime) -> str:
    return (dt_utc + TZ_OFFSET).strftime("%d %b %Y, %I:%M %p")


def parse_remove_time(text: str):
    """6h | 1d 12h | 90m (abhi se) · 12:00 | 6:30 pm (agli baar) · 25-12-2026 18:30 (exact). Past/invalid -> None."""
    t = (text or "").strip().lower()
    if not t:
        return None
    now = datetime.utcnow()
    result = None
    if re.fullmatch(r"(?:\s*\d+\s*[dhm]\s*)+", t):
        mins = sum(int(n) * {"d": 1440, "h": 60, "m": 1}[u] for n, u in re.findall(r"(\d+)\s*([dhm])", t))
        result = now + timedelta(minutes=mins) if mins > 0 else None
    else:
        for fmt in ("%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M", "%d-%m-%Y %I:%M %p"):
            try:
                result = datetime.strptime(t, fmt) - TZ_OFFSET
                break
            except ValueError:
                continue
        if result is None:
            for fmt in ("%H:%M", "%I:%M %p", "%I %p"):
                try:
                    hm = datetime.strptime(t, fmt)
                except ValueError:
                    continue
                now_local = now + TZ_OFFSET
                cand = now_local.replace(hour=hm.hour, minute=hm.minute, second=0, microsecond=0)
                if cand <= now_local:
                    cand += timedelta(days=1)
                result = cand - TZ_OFFSET
                break
    if result is None or result <= now:
        return None
    return result


def render_fsub_text(text: str, user) -> str:
    """Admin ka likha text -> safe HTML (hamesha bold). Placeholders: {mention} {first} {last} {id} {username}"""
    safe = html.escape((text or "").strip(), quote=False)
    first = getattr(user, "first_name", "") or ""
    last = getattr(user, "last_name", "") or ""
    uname = getattr(user, "username", "") or ""
    mention = getattr(user, "mention", None) or html.escape(first or "User", quote=False)
    mapping = {
        "{mention}": mention,
        "{first}": html.escape(first, quote=False),
        "{last}": html.escape(last, quote=False),
        "{id}": str(getattr(user, "id", "")),
        "{username}": f"@{uname}" if uname else "",
    }
    for k, v in mapping.items():
        safe = safe.replace(k, v)
    return f"<b>{safe}</b>"


def limit_progress(doc: dict) -> int:
    """Target set hone ke baad aaye naye requests (request mode) ya joins (normal mode)."""
    if doc.get("mode", "off") == "on":
        return doc.get("request_count", 0) - doc.get("limit_base_req", 0)
    return doc.get("join_count", 0) - doc.get("limit_base_join", 0)


async def _is_admin(uid: int) -> bool:
    return uid == OWNER_ID or await Seishiro.is_admin(uid)


async def _title(client, cid: int) -> str:
    try:
        chat = await client.get_chat(cid)
        return chat.title or str(cid)
    except Exception:
        return str(cid)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AUTO REMOVE / LIMIT / ROTATION  (engine)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def remove_channel_now(client, cid: int, reason: str) -> bool:
    """Channel ko fsub se hatao AUR uska invite link expire karo."""
    doc = await Seishiro.get_fsub_doc(cid)
    if not doc:
        return False
    title = await _title(client, cid)
    await revoke_fsub_channel_link(client, cid)
    await Seishiro.remove_fsub_channel(cid)
    logger.info(f"[fsub] channel {cid} auto-removed ({reason})")
    try:
        await client.send_message(
            OWNER_ID,
            "<b>Channel auto-removed from Fsub</b>\n\n"
            f"<blockquote><b>Channel:</b> {html.escape(title)}\n<code>{cid}</code>\n"
            f"<b>Reason:</b> {reason}\n\nIts invite link has been expired.</blockquote>",
        )
    except Exception:
        pass
    return True


async def rotate_link(client, cid: int) -> bool:
    """Naya permanent link banao, phir purana expire karo."""
    old = await Seishiro.get_current_invite_link(cid)
    if not old or not old.get("invite_link"):
        return False
    is_request = (await Seishiro.get_channel_mode(cid)) == "on"
    inv = None
    for _ in range(3):
        try:
            inv = await client.create_chat_invite_link(chat_id=cid, creates_join_request=is_request)
            break
        except FloodWait as fw:
            await asyncio.sleep(fw.value + 2)
        except Exception as e:
            logger.error(f"[fsub] rotate create failed ({cid}): {e}")
            return False
    if inv is None:
        return False
    await Seishiro.save_invite_link(cid, inv.invite_link, is_request)
    try:
        await client.revoke_chat_invite_link(cid, old["invite_link"])
    except Exception:
        pass
    await Seishiro.mark_fsub_rotated(cid)
    logger.info(f"[fsub] rotated invite link of {cid}")
    return True


async def maintenance_tick(client):
    now = datetime.utcnow()
    for doc in await Seishiro.get_all_fsub_docs():
        cid = doc.get("channel_id")
        if cid is None:
            continue
        try:
            remove_at = doc.get("remove_at")
            if remove_at and now >= remove_at:
                await remove_channel_now(client, cid, "scheduled removal time reached")
                continue
            limit = doc.get("request_limit") or 0
            if limit and limit_progress(doc) >= limit:
                kind = "requests" if doc.get("mode", "off") == "on" else "joins"
                await remove_channel_now(client, cid, f"target of {limit} {kind} reached")
                continue
            hours = doc.get("rotate_hours") or 0
            since = doc.get("rotate_since")
            if hours and since and now - since >= timedelta(hours=hours):
                await rotate_link(client, cid)
        except Exception as e:
            logger.error(f"[fsub] maintenance error for {cid}: {e}")


_maint_task = None


async def _maintenance_loop(client):
    await asyncio.sleep(20)
    while True:
        try:
            await maintenance_tick(client)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[fsub] maintenance loop error: {e}")
        await asyncio.sleep(60)


def start_fsub_maintenance(client):
    """bot.py ke start() se ek baar call hota hai."""
    global _maint_task
    if _maint_task is None or _maint_task.done():
        _maint_task = asyncio.create_task(_maintenance_loop(client))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SETTINGS UI  (callbacks "fsx_*")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _back(to: str = "fsub_settings_menu"):
    return [InlineKeyboardButton("back", callback_data=to)]


async def _ask(client, cq: CallbackQuery, prompt: str, back_to: str, allow_photo: bool = False):
    """Admin se input maango. Returns message ya None (cancel/timeout)."""
    await cq.message.edit_text(
        prompt + "\n\n<i>/cancel — cancel karne ke liye</i>",
        reply_markup=InlineKeyboardMarkup([_back(back_to)]),
    )
    try:
        resp = await client.listen(chat_id=cq.message.chat.id, timeout=300)
    except Exception:
        return None
    txt = (resp.text or "").strip()
    if txt.lower() == "/cancel" or (not txt and not (allow_photo and resp.photo)):
        try:
            await resp.delete()
        except Exception:
            pass
        return None
    return resp


async def _show_text_menu(cq: CallbackQuery):
    ui = await Seishiro.get_fsub_ui()
    cur = ui["text"]
    pic = ui["pic"]
    pic_txt = "None (text only)" if pic == "none" else ("Custom" if pic else "Default")
    shown = f"<blockquote>{html.escape(cur, quote=False)}</blockquote>" if cur else "<i>Default text</i>"
    await cq.message.edit_text(
        "<b>Fsub Text</b>\n\n"
        "<blockquote>Ye wo text hai jo user ko join buttons ke <b>upar</b> dikhta hai. "
        "Hamesha <b>bold</b> mein dikhega.\n\n"
        "Placeholders: <code>{mention}</code> <code>{first}</code> <code>{last}</code> "
        "<code>{id}</code> <code>{username}</code></blockquote>\n"
        f"<b>Photo:</b> {pic_txt}\n<b>Current:</b>\n{shown}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Edit Text", callback_data="fsx_txte"),
             InlineKeyboardButton("Photo", callback_data="fsx_pic")],
            [InlineKeyboardButton("Preview", callback_data="fsx_prev"),
             InlineKeyboardButton("Reset to Default", callback_data="fsx_txtr")],
            _back(),
        ]),
    )


async def _send_preview(client, user, chat_id: int, back_markup=None):
    ui = await Seishiro.get_fsub_ui()
    custom = ui["text"].strip()
    caption = render_fsub_text(custom, user) if custom else (
        "<b>Welcome!\n\n<blockquote>Links pane ke liye niche diye gaye "
        "channels join karein ya request karein.</blockquote></b>"
    )
    layout = await Seishiro.get_fsub_layout()
    channels = (await Seishiro.get_fsub_channels())[:6] or [0, 0, 0]
    btns = []
    for i, cid in enumerate(channels, start=1):
        mode = await Seishiro.get_channel_mode(cid) if cid else "off"
        name = await Seishiro.get_fsub_channel_name(cid) if cid else None
        if layout == 2:
            text = name or f"⚡ {'Req' if mode == 'on' else 'Join'} Channel {i} ⚡"
        else:
            text = name or f"⚡ {'Request' if mode == 'on' else 'Join'} channel {i:02d} ⚡"
        btns.append(InlineKeyboardButton(text, url="https://t.me/telegram"))
    rows = [btns[i:i + 2] for i in range(0, len(btns), 2)] if layout == 2 else [[b] for b in btns]
    rows.append([InlineKeyboardButton("• Jᴏɪɴᴇᴅ •", url="https://t.me/telegram")])
    if back_markup:
        rows.extend(back_markup.inline_keyboard)
    markup = InlineKeyboardMarkup(rows)

    await client.send_message(chat_id, "<b>Preview — users ko aisa dikhega:</b>")
    pic = ui["pic"] if ui["pic"] else FSUB_PIC
    if pic != "none":
        try:
            await client.send_photo(chat_id, photo=pic, caption=caption, reply_markup=markup)
            return
        except Exception as e:
            await client.send_message(chat_id, f"<b>Photo send nahi hui</b> (<code>{str(e)[:100]}</code>). Text-only dikhega:")
    await client.send_message(chat_id, caption, reply_markup=markup)


async def _show_channel_sched(cq: CallbackQuery, cid: int):
    doc = await Seishiro.get_fsub_doc(cid)
    if not doc:
        await cq.answer("Channel nahi mila (shayad remove ho chuka).", show_alert=True)
        return
    title = html.escape(await _title(cq._client, cid))
    mode = doc.get("mode", "off")
    remove_at = doc.get("remove_at")
    remove_line = f"{fmt_local(remove_at)} ({TZ_LABEL})" if remove_at else "Not set"
    limit = doc.get("request_limit") or 0
    if limit:
        kind = "requests" if mode == "on" else "joins"
        limit_line = f"{max(0, limit_progress(doc))} / {limit} {kind}"
    else:
        limit_line = "Not set"
    hours = doc.get("rotate_hours") or 0
    rot_line = f"Every {hours}h" if hours else "Off"
    rot_row = [InlineKeyboardButton(f"{lbl}{' ✅' if hours == h else ''}", callback_data=f"fsx_rot:{cid}:{h}")
               for lbl, h in ROTATE_OPTIONS]
    await cq.message.edit_text(
        "<b>Auto Remove & Link Rotation</b>\n\n"
        f"<blockquote><b>Channel:</b> {title}\n<code>{cid}</code> — {'Request' if mode == 'on' else 'Normal'}\n\n"
        f"<b>Auto-remove at:</b> {remove_line}\n"
        f"<b>Target:</b> {limit_line}\n"
        f"<b>Link rotation:</b> {rot_line}</blockquote>\n"
        "<i>Channel fsub se jaise bhi hate (manual/auto), uska invite link expire ho jata hai.</i>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Set Remove Time", callback_data=f"fsx_rt:{cid}"),
             InlineKeyboardButton("✖", callback_data=f"fsx_rtx:{cid}")],
            [InlineKeyboardButton("Set Request Target", callback_data=f"fsx_lim:{cid}"),
             InlineKeyboardButton("✖", callback_data=f"fsx_limx:{cid}")],
            [InlineKeyboardButton("New link every:", callback_data="fsx_noop")],
            rot_row[:3], rot_row[3:],
            _back("fsx_sch"),
        ]),
    )


@Bot.on_callback_query(filters.regex(r"^fsx_"), group=-1)
async def fsx_callbacks(client: Bot, cq: CallbackQuery):
    if not await _is_admin(cq.from_user.id):
        await cq.answer("Only admins can access this!", show_alert=True)
        raise StopPropagation

    parts = cq.data.split(":")
    cmd = parts[0]
    try:
        # ── Layout ────────────────────────────────────
        if cmd == "fsx_lay":
            per_row = 2 if parts[1] == "2" else 1
            if await Seishiro.get_fsub_layout() == per_row:
                await cq.answer("Already set")
            else:
                await Seishiro.set_fsub_layout(per_row)
                await cq.answer("2 buttons per row (request channels 'Req' dikhenge)" if per_row == 2 else "1 button per row")
                from plugins.settings import settings_callback
                cq.data = "fsub_settings_menu"
                await settings_callback(client, cq)

        # ── Text / Photo ──────────────────────────────
        elif cmd == "fsx_txt":
            await _show_text_menu(cq)

        elif cmd == "fsx_txte":
            resp = await _ask(
                client, cq,
                "<b>Naya fsub text bhejo</b>\n\n"
                f"<blockquote>Max {FSUB_TEXT_MAX} characters. Bold mein dikhega.\n\n"
                "Example:\n<code>Hey {mention}, niche ke channels join karo phir Joined dabao</code></blockquote>",
                "fsx_txt",
            )
            if resp:
                text = (resp.text or "").strip()
                try:
                    await resp.delete()
                except Exception:
                    pass
                if len(text) > FSUB_TEXT_MAX:
                    await cq.message.reply(f"<b>Bahut lamba ({len(text)}). {FSUB_TEXT_MAX} se kam rakho.</b>")
                else:
                    await Seishiro.set_fsub_ui(text=text)
                    await cq.message.reply("<b>Fsub text save ho gaya.</b>")
                    await _send_preview(client, cq.from_user, cq.message.chat.id,
                                        InlineKeyboardMarkup([[InlineKeyboardButton("back", callback_data="fsx_txt")]]))
                    raise StopPropagation
            await _show_text_menu(cq)

        elif cmd == "fsx_pic":
            resp = await _ask(
                client, cq,
                "<b>Fsub photo bhejo</b> (image ya direct link)\n\n"
                "<blockquote>Ye text aur buttons ke upar dikhegi.\n"
                "<code>0</code> bhejo = photo hata do (sirf text)\n"
                "<code>default</code> bhejo = original photo wapas</blockquote>",
                "fsx_txt", allow_photo=True,
            )
            if resp:
                if resp.photo:
                    await Seishiro.set_fsub_ui(pic=resp.photo.file_id)
                    await cq.message.reply("<b>Photo set ho gayi.</b>")
                else:
                    t = (resp.text or "").strip()
                    if t == "0":
                        await Seishiro.set_fsub_ui(pic="none")
                        await cq.message.reply("<b>Photo hata di — ab sirf text dikhega.</b>")
                    elif t.lower() == "default":
                        await Seishiro.set_fsub_ui(pic="")
                        await cq.message.reply("<b>Default photo wapas set.</b>")
                    elif t.startswith("http"):
                        await Seishiro.set_fsub_ui(pic=t)
                        await cq.message.reply("<b>Photo link set ho gaya.</b>")
                    else:
                        await cq.message.reply("<b>Photo, link, 0 ya default bhejo.</b>")
            await _show_text_menu(cq)

        elif cmd == "fsx_prev":
            await cq.answer()
            await _send_preview(client, cq.from_user, cq.message.chat.id)
            raise StopPropagation

        elif cmd == "fsx_txtr":
            await Seishiro.set_fsub_ui(text="")
            await cq.answer("Default text par reset")
            await _show_text_menu(cq)

        # ── Auto remove / rotate ──────────────────────
        elif cmd == "fsx_sch":
            channels = await Seishiro.get_fsub_channels()
            if not channels:
                await cq.answer("Koi fsub channel add nahi hai!", show_alert=True)
                raise StopPropagation
            titles = await asyncio.gather(*[_title(client, c) for c in channels])
            rows = [[InlineKeyboardButton(t[:60], callback_data=f"fsx_schc:{c}")] for c, t in zip(channels, titles)]
            rows.append(_back())
            await cq.message.edit_text(
                "<b>Auto Remove / Link Rotate</b>\n\n"
                "<blockquote>Channel chuno. Aap kar sakte ho:\n"
                "- kisi time par fsub se hata do\n"
                "- N requests / joins ke baad hata do\n"
                "- har N ghante naya invite link do\n\n"
                "Har removal par channel ka invite link expire hota hai.</blockquote>",
                reply_markup=InlineKeyboardMarkup(rows),
            )

        elif cmd == "fsx_schc":
            await _show_channel_sched(cq, int(parts[1]))

        elif cmd == "fsx_rt":
            cid = int(parts[1])
            resp = await _ask(
                client, cq,
                "<b>Channel fsub se kab hate?</b>\n\n<blockquote>Bhejo:\n"
                "- <code>6h</code>, <code>1d 12h</code>, <code>90m</code> — abhi se\n"
                "- <code>12:00</code> ya <code>6:30 pm</code> — agli baar us time par\n"
                "- <code>25-12-2026 18:30</code> — exact date aur time\n\n"
                f"Clock times <b>{TZ_LABEL}</b> mein.</blockquote>",
                f"fsx_schc:{cid}",
            )
            if resp:
                when = parse_remove_time(resp.text or "")
                try:
                    await resp.delete()
                except Exception:
                    pass
                if when is None:
                    await cq.message.reply("<b>Samajh nahi aaya (ya time past mein hai).</b> Try: <code>6h</code>, <code>12:00</code>")
                elif await Seishiro.set_fsub_remove_at(cid, when):
                    await cq.message.reply(
                        f"<b>Channel is time par hat jayega:</b>\n<code>{fmt_local(when)}</code> ({TZ_LABEL})\n\n"
                        "<i>Har minute check hota hai.</i>")
            await _show_channel_sched(cq, cid)

        elif cmd == "fsx_rtx":
            cid = int(parts[1])
            await Seishiro.set_fsub_remove_at(cid, None)
            await cq.answer("Remove time clear")
            await _show_channel_sched(cq, cid)

        elif cmd == "fsx_lim":
            cid = int(parts[1])
            mode = await Seishiro.get_channel_mode(cid)
            kind = "join requests" if mode == "on" else "joins"
            resp = await _ask(
                client, cq,
                f"<b>Request target</b>\n\n<blockquote>Ek number bhejo. Ab se itne NAYE {kind} aate hi channel "
                "fsub se hat jayega aur invite link expire ho jayega.\n\nExample: <code>5000</code></blockquote>",
                f"fsx_schc:{cid}",
            )
            if resp:
                txt = (resp.text or "").strip().replace(",", "")
                try:
                    await resp.delete()
                except Exception:
                    pass
                if not txt.isdigit() or int(txt) <= 0:
                    await cq.message.reply("<b>Positive number bhejo, e.g. <code>5000</code>.</b>")
                elif await Seishiro.set_fsub_request_limit(cid, int(txt)):
                    await cq.message.reply(f"<b>Target set: {int(txt)}</b>\n<i>Counting ab se shuru.</i>")
            await _show_channel_sched(cq, cid)

        elif cmd == "fsx_limx":
            cid = int(parts[1])
            await Seishiro.set_fsub_request_limit(cid, 0)
            await cq.answer("Target clear")
            await _show_channel_sched(cq, cid)

        elif cmd == "fsx_rot":
            cid, hours = int(parts[1]), int(parts[2])
            if hours not in [h for _, h in ROTATE_OPTIONS]:
                await cq.answer("Invalid option", show_alert=True)
                raise StopPropagation
            await Seishiro.set_fsub_link_rotation(cid, hours)
            await cq.answer(f"Link rotation every {hours}h" if hours else "Link rotation off")
            await _show_channel_sched(cq, cid)

        else:
            pass

    except StopPropagation:
        raise
    except MessageNotModified:
        pass
    except Exception as e:
        logger.error(f"fsx callback error ({cq.data}): {e}", exc_info=True)
        try:
            await cq.answer("Error, dobara try karo", show_alert=True)
        except Exception:
            pass
    try:
        await cq.answer()
    except Exception:
        pass
    raise StopPropagation
