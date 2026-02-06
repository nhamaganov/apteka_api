from datetime import datetime, timedelta, timezone

UTC_PLUS_8 = timezone(timedelta(hours=8))

def now_iso() -> str:
    return datetime.now(UTC_PLUS_8).isoformat()
