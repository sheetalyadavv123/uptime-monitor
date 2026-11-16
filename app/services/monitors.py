# =============================================================================
# services/monitors.py  -  CREATE, READ, UPDATE AND DELETE MONITORS
# =============================================================================
# This is the "CRUD" part of the app (Create, Read, Update, Delete).
#
# SECURITY RULE USED EVERYWHERE IN THIS FILE:
# Every query filters by `user_id`. That way a user can only ever see and
# change their OWN monitors. If someone asks for a monitor that belongs to
# another user, we answer "not found" (not "forbidden"), so we do not even
# reveal that the monitor exists.
# =============================================================================

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.errors import LimitExceededError, NotFoundError
from app.models import CheckResult, Monitor, utcnow
from app.schemas import MonitorCreate, MonitorUpdate
from app.services.url_safety import ensure_public_url


# Creates a monitor. The first check happens within a few seconds, because we
# set next_check_at to "now" and the scheduler picks up due monitors.
async def create_monitor(session: AsyncSession, user_id: int, data: MonitorCreate) -> Monitor:
    # Enforce the per-user limit.
    current_count = await session.scalar(
        select(func.count()).select_from(Monitor).where(Monitor.user_id == user_id)
    )
    if current_count >= settings.max_monitors_per_user:
        raise LimitExceededError(
            f"You can have at most {settings.max_monitors_per_user} monitors."
        )

    # Refuse private addresses (see url_safety.py).
    url = str(data.url)
    await ensure_public_url(url)
    webhook_url = str(data.alert_webhook_url) if data.alert_webhook_url else None
    if webhook_url:
        await ensure_public_url(webhook_url)

    monitor = Monitor(
        user_id=user_id,
        name=data.name,
        url=url,
        interval_seconds=data.interval_seconds,
        expected_status=data.expected_status,
        failure_threshold=data.failure_threshold,
        alert_webhook_url=webhook_url,
        next_check_at=utcnow(),
    )
    session.add(monitor)
    await session.commit()
    return monitor


# Returns a page of the user's monitors, newest first.
# `limit` and `offset` are "pagination": the client asks for 50 rows at a time.
async def list_monitors(
    session: AsyncSession, user_id: int, limit: int = 50, offset: int = 0
) -> list[Monitor]:
    result = await session.scalars(
        select(Monitor)
        .where(Monitor.user_id == user_id)
        .order_by(Monitor.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result)


# Returns one monitor, but only if it belongs to this user.
async def get_monitor(session: AsyncSession, user_id: int, monitor_id: int) -> Monitor:
    monitor = await session.scalar(
        select(Monitor).where(Monitor.id == monitor_id, Monitor.user_id == user_id)
    )
    if monitor is None:
        raise NotFoundError("Monitor not found.")
    return monitor


# Changes a monitor. Only the fields the client actually sent are changed.
async def update_monitor(
    session: AsyncSession, monitor: Monitor, data: MonitorUpdate
) -> Monitor:
    # `exclude_unset=True` gives us ONLY the fields that were in the request.
    # This is how we tell "not sent" apart from "sent as null".
    changes = data.model_dump(exclude_unset=True)

    for field, value in changes.items():
        # Only the webhook may be set to null (that means "remove it").
        if value is None and field != "alert_webhook_url":
            continue
        # URLs arrive as special URL objects; we store them as plain text.
        if field in ("url", "alert_webhook_url") and value is not None:
            value = str(value)
            await ensure_public_url(value)
        setattr(monitor, field, value)

    # When a monitor is resumed, check it again right away.
    if changes.get("is_active") is True:
        monitor.next_check_at = utcnow()

    await session.commit()
    return monitor


# Deletes a monitor. Its check results and incidents are removed by the
# database itself (we set ondelete="CASCADE" on those tables).
async def delete_monitor(session: AsyncSession, monitor: Monitor) -> None:
    await session.delete(monitor)
    await session.commit()


# Returns a page of check results for a monitor, newest first.
# The caller must already have verified that the monitor belongs to the user.
async def list_check_results(
    session: AsyncSession, monitor_id: int, limit: int = 50, offset: int = 0
) -> list[CheckResult]:
    result = await session.scalars(
        select(CheckResult)
        .where(CheckResult.monitor_id == monitor_id)
        .order_by(CheckResult.checked_at.desc(), CheckResult.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result)
