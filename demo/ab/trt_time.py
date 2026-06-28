def iso_utc(dt) -> str:
    """Given a timezone-aware UTC datetime dt, format it as an ISO-8601 UTC string."""
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
