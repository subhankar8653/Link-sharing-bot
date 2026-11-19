"""
plugins/miniapp.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Telegram Mini App (Ad Watch) System — Shortener ka replacement

FLOW:
  User channel link kholta hai → bot "🎬 Watch Video Ad" button deta hai
  → Mini App khulta hai → ads ek ek karke (admin ke set kiye order aur
  times ke hisaab se) dikhte hain → complete hote hi purana message delete
  hota hai aur normal "HERE IS YOUR LINK" message aa jata hai.

ADMIN PANEL:  /settings → "Mini App Menu"  (ya /miniapp)
  • Ads: add / delete / order / har ad kitni baar / ON-OFF / format
  • Daily Goal: din mein itne ads dekho → baaki din free
  • Free Time: ek session ke baad kitni der free
  • Min watch time, In-App ads, Stats, URL

COMMANDS (shortcut):
  /addminiad <provider> <id> [times]   provider: monetag | monetag_pop | adsgram | gigapub
  /delminiad <n> | /miniadorder 2 1 3 | /setminiurl <https-url> | /setminiwait <sec>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import hashlib
import hmac
import json
import logging
import datetime
import time
from urllib.parse import parse_qsl

from pyrogram import filters, StopPropagation
from pyrogram.errors import MessageNotModified
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot import Bot
from config import MINIAPP_URL, TG_BOT_TOKEN, OWNER_ID
from database.database import Seishiro
from plugins.premium import _get_bot_config, _set_bot_config, is_owner_or_admin

logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS = ("monetag", "monetag_pop", "adsgram", "gigapub")
PROVIDER_LABEL = {
    "monetag": "Monetag (Rewarded Interstitial)",
    "monetag_pop": "Monetag (Rewarded Popup)",
    "adsgram": "Adsgram",
    "gigapub": "Gigapub",
}
DEFAULT_MIN_SECONDS = 5
FLOW_LABELS = {
    "fsub_ads": "FSub first, then Ads",
    "ads_fsub": "Ads first, then FSub",
    "ads_only": "Only Ads (no FSub)",
    "fsub_only": "Only FSub (no Ads)",
}
MAX_TIMES = 10


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONFIG HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _norm_ad(a: dict) -> dict:
    return {
        "provider": a.get("provider", "monetag"),
        "id": str(a.get("id", "")),
        "times": max(1, min(MAX_TIMES, int(a.get("times", 1)))),
        "on": bool(a.get("on", True)),
        "place": a.get("place", "both") if a.get("place", "both") in ("both", "gate", "earn") else "both",
    }


async def get_miniapp_settings() -> dict:
    cfg = await _get_bot_config()
    url = (cfg.get("miniapp_url") or MINIAPP_URL or "").rstrip("/")
    return {
        "enabled": bool(cfg.get("miniapp_enabled", False)),
        "url": url,
        "ads": [_norm_ad(a) for a in cfg.get("miniapp_ads", [])],
        "min_seconds": int(cfg.get("miniapp_min_seconds", DEFAULT_MIN_SECONDS)),
        "daily_goal": int(cfg.get("miniapp_daily_goal", 0)),          # 0 = off
        "free_seconds": int(cfg.get("verify_premium_seconds", 86400)),  # sirf jab Daily Goal OFF ho
        "goal_reward_seconds": int(cfg.get("miniapp_goal_reward", 86400)),  # goal poora -> itni der ads-free
        "flow": cfg.get("link_flow", "fsub_ads") if cfg.get("link_flow", "fsub_ads") in FLOW_LABELS else "fsub_ads",
        "fb_daily": max(0, int(cfg.get("miniapp_fb_daily", 3))),   # ads fail hone par "bina ads" raasta: din mein kitni baar (0 = band)
        "inapp": False,   # passive in-app ads hata diye (auto-ads uncounted the)
    }


async def get_link_flow() -> str:
    return (await get_miniapp_settings())["flow"]


async def _save_ads(ads: list) -> None:
    await _set_bot_config("miniapp_ads", ads)


def build_steps(ads: list, place: str = "gate") -> list:
    """ON wale ads ko 'times' ke hisaab se expand karo. place: "gate" (link unlock) ya "earn" (Senpai Sync Earn tab).
    Ad ka place "both" ho toh dono jagah chalta hai."""
    steps = []
    for a in ads:
        if a["on"] and a.get("place", "both") in ("both", place):
            steps.extend({"provider": a["provider"], "id": a["id"]} for _ in range(a["times"]))
    return steps


def first_monetag_zone(ads: list) -> str:
    for a in ads:
        if a["on"] and a["provider"] in ("monetag", "monetag_pop"):
            return a["id"]
    return ""


async def miniapp_ready() -> bool:
    """Mini app tabhi use hoga jab ON ho, URL ho (https) aur kam se kam 1 ON ad ho."""
    s = await get_miniapp_settings()
    return bool(s["enabled"] and s["url"].startswith("https://") and build_steps(s["ads"]))


def seconds_until_ist_midnight() -> int:
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    nxt = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(60, int((nxt - now).total_seconds()))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TELEGRAM initData VALIDATION
# https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def validate_init_data(init_data: str, max_age: int = 86400) -> dict | None:
    """
    Mini App se aaya initData verify karo.
    Valid ho toh user dict ({"id":..., ...}) return karo, warna None.
    Isse koi bhi fake user_id bhej kar dusre ka token use nahi kar sakta.
    """
    try:
        if not init_data:
            return None
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = pairs.pop("hash", None)
        if not received_hash:
            return None

        data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
        secret_key = hmac.new(b"WebAppData", TG_BOT_TOKEN.encode(), hashlib.sha256).digest()
        calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc_hash, received_hash):
            return None

        auth_date = int(pairs.get("auth_date", "0"))
        if auth_date <= 0 or time.time() - auth_date > max_age:
            return None

        user = json.loads(pairs.get("user", "{}"))
        if not user.get("id"):
            return None
        return user
    except Exception as e:
        logger.warning(f"initData validation error: {e}")
        return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ADMIN PANEL  (settings menu ke andar: callback "mini_*")
# NOTE: photo-message ka caption 1024 chars tak hi hota hai, isliye
#       panel text chhota rakha gaya hai.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _admin_ok(uid: int) -> bool:
    return uid == OWNER_ID or await Seishiro.is_admin(uid)


def _dur(seconds: int) -> str:
    if seconds <= 0:
        return "None"
    h, m = divmod(seconds // 60, 60)
    if h and m:
        return f"{h}h {m}m"
    return f"{h}h" if h else f"{m}m"


def _ad_line(i: int, a: dict) -> str:
    st = "✅" if a["on"] else "⏸"
    tag = {"gate": " [gate]", "earn": " [earn]"}.get(a.get("place", "both"), "")
    return f"{st} {i}. <b>{a['provider']}</b> ×{a['times']}{tag} — <code>{a['id']}</code>"


def _menu_text(s: dict) -> str:
    status = "✅ ON" if s["enabled"] else "❌ OFF"
    url = s["url"] or "Not set"
    if s["ads"]:
        shown_ads = s["ads"][:6]
        ads = "\n".join(_ad_line(i, a) for i, a in enumerate(shown_ads, 1))
        if len(s["ads"]) > 6:
            ads += f"\n… +{len(s['ads']) - 6} more"
    else:
        ads = "(koi ad nahi — Ads Manage se add karo)"
    steps = len(build_steps(s["ads"]))
    goal = f"{s['daily_goal']} ads" if s["daily_goal"] else "OFF"
    if s["daily_goal"]:
        rule = f"Goal ON: {s['daily_goal']} ads dekhne par <b>{_dur(s['goal_reward_seconds'])}</b> ads-free (FSub lagega)"
    else:
        rule = f"Goal OFF: har session ke baad <b>{_dur(s['free_seconds'])}</b> free"
    return (
        "<b>🎬 Mini App Menu</b>\n\n"
        f"• Status: <b>{status}</b>   • Ads/session: <b>{steps}</b>\n"
        f"• Daily Goal: <b>{goal}</b>   • Min watch: <b>{s['min_seconds']}s</b>\n"
        f"• {rule}\n"
        f"• Link flow: <b>{FLOW_LABELS[s['flow']]}</b>\n"
        f"• Ad fallback: <b>{(str(s['fb_daily']) + '/day') if s['fb_daily'] else 'OFF'}</b>\n"
        f"• URL: <code>{url}</code>\n\n"
        f"<b>Ads (order mein):</b>\n{ads}"
    )


def _menu_kb(s: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 Turn OFF" if s["enabled"] else "🟢 Turn ON", callback_data="mini_toggle")],
        [InlineKeyboardButton("📺 Ads Manage", callback_data="mini_ads"),
         InlineKeyboardButton("🎯 Daily Goal", callback_data="mini_goal")],
        [InlineKeyboardButton("⏱ Free Time", callback_data="mini_free"),
         InlineKeyboardButton("⏳ Min Watch", callback_data="mini_wait")],
        [InlineKeyboardButton("🔀 Link Flow", callback_data="mini_flow"),
         InlineKeyboardButton("📊 Stats", callback_data="mini_stats")],
        [InlineKeyboardButton("🌐 Set URL", callback_data="mini_url"),
         InlineKeyboardButton("🎓 Ads Tutorial", callback_data="mini_tut")],
        [InlineKeyboardButton("🛟 Ad Fallback", callback_data="mini_fb")],
        [InlineKeyboardButton("back", callback_data="settings_main")],
    ])


async def _show_menu(msg):
    s = await get_miniapp_settings()
    await msg.edit_text(_menu_text(s), reply_markup=_menu_kb(s))


def _back(to="mini_menu"):
    return [InlineKeyboardButton("back", callback_data=to)]


def _num_buttons(prefix: str, values: list, labels: dict | None = None, per_row: int = 4):
    rows, row = [], []
    for v in values:
        label = (labels or {}).get(v, str(v))
        row.append(InlineKeyboardButton(label, callback_data=f"{prefix}:{v}"))
        if len(row) == per_row:
            rows.append(row); row = []
    if row:
        rows.append(row)
    return rows


async def _ask(client, cq: CallbackQuery, prompt: str, back_to: str):
    """Admin se text maango (pyromod listen). Returns text ya None (cancel/timeout)."""
    await cq.message.edit_text(
        prompt + "\n\n<i>/cancel — cancel karne ke liye</i>",
        reply_markup=InlineKeyboardMarkup([_back(back_to)]),
    )
    try:
        resp = await client.listen(chat_id=cq.message.chat.id, timeout=300)
    except Exception:
        return None
    try:
        await resp.delete()
    except Exception:
        pass
    text = (resp.text or "").strip()
    if not text or text.lower() == "/cancel":
        return None
    return text


@Bot.on_message(filters.command("miniapp") & filters.private)
async def cmd_miniapp(client: Bot, msg: Message):
    if not await _admin_ok(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    s = await get_miniapp_settings()
    await msg.reply(_menu_text(s), reply_markup=_menu_kb(s))


@Bot.on_callback_query(filters.regex(r"^mini_"), group=-1)
async def mini_callbacks(client: Bot, cq: CallbackQuery):
    if not await _admin_ok(cq.from_user.id):
        await cq.answer("⛔ Admins only", show_alert=True)
        raise StopPropagation

    data = cq.data
    parts = data.split(":")
    cmd = parts[0]

    try:
        if cmd == "mini_menu":
            await _show_menu(cq.message)

        elif cmd == "mini_toggle":
            s = await get_miniapp_settings()
            new = not s["enabled"]
            if new:
                if not build_steps(s["ads"]):
                    await cq.answer("⚠️ Pehle Ads Manage se koi ad add/ON karo!", show_alert=True)
                    raise StopPropagation
                if not s["url"].startswith("https://"):
                    await cq.answer("⚠️ Pehle Set URL se https URL set karo!", show_alert=True)
                    raise StopPropagation
            await _set_bot_config("miniapp_enabled", new)
            await cq.answer("✅ Mini App ON" if new else "❌ Mini App OFF")
            await _show_menu(cq.message)

        # ── Ads ────────────────────────────────────────
        elif cmd == "mini_ads":
            s = await get_miniapp_settings()
            rows = []
            for i, a in enumerate(s["ads"]):
                st = "✅" if a["on"] else "⏸"
                rows.append([InlineKeyboardButton(
                    f"{st} {i + 1}. {a['provider']} ×{a['times']}", callback_data=f"mini_ad:{i}")])
            rows.append([InlineKeyboardButton("➕ Add Ad", callback_data="mini_adadd")])
            rows.append(_back())
            text = ("<b>📺 Ads Manage</b>\n\n"
                    "Ad pe tap karo → times / ON-OFF / order / delete.\n"
                    "<i>Order = jis order mein user ko dikhenge.</i>")
            await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(rows))

        elif cmd == "mini_ad":
            await _show_ad(cq, int(parts[1]))

        elif cmd == "mini_adt":
            i, d = int(parts[1]), int(parts[2])
            s = await get_miniapp_settings(); ads = s["ads"]
            if 0 <= i < len(ads):
                ads[i]["times"] = max(1, min(MAX_TIMES, ads[i]["times"] + d))
                await _save_ads(ads)
            await _show_ad(cq, i)

        elif cmd == "mini_adon":
            i = int(parts[1])
            s = await get_miniapp_settings(); ads = s["ads"]
            if 0 <= i < len(ads):
                ads[i]["on"] = not ads[i]["on"]
                await _save_ads(ads)
                if s["enabled"] and not build_steps(ads):
                    await _set_bot_config("miniapp_enabled", False)
                    await cq.answer("⚠️ Koi ad ON nahi bacha — Mini App OFF kar diya", show_alert=True)
            await _show_ad(cq, i)

        elif cmd == "mini_admv":
            i, direction = int(parts[1]), parts[2]
            s = await get_miniapp_settings(); ads = s["ads"]
            j = i - 1 if direction == "up" else i + 1
            if 0 <= i < len(ads) and 0 <= j < len(ads):
                ads[i], ads[j] = ads[j], ads[i]
                await _save_ads(ads)
                i = j
            await _show_ad(cq, i)

        elif cmd == "mini_adfmt":
            i = int(parts[1])
            s = await get_miniapp_settings(); ads = s["ads"]
            if 0 <= i < len(ads) and ads[i]["provider"] in ("monetag", "monetag_pop"):
                ads[i]["provider"] = "monetag_pop" if ads[i]["provider"] == "monetag" else "monetag"
                await _save_ads(ads)
            await _show_ad(cq, i)

        elif cmd == "mini_addel":
            i = int(parts[1])
            s = await get_miniapp_settings(); ads = s["ads"]
            if 0 <= i < len(ads):
                ads.pop(i)
                await _save_ads(ads)
                if s["enabled"] and not build_steps(ads):
                    await _set_bot_config("miniapp_enabled", False)
            await cq.answer("🗑 Deleted")
            cq.data = "mini_ads"
            await mini_callbacks(client, cq)

        elif cmd == "mini_adadd":
            text = await _ask(
                client, cq,
                "<b>➕ Add Ad</b>\n\nFormat: <code>provider id [times]</code>\n"
                "Providers: <code>monetag</code> (rewarded interstitial), <code>monetag_pop</code> "
                "(rewarded popup), <code>adsgram</code>, <code>gigapub</code>\n\n"
                "Example: <code>monetag 1234567 2</code>",
                "mini_ads",
            )
            if text:
                p = text.split()
                err = None
                if len(p) < 2:
                    err = "❌ Format galat. Example: monetag 1234567 2"
                elif p[0].lower() not in SUPPORTED_PROVIDERS:
                    err = f"❌ Provider galat. Use: {', '.join(SUPPORTED_PROVIDERS)}"
                elif not p[1].replace("-", "").replace("_", "").isalnum():
                    err = "❌ ID mein sirf letters/numbers/-/_ allowed hain."
                if err:
                    await cq.message.reply(err)
                else:
                    times = int(p[2]) if len(p) > 2 and p[2].isdigit() else 1
                    s = await get_miniapp_settings(); ads = s["ads"]
                    ads.append({"provider": p[0].lower(), "id": p[1], "times": max(1, min(MAX_TIMES, times)), "on": True})
                    await _save_ads(ads)
            cq.data = "mini_ads"
            await mini_callbacks(client, cq)

        # ── Daily goal ────────────────────────────────
        elif cmd == "mini_goal":
            s = await get_miniapp_settings()
            cur = f"{s['daily_goal']} ads" if s["daily_goal"] else "OFF"
            rows = _num_buttons("mini_goalset", [0, 5, 10, 15, 20, 30, 50, 100], {0: "OFF"})
            rows.append([InlineKeyboardButton("Reward (ads-free time):", callback_data="mini_noop")])
            rows += _num_buttons("mini_rwset", [21600, 43200, 86400, 172800, 259200],
                                 {21600: "6h", 43200: "12h", 86400: "24h", 172800: "48h", 259200: "72h"}, per_row=5)
            rows.append(_back())
            await cq.message.edit_text(
                "<b>🎯 Daily Goal</b>\n\n"
                f"Goal: <b>{cur}</b>  |  Reward: <b>{_dur(s['goal_reward_seconds'])}</b>\n\n"
                "User jab total itne ads dekh le (har session mein jitne ads, utne count hote hain; "
                "jaise 2 ads/session aur goal 10 = 5 baar link) toh <b>Reward time</b> tak koi ads nahi aayenge. "
                "<b>FSub phir bhi lagega</b>.\n"
                "Goal ON hone par session ke baad ka <i>Free Time</i> lagu nahi hota.",
                reply_markup=InlineKeyboardMarkup(rows),
            )

        elif cmd == "mini_rwset":
            await _set_bot_config("miniapp_goal_reward", max(3600, int(parts[1])))
            await cq.answer("✅ Saved")
            cq.data = "mini_goal"
            await mini_callbacks(client, cq)

        elif cmd == "mini_goalset":
            await _set_bot_config("miniapp_daily_goal", max(0, int(parts[1])))
            await cq.answer("✅ Saved")
            cq.data = "mini_goal"
            await mini_callbacks(client, cq)

        # ── Free time after session ───────────────────
        elif cmd == "mini_free":
            s = await get_miniapp_settings()
            vals = [0, 1800, 3600, 10800, 21600, 43200, 86400]
            labels = {0: "None", 1800: "30m", 3600: "1h", 10800: "3h", 21600: "6h", 43200: "12h", 86400: "24h"}
            rows = _num_buttons("mini_freeset", vals, labels)
            rows.append(_back())
            await cq.message.edit_text(
                "<b>⏱ Free Time</b>\n\n"
                f"Abhi: <b>{_dur(s['free_seconds'])}</b>\n\n"
                "Ek session (saare ads) complete karne ke baad user kitni der tak "
                "direct links paayega (FSub bhi skip).\n<b>None</b> = har link ke liye ads dekhne padenge.\n"
                "<i>Sirf tab lagu hota hai jab Daily Goal OFF ho.</i>",
                reply_markup=InlineKeyboardMarkup(rows),
            )

        elif cmd == "mini_freeset":
            await _set_bot_config("verify_premium_seconds", max(0, int(parts[1])))
            await cq.answer("✅ Saved")
            cq.data = "mini_free"
            await mini_callbacks(client, cq)

        # ── Min watch ─────────────────────────────────
        elif cmd == "mini_wait":
            s = await get_miniapp_settings()
            rows = _num_buttons("mini_waitset", [0, 3, 5, 8, 10, 15, 20, 30], {0: "Off"})
            rows.append(_back())
            await cq.message.edit_text(
                "<b>⏳ Min Watch Time</b>\n\n"
                f"Abhi: <b>{s['min_seconds']}s per ad</b>\n\n"
                "Server itna time guzre bina verify nahi karega (fast-skip/bypass se bachav).",
                reply_markup=InlineKeyboardMarkup(rows),
            )

        elif cmd == "mini_waitset":
            await _set_bot_config("miniapp_min_seconds", max(0, min(60, int(parts[1]))))
            await cq.answer("✅ Saved")
            cq.data = "mini_wait"
            await mini_callbacks(client, cq)

        # ── Link flow (ads / fsub ka order) ───────────
        elif cmd == "mini_flow":
            s = await get_miniapp_settings()
            rows = [[InlineKeyboardButton(("✅ " if s["flow"] == k else "") + lbl, callback_data=f"mini_flowset:{k}")]
                    for k, lbl in FLOW_LABELS.items()]
            rows.append(_back())
            await cq.message.edit_text(
                "<b>🔀 Link Flow</b>\n\n"
                "Channel link se aane wale user ke liye order chuno:\n\n"
                "<b>FSub first, then Ads:</b> pehle FSub join, uske baad ads (FSub ke turant baad ka link seedha milta hai).\n"
                "<b>Ads first, then FSub:</b> pehle ads; daily goal poora hone par FSub, phir ads-free time.\n"
                "<b>Only Ads:</b> sirf ads, FSub nahi.\n"
                "<b>Only FSub:</b> sirf FSub, ads nahi.\n\n"
                "<i>Ads-free time mein bhi naya FSub channel add hone par FSub dikhta hai.</i>",
                reply_markup=InlineKeyboardMarkup(rows),
            )

        elif cmd == "mini_flowset":
            if parts[1] in FLOW_LABELS:
                await _set_bot_config("link_flow", parts[1])
                await cq.answer("✅ " + FLOW_LABELS[parts[1]])
            cq.data = "mini_flow"
            await mini_callbacks(client, cq)

        # ── Ads tutorial (user ko "How to watch ads" button) ───────────
        elif cmd == "mini_tut":
            cfg = await _get_bot_config()
            t = cfg.get("miniapp_tutorial")
            rows = [[InlineKeyboardButton("Replace Video" if t else "Set Video", callback_data="mini_tutset")]]
            if t:
                rows.append([InlineKeyboardButton("Remove", callback_data="mini_tutdel")])
            rows.append(_back())
            await cq.message.edit_text(
                "<b>🎓 Ads Tutorial</b>\n\n"
                f"Status: <b>{'SET (' + t.get('kind', 'video') + ')' if t else 'Not set'}</b>\n\n"
                "Set hone par user ke <b>Watch Video Ad</b> button ke neeche <b>How to watch ads</b> button aata hai; "
                "dabane par ye video bheja jata hai (auto-delete ke saath). Set nahi hai toh button nahi dikhta.",
                reply_markup=InlineKeyboardMarkup(rows))

        elif cmd == "mini_tutset":
            await cq.message.edit_text(
                "<b>🎓 Ads Tutorial</b>\n\nTutorial <b>video</b> (ya GIF / document / photo) bhejo.\n<i>/cancel — cancel</i>",
                reply_markup=InlineKeyboardMarkup([_back("mini_tut")]))
            try:
                resp = await client.listen(chat_id=cq.message.chat.id, timeout=300)
            except Exception:
                resp = None
            if resp:
                data = None
                if resp.video:
                    data = {"file_id": resp.video.file_id, "kind": "video"}
                elif resp.animation:
                    data = {"file_id": resp.animation.file_id, "kind": "animation"}
                elif resp.document:
                    data = {"file_id": resp.document.file_id, "kind": "document"}
                elif resp.photo:
                    data = {"file_id": resp.photo.file_id, "kind": "photo"}
                try:
                    await resp.delete()
                except Exception:
                    pass
                if data:
                    await _set_bot_config("miniapp_tutorial", data)
                    await cq.answer("✅ Tutorial saved")
                elif (resp.text or "").strip().lower() != "/cancel":
                    await cq.message.reply("❌ Video, GIF, document ya photo bhejo.")
            cq.data = "mini_tut"
            await mini_callbacks(client, cq)

        elif cmd == "mini_tutdel":
            await _set_bot_config("miniapp_tutorial", None)
            await cq.answer("Removed")
            cq.data = "mini_tut"
            await mini_callbacks(client, cq)

        elif cmd == "mini_adplace":
            i = int(parts[1])
            s = await get_miniapp_settings(); ads = s["ads"]
            if 0 <= i < len(ads):
                order = ["both", "gate", "earn"]
                ads[i]["place"] = order[(order.index(ads[i]["place"]) + 1) % 3]
                await _save_ads(ads)
                if s["enabled"] and not build_steps(ads):
                    await cq.answer("⚠️ Link gate ke liye koi ad nahi bacha — Mini App OFF kar diya", show_alert=True)
                    await _set_bot_config("miniapp_enabled", False)
            await _show_ad(cq, i)

        elif cmd == "mini_fb":
            s = await get_miniapp_settings()
            cur = s["fb_daily"]
            rows = [[InlineKeyboardButton(("✅ " if cur == v else "") + ("Off" if v == 0 else f"{v}/day"),
                                          callback_data=f"mini_fbset:{v}") for v in (0, 1, 2, 3, 5)], _back()]
            await cq.message.edit_text(
                "<b>🛟 Ad Fallback</b>\n\n"
                f"Abhi: <b>{'OFF' if not cur else str(cur) + ' baar / din'}</b>\n\n"
                "Kisi user ke ads load na hon (AdBlock, VPN, black screen) toh wo <b>Continue without ads</b> dabata hai. "
                "Bot use <b>FSub</b> (channels join) karwata hai aur phir link deta hai. Ads-free time ya daily goal nahi milta.\n"
                "Ek user din mein itni baar hi use kar sakta hai. Off = user ko error dikhta hai.",
                reply_markup=InlineKeyboardMarkup(rows))

        elif cmd == "mini_fbset":
            await _set_bot_config("miniapp_fb_daily", max(0, min(20, int(parts[1]))))
            await cq.answer("✅ Saved")
            cq.data = "mini_fb"
            await mini_callbacks(client, cq)

        # ── Stats ─────────────────────────────────────
        elif cmd == "mini_stats":
            st = await Seishiro.get_miniapp_stats()
            await cq.message.edit_text(
                "<b>📊 Mini App Stats</b>\n\n"
                f"<b>Aaj (IST)</b>\n• Users: <b>{st['users_today']}</b>\n"
                f"• Sessions (links unlock): <b>{st['today_sessions']}</b>\n"
                f"• Ads dekhe gaye: <b>{st['today_ads']}</b>\n\n"
                f"<b>Total</b>\n• Sessions: <b>{st['total_sessions']}</b>\n"
                f"• Ads: <b>{st['total_ads']}</b>\n\n"
                "<i>Asli earning Monetag dashboard mein dekho — ye bot ke apne counts hain.</i>",
                reply_markup=InlineKeyboardMarkup([_back()]),
            )

        # ── URL ───────────────────────────────────────
        elif cmd == "mini_url":
            s = await get_miniapp_settings()
            text = await _ask(
                client, cq,
                "<b>🌐 Mini App URL</b>\n\n"
                f"Abhi: <code>{s['url'] or 'Not set'}</code>\n\n"
                "Naya <b>https://</b> URL bhejo (e.g. <code>https://aapka-app.up.railway.app</code>)",
                "mini_menu",
            )
            if text:
                url = text.split()[0].rstrip("/")
                if url.startswith("https://"):
                    await _set_bot_config("miniapp_url", url)
                else:
                    await cq.message.reply("❌ URL <b>https://</b> se shuru hona chahiye.")
            await _show_menu(cq.message)

        else:
            await cq.answer()

    except StopPropagation:
        raise
    except MessageNotModified:
        pass
    except Exception as e:
        logger.error(f"mini callback error ({data}): {e}", exc_info=True)
        try:
            await cq.answer("⚠️ Error, dobara try karo", show_alert=True)
        except Exception:
            pass
    try:
        await cq.answer()
    except Exception:
        pass
    raise StopPropagation


async def _show_ad(cq: CallbackQuery, i: int):
    s = await get_miniapp_settings()
    ads = s["ads"]
    if not (0 <= i < len(ads)):
        cq.data = "mini_ads"
        return await mini_callbacks(cq._client, cq)
    a = ads[i]
    rows = [
        [InlineKeyboardButton("➖", callback_data=f"mini_adt:{i}:-1"),
         InlineKeyboardButton(f"Times: {a['times']}", callback_data="mini_noop"),
         InlineKeyboardButton("➕", callback_data=f"mini_adt:{i}:1")],
        [InlineKeyboardButton("⏸ Turn OFF" if a["on"] else "▶️ Turn ON", callback_data=f"mini_adon:{i}")],
        [InlineKeyboardButton("📍 Place: " + {"both": "Gate + Earn", "gate": "Link gate only", "earn": "Earn tab only"}[a["place"]],
                              callback_data=f"mini_adplace:{i}")],
        [InlineKeyboardButton("⬆️ Up", callback_data=f"mini_admv:{i}:up"),
         InlineKeyboardButton("⬇️ Down", callback_data=f"mini_admv:{i}:down")],
    ]
    if a["provider"] in ("monetag", "monetag_pop"):
        rows.append([InlineKeyboardButton("🔁 Format badlo (Interstitial ⇄ Popup)", callback_data=f"mini_adfmt:{i}")])
    rows.append([InlineKeyboardButton("🗑 Delete", callback_data=f"mini_addel:{i}")])
    rows.append(_back("mini_ads"))
    await cq.message.edit_text(
        f"<b>📺 Ad #{i + 1}</b>\n\n"
        f"• Network: <b>{PROVIDER_LABEL.get(a['provider'], a['provider'])}</b>\n"
        f"• ID: <code>{a['id']}</code>\n"
        f"• Status: <b>{'ON' if a['on'] else 'OFF'}</b>\n"
        f"• Har session mein: <b>{a['times']} baar</b>\n"
        f"• Place: <b>{ {'both': 'Gate + Earn', 'gate': 'Link gate only', 'earn': 'Earn tab only'}[a['place']] }</b>",
        reply_markup=InlineKeyboardMarkup(rows),
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SHORTCUT COMMANDS (panel ke alawa)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@Bot.on_message(filters.command("addminiad") & filters.private)
async def cmd_add_miniad(client: Bot, msg: Message):
    if not await _admin_ok(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    if len(msg.command) < 3:
        return await msg.reply(
            "<b>Usage:</b> <code>/addminiad provider id [times]</code>\n"
            f"<b>Providers:</b> {', '.join(SUPPORTED_PROVIDERS)}\n"
            "<b>Example:</b> <code>/addminiad monetag 1234567 2</code>"
        )
    provider = msg.command[1].lower().strip()
    ad_id = msg.command[2].strip()
    times = int(msg.command[3]) if len(msg.command) > 3 and msg.command[3].isdigit() else 1
    if provider not in SUPPORTED_PROVIDERS:
        return await msg.reply(f"❌ Provider galat hai. Use: {', '.join(SUPPORTED_PROVIDERS)}")
    if not ad_id.replace("-", "").replace("_", "").isalnum():
        return await msg.reply("❌ ID mein sirf letters/numbers/-/_ allowed hain.")
    s = await get_miniapp_settings()
    ads = s["ads"]
    ads.append({"provider": provider, "id": ad_id, "times": max(1, min(MAX_TIMES, times)), "on": True})
    await _save_ads(ads)
    await msg.reply(f"✅ Ad add hua: <b>{provider}</b> → <code>{ad_id}</code> ×{max(1, min(MAX_TIMES, times))}\nTotal ads: {len(ads)}\n\n/miniapp se manage karo.")


@Bot.on_message(filters.command("delminiad") & filters.private)
async def cmd_del_miniad(client: Bot, msg: Message):
    if not await _admin_ok(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    if len(msg.command) < 2 or not msg.command[1].isdigit():
        return await msg.reply("<b>Usage:</b> <code>/delminiad 2</code> (number /miniapp mein dekho)")
    idx = int(msg.command[1])
    s = await get_miniapp_settings()
    ads = s["ads"]
    if idx < 1 or idx > len(ads):
        return await msg.reply("❌ Galat number.")
    removed = ads.pop(idx - 1)
    await _save_ads(ads)
    extra = ""
    if s["enabled"] and not build_steps(ads):
        await _set_bot_config("miniapp_enabled", False)
        extra = "\n⚠️ Koi ON ad bacha nahi, isliye Mini App OFF kar diya."
    await msg.reply(f"🗑 Removed: <b>{removed['provider']}</b> → <code>{removed['id']}</code>{extra}")


@Bot.on_message(filters.command("miniadorder") & filters.private)
async def cmd_miniad_order(client: Bot, msg: Message):
    if not await _admin_ok(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    s = await get_miniapp_settings()
    ads = s["ads"]
    try:
        order = [int(x) for x in msg.command[1:]]
    except ValueError:
        order = []
    if sorted(order) != list(range(1, len(ads) + 1)):
        return await msg.reply(
            "<b>Usage:</b> <code>/miniadorder 2 1 3</code>\n"
            f"Saare {len(ads)} numbers ek baar likhne hain (1 se {len(ads)} tak)."
        )
    await _save_ads([ads[i - 1] for i in order])
    await msg.reply("✅ Order update ho gaya. /miniapp mein dekho.")


@Bot.on_message(filters.command("setminiurl") & filters.private)
async def cmd_set_miniurl(client: Bot, msg: Message):
    if not await _admin_ok(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    if len(msg.command) < 2:
        return await msg.reply("<b>Usage:</b> <code>/setminiurl https://your-app.up.railway.app</code>")
    url = msg.command[1].strip().rstrip("/")
    if not url.startswith("https://"):
        return await msg.reply("❌ URL <b>https://</b> se shuru hona chahiye (Telegram ki requirement).")
    await _set_bot_config("miniapp_url", url)
    await msg.reply(f"✅ Mini App URL set: <code>{url}</code>")


@Bot.on_message(filters.command("setminiwait") & filters.private)
async def cmd_set_miniwait(client: Bot, msg: Message):
    if not await _admin_ok(msg.from_user.id):
        return await msg.reply("⛔ Sirf admins ke liye!")
    if len(msg.command) < 2 or not msg.command[1].isdigit():
        return await msg.reply("<b>Usage:</b> <code>/setminiwait 5</code> (seconds, 0-60)")
    sec = int(msg.command[1])
    if sec > 60:
        return await msg.reply("❌ Max 60 seconds.")
    await _set_bot_config("miniapp_min_seconds", sec)
    await msg.reply(f"✅ Har ad ke liye minimum <b>{sec}s</b> set.")


async def send_ads_tutorial(client, uid: int) -> bool:
    """Admin ka set kiya tutorial user ko bhejo. False agar set nahi / send fail."""
    cfg = await _get_bot_config()
    t = cfg.get("miniapp_tutorial")
    if not t:
        return False
    caption = ("<b>How to watch the ads</b>\n\n<blockquote>Watch this short guide, then tap "
               "<b>Watch Video Ad</b>. This message is deleted automatically.</blockquote>")
    kind = t.get("kind", "video")
    send = {"video": client.send_video, "animation": client.send_animation,
            "document": client.send_document, "photo": client.send_photo}.get(kind, client.send_video)
    key = kind if kind in ("video", "animation", "document", "photo") else "video"
    try:
        await send(uid, **{key: t["file_id"]}, caption=caption)
        return True
    except Exception as e:
        logger.warning(f"ads tutorial send failed: {e}")
        return False


@Bot.on_callback_query(filters.regex(r"^ads_tut$"), group=-1)
async def cb_ads_tutorial(client: Bot, cq: CallbackQuery):
    """User: 'How to watch ads' -> tutorial video (admin ne set kiya ho toh)."""
    ok = await send_ads_tutorial(client, cq.from_user.id)
    if ok:
        await cq.answer()
    else:
        await cq.answer("Tutorial is not available right now.", show_alert=True)
    raise StopPropagation
