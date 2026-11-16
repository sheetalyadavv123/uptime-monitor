# =============================================================================
# database.py  -  CONNECTING TO THE DATABASE
# =============================================================================
# This file creates the three things every database-backed app needs:
#
#   engine         The connection "pool". Think of it as a phone line to the
#                  database that many parts of the app can share.
#   SessionLocal   A factory that gives us a "session". A session is one
#                  conversation with the database: we ask for rows, change
#                  them, and then `commit` to save everything at once.
#   Base           The parent class of all our table classes (see models.py).
#
# We use "async" database code. Async lets the server handle other requests
# while it waits for the database, so one process can serve many users.
#
# Read more: docs/05-database.md
# =============================================================================

from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# SQLite needs two small tweaks. PostgreSQL needs neither.
_connect_args: dict = {}
if settings.database_url.startswith("sqlite"):
    # Wait up to 30 seconds if another worker is writing at the same moment,
    # instead of failing immediately with "database is locked".
    _connect_args = {"timeout": 30}

# Create the engine. `pool_pre_ping` checks a connection is still alive before
# using it, which avoids errors after the database restarts.
engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args=_connect_args,
)

# SQLite ignores foreign keys (links between tables) unless we switch them on.
# We switch them on so that deleting a monitor also deletes its results,
# exactly like PostgreSQL does.
if settings.database_url.startswith("sqlite"):

    # This function runs every time a new SQLite connection is opened.
    @event.listens_for(engine.sync_engine, "connect")
    def _turn_on_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


# A factory that creates sessions.
# `expire_on_commit=False` keeps objects usable after we commit them,
# which is what we want in async code.
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


# The parent class for all table classes. Every class that inherits from it
# becomes a database table (see models.py).
class Base(DeclarativeBase):
    pass


# This is a FastAPI "dependency" (explained in docs/02-fastapi-basics.md).
# When a route asks for a session, FastAPI calls this function, hands over the
# session, and closes it automatically after the request is finished.
async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
