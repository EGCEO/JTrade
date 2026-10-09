"""Heartbeat freshness and provenance shared by status cards and the safety gate."""
from datetime import datetime
from app.models import BotState


def heartbeat_status(bot):
    age = ((datetime.utcnow() - bot.last_heartbeat).total_seconds()
           if bot.last_heartbeat else None)
    stale = age is None or not 0 <= age <= 60
    active = bot.state == BotState.running and not bot.paused and not stale
    source = bot.heartbeat_source or "unknown"
    return {
        "stale": stale,
        "active": active,
        "heartbeat_age_seconds": round(age) if age is not None else None,
        "heartbeat_source": source,
        "external_active": active and source == "external" and not bot.last_error,
    }
