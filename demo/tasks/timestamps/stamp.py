from datetime import datetime, timezone


def iso_utc(dt: datetime) -> str:
    # Obvious isoformat() — but THIS repo wants a trailing "Z", not "+00:00".
    return dt.astimezone(timezone.utc).isoformat()
