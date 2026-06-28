from datetime import datetime


def iso_utc(dt) -> str:
    """Given a timezone-aware UTC datetime dt, format it as an ISO-8601 UTC string."""
    return dt.isoformat().replace('+00:00', 'Z')
