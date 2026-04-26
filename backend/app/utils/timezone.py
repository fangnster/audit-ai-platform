from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import settings


def app_timezone() -> ZoneInfo:
    try:
        return ZoneInfo(settings.APP_TIMEZONE)
    except ZoneInfoNotFoundError:
        return ZoneInfo("Asia/Shanghai")


def local_now() -> datetime:
    return datetime.now(app_timezone())


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def local_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _aware(value).astimezone(app_timezone()).isoformat(timespec="seconds")


def local_display(value: datetime | None = None) -> str:
    local_value = (_aware(value) if value else local_now()).astimezone(app_timezone())
    offset = local_value.strftime("%z")
    pretty_offset = f"{offset[:3]}:{offset[3:]}" if offset else ""
    return f"{local_value:%Y-%m-%d %H:%M:%S} {pretty_offset}".strip()
