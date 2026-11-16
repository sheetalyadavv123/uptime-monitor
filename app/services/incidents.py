# =============================================================================
# services/incidents.py  -  DECIDING WHEN A SITE IS "DOWN", AND TRACKING OUTAGES
# =============================================================================
# An INCIDENT is one outage: it starts when a monitor goes DOWN and ends when
# the monitor comes back UP.
#
# The most important function here is `decide_next_state`. It is a "pure
# function": it only looks at its inputs and returns an answer. It never
# touches the database or the network, so it is very easy to understand and
# to test. Draw it as a state machine: docs/08-incidents-and-alerts.md
# =============================================================================

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Incident, Monitor, MonitorStatus, utcnow


# The two things worth telling the user about.
class StatusEvent(StrEnum):
    WENT_DOWN = "went_down"  # the site just became DOWN  -> open an incident, send an alert
    RECOVERED = "recovered"  # the site just became UP again -> close the incident, send an alert


# The answer of decide_next_state: what the monitor looks like after this check.
@dataclass
class NextState:
    status: str
    consecutive_failures: int
    event: StatusEvent | None  # None means "nothing worth reporting happened"


# THE RULES:
#   * A passing check resets the failure counter and makes the monitor UP.
#     If it was DOWN before, that is a "recovered" event.
#   * A failing check adds 1 to the failure counter.
#     Only when the counter reaches `failure_threshold` do we mark it DOWN.
#     (One failed check can be a network hiccup. Three in a row is a real problem.)
#     If it was not DOWN before, that is a "went_down" event.
def decide_next_state(
    current_status: str,
    consecutive_failures: int,
    check_passed: bool,
    failure_threshold: int,
) -> NextState:
    if check_passed:
        event = StatusEvent.RECOVERED if current_status == MonitorStatus.DOWN else None
        return NextState(MonitorStatus.UP.value, 0, event)

    failures = consecutive_failures + 1
    if failures >= failure_threshold:
        event = StatusEvent.WENT_DOWN if current_status != MonitorStatus.DOWN else None
        return NextState(MonitorStatus.DOWN.value, failures, event)

    # Failing, but not often enough yet: keep the current status.
    return NextState(current_status, failures, None)


# Adds a new open incident to the session. The caller commits.
def open_incident(session: AsyncSession, monitor_id: int, reason: str | None) -> Incident:
    incident = Incident(monitor_id=monitor_id, reason=reason)
    session.add(incident)
    return incident


# Marks all open incidents of a monitor as resolved. The caller commits.
async def close_open_incidents(session: AsyncSession, monitor_id: int) -> None:
    open_incidents = await session.scalars(
        select(Incident).where(Incident.monitor_id == monitor_id, Incident.resolved_at.is_(None))
    )
    now = utcnow()
    for incident in open_incidents:
        incident.resolved_at = now


# Lists incidents of a user's monitors, newest first.
# We join with the monitors table so we can filter by the owner (user_id).
async def list_incidents(
    session: AsyncSession,
    user_id: int,
    monitor_id: int | None = None,
    only_open: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[Incident]:
    query = (
        select(Incident)
        .join(Monitor, Monitor.id == Incident.monitor_id)
        .where(Monitor.user_id == user_id)
    )
    if monitor_id is not None:
        query = query.where(Incident.monitor_id == monitor_id)
    if only_open:
        query = query.where(Incident.resolved_at.is_(None))

    result = await session.scalars(
        query.order_by(Incident.started_at.desc(), Incident.id.desc()).limit(limit).offset(offset)
    )
    return list(result)
