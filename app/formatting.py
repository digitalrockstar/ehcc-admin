import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

from .config import TIMEZONE


def inr(value, signed: bool = False) -> str:
    """Indian digit grouping: 1234567.5 -> ₹12,34,567.50"""
    if value is None:
        return "—"
    v = Decimal(str(value)).quantize(Decimal("0.01"))
    neg = v < 0
    v = abs(v)
    whole, frac = f"{v:.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    if head:
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts) + "," + tail
    out = "₹" + whole + ("" if frac == "00" else "." + frac)
    if neg:
        return "-" + out
    return ("+" + out) if signed and v > 0 else out


def dmy(d) -> str:
    return d.strftime("%d %b %Y") if d else ""


def ist(value: dt.datetime | None) -> str:
    if not value:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(ZoneInfo(TIMEZONE)).strftime("%d %b %Y, %H:%M")


def mask_mobile(mob: str | None) -> str:
    if not mob:
        return ""
    return "•" * max(len(mob) - 4, 0) + mob[-4:]
