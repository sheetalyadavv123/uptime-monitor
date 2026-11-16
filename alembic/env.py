# =============================================================================
# alembic/env.py  -  CONFIGURATION FOR DATABASE MIGRATIONS
# =============================================================================
# WHAT IS A MIGRATION?
# Your tables change over time (a new column, a new table...). A migration is
# a small numbered script that changes the database from one version to the
# next. They live in alembic/versions/ and work like "git commits" for the
# database structure.
#
# Commands you will use (run them in the project folder):
#   alembic upgrade head                          apply all migrations (creates the tables)
#   alembic revision --autogenerate -m "message"  create a new migration after editing models.py
#   alembic downgrade -1                          undo the last migration
#
# This file is run by Alembic every time you use one of those commands.
# It only does two things: find out WHICH database to use (from our settings),
# and tell Alembic WHAT our tables should look like (from models.py).
#
# Read more: docs/05-database.md
# =============================================================================

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.database import Base
from app import models  # noqa: F401  (importing it registers all tables on Base)

# Alembic compares this "wanted" structure with the real database to
# generate migrations automatically.
target_metadata = Base.metadata


# Applies the migrations using an open database connection.
# `render_as_batch` lets SQLite change tables the way other databases do.
def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# Connects to the database (using the URL from our settings) and runs migrations.
async def run_async_migrations() -> None:
    engine = create_async_engine(settings.database_url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


# "Offline mode" only prints the SQL instead of running it.
# Useful when you want to hand the SQL to a database administrator.
def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
