def format_uptime(total_seconds: int) -> str:
    """'Xd HH:MM:SS' (or plain 'HH:MM:SS' under a day) - used for the
    title bar's live uptime readout, see AppController.uptime_changed."""
    total_seconds = max(0, int(total_seconds))
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    if days:
        return f"{days}d {hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
