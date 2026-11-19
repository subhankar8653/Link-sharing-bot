"""
plugins/sync_app.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Senpai Sync — Mini App ka backend (points, rewarded ads, check-in, referral, withdrawal)

SECURITY: saara hisaab SERVER par hota hai. Browser sirf request bhejta hai, points khud
nahi likh sakta. Login = Telegram initData (HMAC verified) — Firebase/password nahi.

Collections (MongoDB):  sync_users · sync_ads · sync_tx · sync_withdrawals
Settings (bot_config):  sync_*  (admin panel: /settings -> Senpai Sync Menu)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import datetime
import logging
import random
import re
import secrets

from pymongo import ReturnDocument

from database.database import Seishiro
from plugins.premium import _get_bot_config

logger = logging.getLogger(__name__)

# key -> (default, label, min, max)
SYNC_SETTINGS = {
    "ad_reward":      (2,    "Ad reward (SP)",            0, 1000),
    "daily_cap":      (20,   "Daily ads / user",          1, 200),
    "cooldown":       (30,   "Cooldown between ads (s)",  0, 3600),
    "min_watch":      (10,   "Min watch time (s)",        0, 120),
    "checkin":        (3,    "Daily check-in (SP)",       0, 1000),
    "ref_reward":     (25,   "Referral reward (SP)",      0, 10000),
    "welcome":        (10,   "Welcome bonus (SP)",        0, 10000),
    "points_per_inr": (100,  "Points per Rs 1",           1, 100000),
    "min_withdraw":   (20,   "Min withdrawal (Rs)",       1, 100000),
}
UPI_RE = re.compile(r"^[A-Za-z0-9.\-_]{2,64}@[A-Za-z]{2,32}$")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SETTINGS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def get_sync_settings() -> dict:
    cfg = await _get_bot_config()
    out = {"enabled": bool(cfg.get("sync_enabled", False))}
    for k, (default, _label, lo, hi) in SYNC_SETTINGS.items():
        try:
            v = int(cfg.get(f"sync_{k}", default))
        except (TypeError, ValueError):
            v = default
        out[k] = max(lo, min(hi, v))
    return out


async def sync_ready() -> bool:
    """Home app tabhi dikhega jab ON ho aur Mini App URL (https) set ho."""
    return bool(await sync_enabled_and_url())


async def sync_enabled_and_url() -> str:
    """Senpai Sync (Home app) ON + https URL ho toh URL. Home URL alag set ho sakta hai
    (sync_app_url), warna Mini App URL. Alag URL = Adsgram ke liye Home-only app, gate alag."""
    from plugins.miniapp import get_miniapp_settings
    cfg = await _get_bot_config()
    st = await get_sync_settings()
    ms = await get_miniapp_settings()
    url = (cfg.get("sync_app_url") or ms["url"] or "").rstrip("/")
    return url if (st["enabled"] and url.startswith("https://")) else ""


INTRO_TEXT = (
    "<b>Welcome to Senpai Sync, {mention}!</b>\n\n"
    "<blockquote>Senpai Sync is a daily rewards bot. Sign in once every day to earn Senpai Sync Points (SP), "
    "complete simple channel tasks, invite friends and track your balance in your wallet. "
    "Watching a short video ad is optional.</blockquote>\n\n"
    "Tap <b>Open Senpai Sync</b> below to claim today's points."
)


async def intro_message(user):
    """Plain /start ka welcome: sirf text + 'Open Senpai Sync' button (photo / About / Help / Premium nahi)."""
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
    url = await sync_enabled_and_url()
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("Open Senpai Sync", web_app=WebAppInfo(url=f"{url}/miniapp"))]]) if url else None
    return INTRO_TEXT.format(mention=user.mention), markup, bool(url)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _col(name: str):
    return Seishiro.database[name]


def _today() -> str:
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")


def _yesterday() -> str:
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30, days=-1)).strftime("%Y-%m-%d")


async def _tx(uid: int, kind: str, amount: int, note: str = "") -> None:
    try:
        await _col("sync_tx").insert_one({
            "uid": int(uid), "type": kind, "amount": int(amount), "note": note,
            "ts": datetime.datetime.utcnow(),
        })
    except Exception as e:
        logger.warning(f"sync tx log failed: {e}")


def _name(u: dict) -> str:
    n = (u.get("first_name") or "").strip()
    return (n or u.get("username") or "User")[:32]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# USER (login = Telegram initData / bot /start)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def register_user(tg_user: dict, ref: int | None = None) -> dict:
    """Pehli baar aane par user banao (welcome bonus + referrer). Baad mein naam/photo refresh."""
    uid = int(tg_user["id"])
    st = await get_sync_settings()
    fields = {
        "name": _name(tg_user),
        "username": tg_user.get("username") or "",
        "photo": tg_user.get("photo_url") or "",
    }
    doc = await _col("sync_users").find_one({"_id": uid})
    if doc:
        await _col("sync_users").update_one({"_id": uid}, {"$set": fields})
        doc.update(fields)
        return doc

    ref_by = ref if (ref and ref != uid) else None
    if ref_by and not await _col("sync_users").find_one({"_id": ref_by}):
        ref_by = None
    new = {
        "_id": uid, **fields, "points": st["welcome"], "earned": st["welcome"],
        "ads_total": 0, "ads_day": "", "ads_today": 0, "last_ad_at": None,
        "streak": 0, "last_checkin": "", "ref_by": ref_by, "ref_rewarded": False,
        "ref_count": 0, "ref_earned": 0, "created": datetime.datetime.utcnow(),
    }
    try:
        await _col("sync_users").insert_one(new)
    except Exception:
        return await _col("sync_users").find_one({"_id": uid}) or new   # race: dusri request ne bana diya
    if st["welcome"]:
        await _tx(uid, "welcome", st["welcome"], "Welcome bonus")
    return new


async def sync_register_from_bot(user, ref: str = "") -> None:
    """Bot /start se (pyrogram User object): login ho jata hai."""
    try:
        tg = {"id": user.id, "first_name": user.first_name or "", "username": user.username or ""}
        r = int(ref) if ref and ref.isdigit() else None
        await register_user(tg, r)
    except Exception as e:
        logger.warning(f"sync register from bot failed: {e}")


def _profile(u: dict, st: dict, bot_username: str, cooldown_left: int) -> dict:
    today = _today()
    ads_today = u.get("ads_today", 0) if u.get("ads_day") == today else 0
    return {
        "id": u["_id"], "name": u.get("name", "User"), "photo": u.get("photo", ""),
        "points": u.get("points", 0), "earned": u.get("earned", 0),
        "inr": round(u.get("points", 0) / st["points_per_inr"], 2),
        "streak": u.get("streak", 0),
        "can_checkin": u.get("last_checkin") != today,
        "ads_today": ads_today, "ads_cap": st["daily_cap"], "cooldown_left": cooldown_left,
        "ref": {
            "link": f"https://t.me/{bot_username}?start=ref_{u['_id']}" if bot_username else "",
            "count": u.get("ref_count", 0), "earned": u.get("ref_earned", 0),
        },
    }


def _cooldown_left(u: dict, st: dict) -> int:
    last = u.get("last_ad_at")
    if not last or not st["cooldown"]:
        return 0
    left = st["cooldown"] - (datetime.datetime.utcnow() - last).total_seconds()
    return max(0, int(left + 0.999))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ACTIONS  (route.py -> handle())
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def act_me(tg: dict, body: dict, bot) -> dict:
    st = await get_sync_settings()
    ref = None
    sp = str(body.get("start_param", "") or "")
    if sp.startswith("ref_") and sp[4:].isdigit():
        ref = int(sp[4:])
    u = await register_user(tg, ref)
    cfg = {k: st[k] for k in SYNC_SETTINGS}
    cfg["enabled"] = st["enabled"]
    return {"ok": True, "me": _profile(u, st, getattr(bot, "username", ""), _cooldown_left(u, st)), "config": cfg}


async def act_ad_start(tg: dict, body: dict, bot) -> dict:
    from plugins.miniapp import get_miniapp_settings, build_steps
    st = await get_sync_settings()
    if not st["enabled"]:
        return {"ok": False, "error": "disabled"}
    uid = int(tg["id"])
    u = await register_user(tg)
    today = _today()
    if u.get("ads_day") == today and u.get("ads_today", 0) >= st["daily_cap"]:
        return {"ok": False, "error": "cap"}
    left = _cooldown_left(u, st)
    if left:
        return {"ok": False, "error": "cooldown", "left": left}
    steps = build_steps((await get_miniapp_settings())["ads"], "earn")
    if not steps:
        return {"ok": False, "error": "no_ads"}
    ad = random.choice(steps)
    nonce = secrets.token_urlsafe(16)
    await _col("sync_ads").insert_one({
        "_id": nonce, "uid": uid, "used": False, "started": datetime.datetime.utcnow(),
    })
    return {"ok": True, "nonce": nonce, "ad": ad, "min_watch": st["min_watch"]}


async def act_ad_claim(tg: dict, body: dict, bot) -> dict:
    st = await get_sync_settings()
    uid = int(tg["id"])
    nonce = str(body.get("nonce", ""))[:64]
    doc = await _col("sync_ads").find_one({"_id": nonce, "uid": uid})
    if not doc or doc.get("used"):
        return {"ok": False, "error": "invalid"}
    elapsed = (datetime.datetime.utcnow() - doc["started"]).total_seconds()
    if elapsed < st["min_watch"]:
        return {"ok": False, "error": "too_fast"}
    if elapsed > 900:
        return {"ok": False, "error": "expired"}
    # nonce atomically claim (double-submit safe)
    claimed = await _col("sync_ads").find_one_and_update(
        {"_id": nonce, "uid": uid, "used": False}, {"$set": {"used": True}})
    if not claimed:
        return {"ok": False, "error": "invalid"}

    today = _today()
    await _col("sync_users").update_one(
        {"_id": uid, "ads_day": {"$ne": today}}, {"$set": {"ads_day": today, "ads_today": 0}})
    before = await _col("sync_users").find_one_and_update(
        {"_id": uid, "ads_today": {"$lt": st["daily_cap"]}},
        {"$inc": {"points": st["ad_reward"], "earned": st["ad_reward"], "ads_today": 1, "ads_total": 1},
         "$set": {"last_ad_at": datetime.datetime.utcnow()}},
        return_document=ReturnDocument.BEFORE,
    )
    if not before:
        return {"ok": False, "error": "cap"}
    await _tx(uid, "ad", st["ad_reward"], "Rewarded ad")

    # Referral: friend ka PEHLA ad poora hone par referrer ko reward (fake signup se bachav)
    if before.get("ads_total", 0) == 0 and before.get("ref_by") and not before.get("ref_rewarded") and st["ref_reward"]:
        flag = await _col("sync_users").update_one(
            {"_id": uid, "ref_rewarded": {"$ne": True}}, {"$set": {"ref_rewarded": True}})
        if flag.modified_count:
            await _col("sync_users").update_one(
                {"_id": before["ref_by"]},
                {"$inc": {"points": st["ref_reward"], "earned": st["ref_reward"],
                          "ref_count": 1, "ref_earned": st["ref_reward"]}})
            await _tx(before["ref_by"], "referral", st["ref_reward"], f"Friend joined: {before.get('name', '')}")
            try:
                await bot.send_message(
                    before["ref_by"],
                    f"<b>Referral bonus:</b> {before.get('name', 'A friend')} completed their first ad. "
                    f"+{st['ref_reward']} SP added.")
            except Exception:
                pass

    u = await _col("sync_users").find_one({"_id": uid})
    return {"ok": True, "reward": st["ad_reward"],
            "me": _profile(u, st, getattr(bot, "username", ""), _cooldown_left(u, st))}


async def act_checkin(tg: dict, body: dict, bot) -> dict:
    st = await get_sync_settings()
    uid = int(tg["id"])
    u = await register_user(tg)
    today = _today()
    if u.get("last_checkin") == today:
        return {"ok": False, "error": "done"}
    streak = u.get("streak", 0) + 1 if u.get("last_checkin") == _yesterday() else 1
    reward = st["checkin"] + min(streak - 1, 6)      # streak bonus: +1 SP/din, max +6
    res = await _col("sync_users").update_one(
        {"_id": uid, "last_checkin": {"$ne": today}},
        {"$set": {"last_checkin": today, "streak": streak},
         "$inc": {"points": reward, "earned": reward}})
    if not res.modified_count:
        return {"ok": False, "error": "done"}
    await _tx(uid, "checkin", reward, f"Day {streak} check-in")
    u = await _col("sync_users").find_one({"_id": uid})
    return {"ok": True, "reward": reward, "me": _profile(u, st, getattr(bot, "username", ""), _cooldown_left(u, st))}


async def act_history(tg: dict, body: dict, bot) -> dict:
    uid = int(tg["id"])
    rows = await _col("sync_tx").find({"uid": uid}).sort("ts", -1).limit(30).to_list(30)
    wds = await _col("sync_withdrawals").find({"uid": uid}).sort("created", -1).limit(10).to_list(10)
    return {
        "ok": True,
        "history": [{"type": r["type"], "amount": r["amount"], "note": r.get("note", ""),
                     "ts": r["ts"].isoformat() + "Z"} for r in rows],
        "withdrawals": [{"id": str(w["_id"]), "inr": w["inr"], "status": w["status"], "upi": w["upi"],
                         "ts": w["created"].isoformat() + "Z"} for w in wds],
    }


async def act_leaderboard(tg: dict, body: dict, bot) -> dict:
    rows = await _col("sync_users").find({"earned": {"$gt": 0}}).sort("earned", -1).limit(10).to_list(10)
    return {"ok": True, "top": [{"name": r.get("name", "User"), "earned": r.get("earned", 0),
                                 "photo": r.get("photo", ""), "me": r["_id"] == int(tg["id"])} for r in rows]}


async def act_withdraw(tg: dict, body: dict, bot) -> dict:
    st = await get_sync_settings()
    uid = int(tg["id"])
    if await Seishiro.is_user_banned(uid):
        return {"ok": False, "error": "banned"}
    upi = str(body.get("upi", "")).strip()
    try:
        inr = int(body.get("inr", 0))
    except (TypeError, ValueError):
        inr = 0
    if not UPI_RE.match(upi):
        return {"ok": False, "error": "bad_upi"}
    if inr < st["min_withdraw"]:
        return {"ok": False, "error": "min", "min": st["min_withdraw"]}
    pending = await _col("sync_withdrawals").count_documents({"uid": uid, "status": "pending"})
    if pending >= 2:
        return {"ok": False, "error": "pending_limit"}
    pts = inr * st["points_per_inr"]
    res = await _col("sync_users").update_one({"_id": uid, "points": {"$gte": pts}}, {"$inc": {"points": -pts}})
    if not res.modified_count:
        return {"ok": False, "error": "balance"}
    wd = {"uid": uid, "name": tg.get("first_name", ""), "inr": inr, "points": pts, "upi": upi,
          "status": "pending", "created": datetime.datetime.utcnow()}
    ins = await _col("sync_withdrawals").insert_one(wd)
    await _tx(uid, "withdraw", -pts, f"Withdrawal request Rs {inr}")
    await notify_admin_withdrawal(bot, str(ins.inserted_id), wd)
    u = await _col("sync_users").find_one({"_id": uid})
    return {"ok": True, "me": _profile(u, st, getattr(bot, "username", ""), _cooldown_left(u, st))}


async def notify_admin_withdrawal(bot, wd_id: str, wd: dict) -> None:
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    from config import OWNER_ID
    try:
        await bot.send_message(
            OWNER_ID,
            "<b>New withdrawal request</b>\n\n"
            f"<blockquote><b>User:</b> {wd.get('name', '')} (<code>{wd['uid']}</code>)\n"
            f"<b>Amount:</b> Rs {wd['inr']} ({wd['points']} SP)\n"
            f"<b>UPI:</b> <code>{wd['upi']}</code></blockquote>",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Mark Paid", callback_data=f"syncwd_ok:{wd_id}"),
                InlineKeyboardButton("Reject + Refund", callback_data=f"syncwd_no:{wd_id}"),
            ]]),
            keep=True,          # admin ki withdrawal request auto-delete nahi hogi
        )
    except Exception as e:
        logger.warning(f"withdraw admin notify failed: {e}")


async def act_tasks(tg: dict, body: dict, bot) -> dict:
    """Channel-join tasks (bot membership verify karta hai)."""
    uid = int(tg["id"])
    await register_user(tg)
    rows = await _col("sync_tasks").find({"active": True}).sort("created", 1).limit(30).to_list(30)
    done = set()
    async for d in _col("sync_task_done").find({"uid": uid}):
        done.add(d["task_id"])
    return {"ok": True, "tasks": [
        {"id": str(r["_id"]), "title": r["title"], "reward": r["reward"], "url": r["url"],
         "done": str(r["_id"]) in done} for r in rows]}


async def act_task_claim(tg: dict, body: dict, bot) -> dict:
    from bson import ObjectId
    from pymongo.errors import DuplicateKeyError
    st = await get_sync_settings()
    uid = int(tg["id"])
    await register_user(tg)
    tid = str(body.get("id", ""))[:40]
    try:
        oid = ObjectId(tid)
    except Exception:
        return {"ok": False, "error": "invalid"}
    task = await _col("sync_tasks").find_one({"_id": oid, "active": True})
    if not task:
        return {"ok": False, "error": "invalid"}
    if await _col("sync_task_done").find_one({"_id": f"{uid}:{tid}"}):
        return {"ok": False, "error": "done"}
    try:
        m = await bot.get_chat_member(task["channel_id"], uid)
        name = getattr(m.status, "name", str(m.status)).upper()
        joined = name in ("MEMBER", "ADMINISTRATOR", "OWNER") or (name == "RESTRICTED" and getattr(m, "is_member", False))
    except Exception as e:
        if type(e).__name__ == "UserNotParticipant":
            joined = False
        else:
            logger.warning(f"task verify failed ({task['channel_id']}): {e}")
            return {"ok": False, "error": "verify_failed"}
    if not joined:
        return {"ok": False, "error": "not_joined"}
    try:
        await _col("sync_task_done").insert_one({"_id": f"{uid}:{tid}", "uid": uid, "task_id": tid,
                                                 "ts": datetime.datetime.utcnow()})
    except DuplicateKeyError:
        return {"ok": False, "error": "done"}
    await _col("sync_users").update_one({"_id": uid}, {"$inc": {"points": task["reward"], "earned": task["reward"]}})
    await _tx(uid, "task", task["reward"], f"Task: {task['title']}")
    u = await _col("sync_users").find_one({"_id": uid})
    return {"ok": True, "reward": task["reward"],
            "me": _profile(u, st, getattr(bot, "username", ""), _cooldown_left(u, st))}


def _mask(name: str) -> str:
    n = (name or "User").strip()
    return (n[0] + "***" + (n[-1] if len(n) > 2 else "")).strip()


async def act_payouts(tg: dict, body: dict, bot) -> dict:
    """Public payout proof: asli 'paid' withdrawals (naam masked)."""
    rows = await _col("sync_withdrawals").find({"status": "paid"}).sort("decided", -1).limit(15).to_list(15)
    cnt = tot = 0
    async for r in _col("sync_withdrawals").aggregate(
            [{"$match": {"status": "paid"}}, {"$group": {"_id": None, "c": {"$sum": 1}, "t": {"$sum": "$inr"}}}]):
        cnt, tot = r["c"], r["t"]
    return {"ok": True, "count": cnt, "total": tot, "items": [
        {"who": _mask(r.get("name", "")), "inr": r["inr"], "ref": (r.get("ref") or "")[-4:],
         "ts": (r.get("decided") or r["created"]).isoformat() + "Z"} for r in rows]}


ACTIONS = {
    "me": act_me, "ad_start": act_ad_start, "ad_claim": act_ad_claim, "checkin": act_checkin,
    "history": act_history, "leaderboard": act_leaderboard, "withdraw": act_withdraw,
    "tasks": act_tasks, "task_claim": act_task_claim, "payouts": act_payouts,
}


async def handle(action: str, tg: dict, body: dict, bot) -> dict:
    fn = ACTIONS.get(action)
    if not fn:
        return {"ok": False, "error": "unknown"}
    if await Seishiro.is_user_banned(int(tg["id"])):
        return {"ok": False, "error": "banned"}
    return await fn(tg, body, bot)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ADMIN-side data helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def sync_stats() -> dict:
    users = await _col("sync_users").count_documents({})
    pending = await _col("sync_withdrawals").count_documents({"status": "pending"})
    paid_cur = _col("sync_withdrawals").aggregate([
        {"$match": {"status": "paid"}}, {"$group": {"_id": None, "t": {"$sum": "$inr"}}}])
    paid = 0
    async for r in paid_cur:
        paid = r["t"]
    pts_cur = _col("sync_users").aggregate([{"$group": {"_id": None, "p": {"$sum": "$points"}, "e": {"$sum": "$earned"}}}])
    bal = earned = 0
    async for r in pts_cur:
        bal, earned = r["p"], r["e"]
    return {"users": users, "pending": pending, "paid_inr": paid, "balance_pts": bal, "earned_pts": earned}
