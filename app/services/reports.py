# =============================================================================
# services/reports.py  -  NUMBERS AND SUMMARIES
# =============================================================================
# Two read-only reports:
#   uptime_report   "How did this monitor do in the last N hours?"
#   get_summary     "How are ALL my monitors doing right now?"
#
# We let the DATABASE do the counting (COUNT, SUM, AVG) instead of loading
# thousands of rows into Python. Databases are built for this and it is much
# faster and uses far less memory.
# =============================================================================

from datetime import timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CheckResult, Incident, Monitor, MonitorStatus, utcnow
from app.schemas import Summary, UptimeReport


# Builds the uptime report of one monitor for the last `hours` hours.
# Uptime % = passed checks / total checks * 100
async def uptime_report(session: AsyncSession, monitor_id: int, hours: int) -> UptimeReport:
    since = utcnow() - timedelta(hours=hours)

    # One query that returns: how many checks, how many failed, average speed.
    row = (
        await session.execute(
            select(
                func.count(CheckResult.id),
                func.sum(case((CheckResult.is_up.is_(False), 1), else_=0)),
                func.avg(CheckResult.response_time_ms),
            ).where(CheckResult.monitor_id == monitor_id, CheckResult.checked_at >= since)
        )
    ).one()
    total_checks = row[0]
    failed_checks = int(row[1] or 0)  # SUM gives None when there are no rows
    average_ms = row[2]

    incident_count = await session.scalar(
        select(func.count(Incident.id)).where(
            Incident.monitor_id == monitor_id, Incident.started_at >= since
        )
    )

    # With zero checks we cannot calculate a percentage, so we return None.
    uptime_percent = None
    if total_checks > 0:
        uptime_percent = round((total_checks - failed_checks) / total_checks * 100, 2)

    return UptimeReport(
        monitor_id=monitor_id,
        period_hours=hours,
        total_checks=total_checks,
        failed_checks=failed_checks,
        uptime_percent=uptime_percent,
        average_response_ms=round(average_ms, 1) if average_ms is not None else None,
        incident_count=incident_count or 0,
    )


# Counts the user's monitors by status, plus how many incidents are open.
async def get_summary(session: AsyncSession, user_id: int) -> Summary:
    rows = (
        await session.execute(
            select(Monitor.status, Monitor.is_active, func.count(Monitor.id))
            .where(Monitor.user_id == user_id)
            .group_by(Monitor.status, Monitor.is_active)
        )
    ).all()

    counts = {"total": 0, "up": 0, "down": 0, "unknown": 0, "paused": 0}
    for status, is_active, number in rows:
        counts["total"] += number
        if not is_active:
            counts["paused"] += number  # paused monitors are counted separately
        elif status == MonitorStatus.UP:
            counts["up"] += number
        elif status == MonitorStatus.DOWN:
            counts["down"] += number
        else:
            counts["unknown"] += number

    open_incidents = await session.scalar(
        select(func.count(Incident.id))
        .join(Monitor, Monitor.id == Incident.monitor_id)
        .where(Monitor.user_id == user_id, Incident.resolved_at.is_(None))
    )

    return Summary(
        total_monitors=counts["total"],
        up=counts["up"],
        down=counts["down"],
        unknown=counts["unknown"],
        paused=counts["paused"],
        open_incidents=open_incidents or 0,
    )
