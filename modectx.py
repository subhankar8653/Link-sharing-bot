"""
modectx.py — "link mode" context (A = normal, B = alag settings wala mode).

Bot ek hi hai, settings/flow ke do set: mode "a" (purana, default) aur mode "b".
Jis update ko handle kiya ja raha hai uska mode yahan ContextVar mein rehta hai;
database.py aur plugins/premium.py isi se decide karte hain ki kaunsa set padhna/likhna hai.
"""
from contextvars import ContextVar

_MODE: ContextVar = ContextVar("link_mode", default="a")


def cur() -> str:
    return _MODE.get()


def set_mode(mode: str) -> None:
    _MODE.set("b" if mode == "b" else "a")


def is_b() -> bool:
    return _MODE.get() == "b"


def wrap_param(param: str) -> str:
    """Mode B mein /start payload ko wapas B link format mein (b_<b64> / breq_<b64>) — Joined/Try again button ke liye."""
    if not is_b() or not param or param.startswith(("b_", "breq_", "vfy_", "ref_")) or param == "premium":
        return param
    return "breq_" + param[4:] if param.startswith("req_") else "b_" + param


def banner() -> str:
    """Settings panel ke upar dikhne wala mode label."""
    return "🅱️ <b>B MODE</b> — yahan ki saari settings sirf B links ke liye hain\n\n" if is_b() else ""
