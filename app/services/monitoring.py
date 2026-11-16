# =============================================================================
# services/monitoring.py  -  THE HEART OF THE APP: RUNNING CHECKS
# =============================================================================
# This file connects all the small pieces:
#
#   claim_due_monitors      "Which monitors need a check right now?"
#   check_monitor_by_id     "Check this monitor" (used by background workers)
#   run_check               The full recipe for one check (see below)
#   delete_old_results      Housekeeping: remove old check results
#
# The background loops that CALL these functions live in
# app/workers/scheduler.py. The REST API also calls run_check for the
# "check now" button.
#
# Read more: docs/07-monitoring-engine.md
# =============================================================================

import logging
from datetime import timedelta

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import SessionLocal
from app.models import CheckResult, Monitor, utcnow
from app.services.alerts import send_alert
from app.services.checks import perform_http_check
from app.services.incidents import (
    StatusEvent,
    close_open_incidents,
    decide_next_state,
    open_incident,
)

logger = logging.getLogger(__name__)


# Finds monitors that are due for a check and "claims" them.
#
# Claiming means: we immediately move their next_check_at into the future.
# So even if this function runs again a moment later (or runs in a second
# copy of the app), the same monitor is not picked twice.
#
# On PostgreSQL, `skip_locked` makes two copies of the app skip rows that the
# other copy is currently claiming. SQLite ignores that option (and is only
# meant for development).
async def claim_due_monitors(session: AsyncSession, limit: int = 100) -> list[int]:
    now = utcnow()
    due_monitors = await session.scalars(
        select(Monitor)
        .where(Monitor.is_active.is_(True), Monitor.next_check_at <= now)
        .order_by(Monitor.next_check_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )

    claimed_ids = []
    for monitor in due_monitors:
        monitor.next_check_at = now + timedelta(seconds=monitor.interval_seconds)
        claimed_ids.append(monitor.id)

    await session.commit()
    return claimed_ids


# THE RECIPE FOR ONE CHECK
#   1. Request the website.
#   2. Save the result.
#   3. Update the monitor's status (using the rules in incidents.py).
#   4. Open or close an incident if the status changed.
#   5. Send an alert if the status changed.
#
# `check_client` and `alert_client` are only passed in by tests.
async def run_check(
    session: AsyncSession,
    monitor: Monitor,
    check_client: httpx.AsyncClient | None = None,
    alert_client: httpx.AsyncClient | None = None,
) -> CheckResult:
    # Ending the current transaction gives the database connection back to the
    # pool while we wait for the website, which can take up to 10 seconds.
    # (Our objects stay usable because of expire_on_commit=False in database.py.)
    await session.commit()

    # 1. Request the website.
    outcome = await perform_http_check(
        monitor.url, monitor.expected_status, settings.request_timeout_seconds, client=check_client
    )

    # 2. Save the result.
    result = CheckResult(
        monitor_id=monitor.id,
        is_up=outcome.is_up,
        status_code=outcome.status_code,
        response_time_ms=outcome.response_time_ms,
        error=outcome.error,
    )
    session.add(result)

    # 3. Update the monitor's status.
    next_state = decide_next_state(
        monitor.status, monitor.consecutive_failures, outcome.is_up, monitor.failure_threshold
    )
    monitor.status = next_state.status
    monitor.consecutive_failures = next_state.consecutive_failures
    monitor.last_checked_at = utcnow()

    # 4. Open or close an incident.
    if next_state.event == StatusEvent.WENT_DOWN:
        open_incident(session, monitor.id, outcome.error)
    elif next_state.event == StatusEvent.RECOVERED:
        await close_open_incidents(session, monitor.id)

    # Save everything together: either all of it is saved or none of it.
    await session.commit()

    # 5. Send the alert AFTER saving, so that a slow or broken webhook can
    # never cause us to lose the check result.
    if next_state.event is not None:
        await send_alert(monitor, next_state.event, outcome.error, client=alert_client)

    return result


# Used by the background workers: opens its own database session, loads the
# monitor, and runs one check. Does nothing if the monitor was deleted or paused
# after it was queued.
async def check_monitor_by_id(monitor_id: int) -> None:
    async with SessionLocal() as session:
        monitor = await session.get(Monitor, monitor_id)
        if monitor is None or not monitor.is_active:
            return
        await run_check(session, monitor)


# Deletes check results older than the retention period.
# Returns how many rows were deleted.
async def delete_old_results(session: AsyncSession) -> int:
    cutoff = utcnow() - timedelta(days=settings.check_retention_days)
    result = await session.execute(delete(CheckResult).where(CheckResult.checked_at < cutoff))
    await session.commit()
    return result.rowcount
