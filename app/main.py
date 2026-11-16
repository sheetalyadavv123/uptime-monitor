# =============================================================================
# main.py  -  THE ENTRY POINT: WHERE EVERYTHING IS PLUGGED TOGETHER
# =============================================================================
# This is the file the server starts. Run it with:
#
#       uvicorn app.main:app --reload
#
# which means: "in the file app/main.py, run the object called `app`".
#
# What this file does, in order:
#   1. Creates the FastAPI app.
#   2. Defines the STARTUP and SHUTDOWN steps (the "lifespan").
#   3. Plugs in the REST routers (auth, api keys, monitors, health).
#   4. Teaches the app how to turn our AppErrors into JSON error responses.
#   5. Mounts the MCP server so AI tools can reach it at /mcp.
#
# After starting, open:
#   http://localhost:8000/docs   interactive API documentation
#   http://localhost:8000/mcp    the MCP endpoint (for AI tools, not browsers)
#
# Read more: docs/01-big-picture.md
# =============================================================================

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.errors import AppError, AuthenticationError
from app.mcp_server import mcp
from app.routers import api_keys, auth, health, monitors
from app.workers.scheduler import Scheduler

# Show log messages (INFO and above) with a timestamp and the module name.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

# Creates the MCP web app. `path="/mcp"` is the address inside that app.
# We need this object early because its startup steps must run together with ours.
mcp_app = mcp.http_app(path="/mcp")


# THE LIFESPAN: code that runs once at startup (before `yield`)
# and once at shutdown (after `yield`).
#
# Startup order:
#   1. Check the settings are safe.
#   2. Start the MCP app's own startup steps (it needs them to work).
#   3. Start the background workers that check websites.
# Shutdown happens in the reverse order.
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.check_is_safe_to_run()

    scheduler = Scheduler() if settings.run_background_workers else None
    async with mcp_app.lifespan(app):
        if scheduler:
            await scheduler.start()
        try:
            yield  # <- the app is running and serving requests here
        finally:
            if scheduler:
                await scheduler.stop()


# Creates the app. The title and description appear on the /docs page.
app = FastAPI(
    title=settings.app_name,
    description="Watches websites and tells you when they go down. "
    "Has a REST API and an MCP server for AI assistants.",
    version="1.0.0",
    lifespan=lifespan,
)


# Our services raise AppError (and its children). This function catches them
# anywhere in the app and turns them into a clean JSON answer such as
#   404  {"detail": "Monitor not found."}
@app.exception_handler(AppError)
async def handle_app_error(request: Request, error: AppError) -> JSONResponse:
    headers = {}
    if isinstance(error, AuthenticationError):
        # The standard way to tell a client "send a Bearer token".
        headers["WWW-Authenticate"] = "Bearer"
    return JSONResponse(
        status_code=error.status_code,
        content={"detail": error.message},
        headers=headers,
    )


# A friendly page at "/" so that newcomers know where to go next.
@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {"name": settings.app_name, "docs": "/docs", "mcp": "/mcp", "health": "/health"}


# Plug in the routers. Each one adds its own group of URLs.
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(api_keys.router)
app.include_router(monitors.router)

# Mount the MCP app. This must come LAST: a mount at "/" catches every URL that
# the routers above did not handle, and the MCP app answers the ones starting
# with /mcp.
app.mount("/", mcp_app)
