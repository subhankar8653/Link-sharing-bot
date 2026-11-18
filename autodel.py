"""
autodel.py — Bot ke bheje SAARE private-chat messages auto delete (DB-backed queue).

• Bot.send_message / send_photo / send_video ... (bot.py) har sent message yahan register karte hain.
• Delay: bot_config.auto_delete_seconds (default 600 = 10 min, 0 = off) — /settings -> Auto Delete.
• Queue MongoDB mein hai, isliye Railway restart ke baad bhi purane messages delete hote hain.
• Sirf private chats (user ke saath). Group/channel messages aur broadcast (copy) ko nahi chhuta.
• Kisi message ko rakhna ho: client.send_message(..., keep=True).
"""
import asyncio
import datetime
import logging
import time

from database.database import Seishiro

logger = logging.getLogger(__name__)
DEFAULT_DELAY = 600
_cache = {"t": 0.0, "v": DEFAULT_DELAY}
_task = None


def reset_cache() -> None:
    _cache["t"] = 0.0


async def get_delay() -> int:
    if time.time() - _cache["t"] < 30:
        return _cache["v"]
    try:
        doc = await Seishiro.database["bot_config"].find_one({"_id": "main"}) or {}
        v = int(doc.get("auto_delete_seconds", DEFAULT_DELAY))
    except Exception:
        v = DEFAULT_DELAY
    _cache.update(t=time.time(), v=max(0, v))
    return _cache["v"]


async def register(msg) -> None:
    """Bheje gaye message(s) ko delete queue mein daalo. Kabhi exception nahi uthata."""
    try:
        if msg is None:
            return
        delay = await get_delay()
        if delay <= 0:
            return
        docs = []
        at = datetime.datetime.utcnow() + datetime.timedelta(seconds=delay)
        for m in (msg if isinstance(msg, list) else [msg]):
            chat = getattr(m, "chat", None)
            cid = getattr(chat, "id", None)
            mid = getattr(m, "id", None)
            if not cid or cid <= 0 or mid is None:      # sirf private chats
                continue
            docs.append({"chat_id": cid, "msg_id": mid, "at": at})
        if docs:
            await Seishiro.database["autodel_queue"].insert_many(docs)
    except Exception as e:
        logger.debug(f"autodel register failed: {e}")


async def _loop(client) -> None:
    col = Seishiro.database["autodel_queue"]
    try:
        await col.create_index("at")
    except Exception:
        pass
    await asyncio.sleep(15)
    while True:
        try:
            now = datetime.datetime.utcnow()
            due = await col.find({"at": {"$lte": now}}).limit(300).to_list(300)
            if due:
                by = {}
                for d in due:
                    by.setdefault(d["chat_id"], []).append(d["msg_id"])
                for cid, ids in by.items():
                    for i in range(0, len(ids), 100):
                        try:
                            await client.delete_messages(cid, ids[i:i + 100])
                        except Exception as e:
                            if type(e).__name__ == "FloodWait":
                                await asyncio.sleep(getattr(e, "value", 5) + 1)
                await col.delete_many({"_id": {"$in": [d["_id"] for d in due]}})
                await asyncio.sleep(2)
            else:
                await asyncio.sleep(20)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"autodel loop error: {e}")
            await asyncio.sleep(30)


def start(client) -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop(client))
