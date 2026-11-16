# =============================================================================
# routers/monitors.py  -  THE MAIN API: MANAGE AND VIEW MONITORS
# =============================================================================
#   POST   /api/v1/monitors                     create a monitor
#   GET    /api/v1/monitors                     list your monitors
#   GET    /api/v1/monitors/{id}                one monitor
#   PATCH  /api/v1/monitors/{id}                change a monitor (also pause / resume)
#   DELETE /api/v1/monitors/{id}                delete a monitor
#   POST   /api/v1/monitors/{id}/check-now      run a check right now
#   GET    /api/v1/monitors/{id}/checks         history of checks
#   GET    /api/v1/monitors/{id}/incidents      outages of this monitor
#   GET    /api/v1/monitors/{id}/report         uptime numbers for a period
#   GET    /api/v1/incidents                    outages across all your monitors
#   GET    /api/v1/summary                      overview of everything
#
# Every route needs a logged-in user (`user: CurrentUser`), and the service
# functions only return data that belongs to that user.
#
# Read more: docs/02-fastapi-basics.md
# =============================================================================

from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.dependencies import CurrentUser, SessionDep
from app.schemas import (
    CheckResultRead,
    IncidentRead,
    MonitorCreate,
    MonitorRead,
    MonitorUpdate,
    Summary,
    UptimeReport,
)
from app.services import incidents as incident_service
from app.services import monitoring as monitoring_service
from app.services import monitors as monitor_service
from app.services import reports as report_service

router = APIRouter(prefix="/api/v1", tags=["Monitors"])

# Reusable "query parameters" for pagination, for example  ?limit=20&offset=40
# `ge` = "greater or equal", `le` = "less or equal". FastAPI rejects bad values.
Limit = Annotated[int, Query(ge=1, le=200, description="How many items to return")]
Offset = Annotated[int, Query(ge=0, description="How many items to skip")]


@router.post("/monitors", response_model=MonitorRead, status_code=201)
async def create_monitor(payload: MonitorCreate, session: SessionDep, user: CurrentUser):
    """Start monitoring a website."""
    return await monitor_service.create_monitor(session, user.id, payload)


@router.get("/monitors", response_model=list[MonitorRead])
async def list_monitors(
    session: SessionDep, user: CurrentUser, limit: Limit = 50, offset: Offset = 0
):
    """List your monitors, newest first."""
    return await monitor_service.list_monitors(session, user.id, limit, offset)


@router.get("/summary", response_model=Summary)
async def get_summary(session: SessionDep, user: CurrentUser):
    """How many monitors are up, down, paused, and how many incidents are open."""
    return await report_service.get_summary(session, user.id)


@router.get("/incidents", response_model=list[IncidentRead])
async def list_incidents(
    session: SessionDep,
    user: CurrentUser,
    only_open: bool = False,
    limit: Limit = 50,
    offset: Offset = 0,
):
    """Outages across all your monitors. Use ?only_open=true for ongoing ones."""
    return await incident_service.list_incidents(
        session, user.id, only_open=only_open, limit=limit, offset=offset
    )


@router.get("/monitors/{monitor_id}", response_model=MonitorRead)
async def get_monitor(monitor_id: int, session: SessionDep, user: CurrentUser):
    """Details and current status of one monitor."""
    return await monitor_service.get_monitor(session, user.id, monitor_id)


# PATCH means "change only some fields". Fields not in the request stay as they are.
@router.patch("/monitors/{monitor_id}", response_model=MonitorRead)
async def update_monitor(
    monitor_id: int, payload: MonitorUpdate, session: SessionDep, user: CurrentUser
):
    """Change a monitor. Send {"is_active": false} to pause it."""
    monitor = await monitor_service.get_monitor(session, user.id, monitor_id)
    return await monitor_service.update_monitor(session, monitor, payload)


@router.delete("/monitors/{monitor_id}", status_code=204)
async def delete_monitor(monitor_id: int, session: SessionDep, user: CurrentUser):
    """Delete a monitor together with its history."""
    monitor = await monitor_service.get_monitor(session, user.id, monitor_id)
    await monitor_service.delete_monitor(session, monitor)
    return Response(status_code=204)


@router.post("/monitors/{monitor_id}/check-now", response_model=CheckResultRead)
async def check_now(monitor_id: int, session: SessionDep, user: CurrentUser):
    """Check the website right now instead of waiting for the next scheduled check."""
    monitor = await monitor_service.get_monitor(session, user.id, monitor_id)
    return await monitoring_service.run_check(session, monitor)


@router.get("/monitors/{monitor_id}/checks", response_model=list[CheckResultRead])
async def list_checks(
    monitor_id: int, session: SessionDep, user: CurrentUser, limit: Limit = 50, offset: Offset = 0
):
    """History of checks for one monitor, newest first."""
    monitor = await monitor_service.get_monitor(session, user.id, monitor_id)
    return await monitor_service.list_check_results(session, monitor.id, limit, offset)


@router.get("/monitors/{monitor_id}/incidents", response_model=list[IncidentRead])
async def list_monitor_incidents(
    monitor_id: int,
    session: SessionDep,
    user: CurrentUser,
    only_open: bool = False,
    limit: Limit = 50,
    offset: Offset = 0,
):
    """Outages of one monitor."""
    monitor = await monitor_service.get_monitor(session, user.id, monitor_id)
    return await incident_service.list_incidents(
        session, user.id, monitor_id=monitor.id, only_open=only_open, limit=limit, offset=offset
    )


@router.get("/monitors/{monitor_id}/report", response_model=UptimeReport)
async def get_report(
    monitor_id: int,
    session: SessionDep,
    user: CurrentUser,
    hours: Annotated[int, Query(ge=1, le=720, description="Length of the period in hours")] = 24,
):
    """Uptime percentage, average speed and incident count for the last N hours."""
    monitor = await monitor_service.get_monitor(session, user.id, monitor_id)
    return await report_service.uptime_report(session, monitor.id, hours)
