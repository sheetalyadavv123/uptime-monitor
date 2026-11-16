# =============================================================================
# mcp_server.py  -  THE MCP SERVER (LETS AI TOOLS USE THE APP)
# =============================================================================
# WHAT IS MCP?
# MCP (Model Context Protocol) is a standard way for an AI assistant, like
# Claude, to use outside tools. Our MCP server says to the AI:
#   "Here are things you can do: list monitors, add a monitor, get a report..."
# The AI reads those descriptions, and when you chat ("what went down last
# night?") it decides which tool to call and explains the result to you.
#
# MCP has three kinds of things you can offer:
#   TOOL       An action the AI can run (can change data).      -> @mcp.tool
#   RESOURCE   Read-only data the AI can look at.               -> @mcp.resource
#   PROMPT     A ready-made instruction template for the user.  -> @mcp.prompt
#
# IMPORTANT: the docstring of every tool is NOT just a comment. FastMCP sends
# it to the AI, and the AI uses it to decide when and how to call the tool.
# So tool docstrings are written for the AI, and "#" comments for you.
#
# This file contains NO business logic. Every tool calls the same service
# functions as the REST API (app/services/). We wrote the logic once, and we
# have two front doors.
#
# Read more: docs/03-fastmcp-basics.md and docs/09-mcp-server.md
# =============================================================================

from pydantic import Field, ValidationError

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import Middleware

from app.database import SessionLocal
from app.errors import AppError
from app.schemas import (
    CheckResultRead,
    IncidentRead,
    MonitorCreate,
    MonitorRead,
    MonitorUpdate,
    UptimeReport,
)
from app.services import api_keys as api_key_service
from app.services import incidents as incident_service
from app.services import monitoring as monitoring_service
from app.services import monitors as monitor_service
from app.services import reports as report_service


# -----------------------------------------------------------------------------
# AUTHENTICATION: who is calling?
# -----------------------------------------------------------------------------
# For every MCP request FastMCP reads the header  Authorization: Bearer <key>
# and calls `verify_token` below. If we return None the request is rejected
# with a 401 error and no tool runs. If we return an AccessToken, the request
# continues, and the tools can find out who the user is (see _current_user_id).
class ApiKeyVerifier(TokenVerifier):
    # FastMCP calls this with the key from the Authorization header.
    # Returns who the caller is, or None if the key is not valid.
    async def verify_token(self, token: str) -> AccessToken | None:
        async with SessionLocal() as session:
            user_id = await api_key_service.find_user_id_by_key(session, token)
        if user_id is None:
            return None
        # `claims` is a free place to store extra facts. We store the user id.
        return AccessToken(token=token, client_id=str(user_id), scopes=[], claims={"user_id": user_id})


# -----------------------------------------------------------------------------
# ERROR TRANSLATION
# -----------------------------------------------------------------------------
# "Middleware" is code that wraps every call. This one catches our AppErrors
# (like "Monitor not found.") and turns them into ToolErrors. FastMCP sends a
# ToolError message to the AI, so the AI can explain the problem to the user.
class ErrorTranslationMiddleware(Middleware):
    # Runs around every tool call. `call_next` runs the real tool.
    async def on_call_tool(self, context, call_next):
        try:
            return await call_next(context)
        except AppError as error:
            raise ToolError(error.message) from error


# Creates the MCP server object. All tools below are attached to it.
# `instructions` is a short description the AI sees when it connects.
mcp = FastMCP(
    name="Uptime Monitor",
    instructions=(
        "Manage website uptime monitors. You can list and add monitors, check a "
        "site right now, see recent checks and incidents, and get uptime reports."
    ),
    auth=ApiKeyVerifier(),
)
mcp.add_middleware(ErrorTranslationMiddleware())


# Finds out which user is calling, using the AccessToken from ApiKeyVerifier.
def _current_user_id() -> int:
    token = get_access_token()
    if token is None:
        raise ToolError("You are not authenticated.")
    return token.claims["user_id"]


# -----------------------------------------------------------------------------
# TOOLS
# -----------------------------------------------------------------------------
# `@mcp.tool` turns a normal Python function into a tool:
#   - the function name becomes the tool name,
#   - the parameters (with their types) become the tool's inputs,
#   - the docstring becomes the description the AI reads,
#   - the return type becomes the structured output.
#
# `annotations` are hints for the AI app. For example readOnlyHint=True says
# "this tool never changes anything", so the app can run it without asking you.


@mcp.tool(annotations={"readOnlyHint": True})
async def list_monitors() -> list[MonitorRead]:
    """List all website monitors of the user, with their current status (up, down or unknown)."""
    async with SessionLocal() as session:
        monitors = await monitor_service.list_monitors(session, _current_user_id(), limit=200)
        return [MonitorRead.model_validate(monitor) for monitor in monitors]


@mcp.tool(annotations={"readOnlyHint": True})
async def get_monitor(monitor_id: int) -> MonitorRead:
    """Get the details and current status of one monitor by its id."""
    async with SessionLocal() as session:
        monitor = await monitor_service.get_monitor(session, _current_user_id(), monitor_id)
        return MonitorRead.model_validate(monitor)


@mcp.tool
async def add_monitor(name: str, url: str, interval_seconds: int = 60) -> MonitorRead:
    """Start monitoring a website. The url must start with http:// or https://.
    interval_seconds is how often to check (minimum 30, default 60)."""
    # We reuse the same MonitorCreate schema as the REST API, so the rules
    # (minimum interval, valid URL...) are identical in both places.
    try:
        data = MonitorCreate(name=name, url=url, interval_seconds=interval_seconds)
    except ValidationError as error:
        raise ToolError(f"Invalid input: {error.errors()[0]['msg']}") from error

    async with SessionLocal() as session:
        monitor = await monitor_service.create_monitor(session, _current_user_id(), data)
        return MonitorRead.model_validate(monitor)


@mcp.tool
async def pause_monitor(monitor_id: int) -> MonitorRead:
    """Pause a monitor so it is no longer checked. Its history is kept."""
    async with SessionLocal() as session:
        monitor = await monitor_service.get_monitor(session, _current_user_id(), monitor_id)
        monitor = await monitor_service.update_monitor(session, monitor, MonitorUpdate(is_active=False))
        return MonitorRead.model_validate(monitor)


@mcp.tool
async def resume_monitor(monitor_id: int) -> MonitorRead:
    """Resume a paused monitor. It is checked again within seconds."""
    async with SessionLocal() as session:
        monitor = await monitor_service.get_monitor(session, _current_user_id(), monitor_id)
        monitor = await monitor_service.update_monitor(session, monitor, MonitorUpdate(is_active=True))
        return MonitorRead.model_validate(monitor)


# destructiveHint=True warns the AI app that this tool deletes data,
# so it will usually ask the human to confirm first.
@mcp.tool(annotations={"destructiveHint": True})
async def delete_monitor(monitor_id: int) -> str:
    """Permanently delete a monitor and all of its history. This cannot be undone."""
    async with SessionLocal() as session:
        monitor = await monitor_service.get_monitor(session, _current_user_id(), monitor_id)
        await monitor_service.delete_monitor(session, monitor)
    return f"Monitor {monitor_id} was deleted."


@mcp.tool
async def check_now(monitor_id: int) -> CheckResultRead:
    """Check a website right now and return the result, instead of waiting for the next scheduled check."""
    async with SessionLocal() as session:
        monitor = await monitor_service.get_monitor(session, _current_user_id(), monitor_id)
        result = await monitoring_service.run_check(session, monitor)
        return CheckResultRead.model_validate(result)


@mcp.tool(annotations={"readOnlyHint": True})
async def get_recent_checks(monitor_id: int, limit: int = Field(10, ge=1, le=100)) -> list[CheckResultRead]:
    """Get the most recent checks of a monitor (newest first), including status codes, response times and errors."""
    async with SessionLocal() as session:
        monitor = await monitor_service.get_monitor(session, _current_user_id(), monitor_id)
        results = await monitor_service.list_check_results(session, monitor.id, limit=limit)
        return [CheckResultRead.model_validate(result) for result in results]


@mcp.tool(annotations={"readOnlyHint": True})
async def get_incidents(
    monitor_id: int | None = None,
    only_open: bool = False,
    limit: int = Field(20, ge=1, le=100),
) -> list[IncidentRead]:
    """List outages (incidents), newest first. Give monitor_id to see one monitor only.
    Set only_open=true to see only outages that are still happening."""
    async with SessionLocal() as session:
        incidents = await incident_service.list_incidents(
            session, _current_user_id(), monitor_id=monitor_id, only_open=only_open, limit=limit
        )
        return [IncidentRead.model_validate(incident) for incident in incidents]


@mcp.tool(annotations={"readOnlyHint": True})
async def get_uptime_report(monitor_id: int, hours: int = Field(24, ge=1, le=720)) -> UptimeReport:
    """Get the uptime percentage, average response time and incident count of a monitor for the last N hours."""
    async with SessionLocal() as session:
        monitor = await monitor_service.get_monitor(session, _current_user_id(), monitor_id)
        return await report_service.uptime_report(session, monitor.id, hours)


# -----------------------------------------------------------------------------
# RESOURCE
# -----------------------------------------------------------------------------
# A resource is read-only data with an address (a URI). The AI app can attach
# it to the conversation as context, without the AI having to call a tool.
@mcp.resource("uptime://summary", mime_type="application/json")
async def summary_resource() -> str:
    """A quick overview: how many monitors are up, down, paused, and how many incidents are open."""
    async with SessionLocal() as session:
        summary = await report_service.get_summary(session, _current_user_id())
    return summary.model_dump_json()


# -----------------------------------------------------------------------------
# PROMPT
# -----------------------------------------------------------------------------
# A prompt is a reusable template the USER can pick (in many AI apps it shows
# up like a slash command). It returns text that is sent to the AI.
@mcp.prompt
def investigate_incident(monitor_id: int) -> str:
    """Ask the AI to investigate why a monitor is failing and explain it simply."""
    return (
        f"Please investigate monitor {monitor_id}. "
        "First call get_monitor, then get_recent_checks and get_incidents for it. "
        "Explain in simple words what is wrong (status codes, errors, timing), "
        "when it started, and what I should check first."
    )
