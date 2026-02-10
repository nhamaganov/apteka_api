from datetime import datetime, timedelta, timezone

UTC_PLUS_8 = timezone(timedelta(hours=8))

def now_iso() -> str:
    """Возвращает текущее время в ISO-формате для часового пояса UTC+8."""
    return datetime.now(UTC_PLUS_8).isoformat()
