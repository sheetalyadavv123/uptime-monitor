# =============================================================================
# routers/health.py  -  "IS THE APP ALIVE?" ENDPOINTS
# =============================================================================
# Hosting platforms (Docker, Kubernetes, load balancers) call these URLs every
# few seconds to find out whether the app is healthy. They need no login.
#
#   GET /health        "Is the process running?"     (liveness)
#   GET /health/ready  "Can it reach the database?"  (readiness)
#
# A "router" is a group of related routes. main.py plugs every router into
# the app. This keeps each file small and focused.
# =============================================================================

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.dependencies import SessionDep

router = APIRouter(tags=["Health"])


# `@router.get("/health")` means: when someone sends GET /health, run this function.
# Whatever the function returns is converted to JSON automatically.
@router.get("/health")
async def liveness() -> dict:
    """Returns ok if the app is running."""
    return {"status": "ok"}


# `session: SessionDep` asks FastAPI for a database session (see dependencies.py).
@router.get("/health/ready")
async def readiness(session: SessionDep) -> dict:
    """Returns ok only if the database answers."""
    try:
        await session.execute(text("SELECT 1"))  # the simplest possible query
    except Exception:
        raise HTTPException(status_code=503, detail="Database is not reachable")
    return {"status": "ok"}
