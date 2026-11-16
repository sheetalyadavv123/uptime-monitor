# =============================================================================
# models.py  -  THE DATABASE TABLES
# =============================================================================
# Each class in this file is ONE table in the database:
#
#   User          a person who signed up
#   ApiKey        a secret key a user creates so an AI tool (MCP) can act as them
#   Monitor       one website we are watching
#   CheckResult   the answer we got from ONE check of ONE website
#   Incident      a period of time when a website was down
#
# How they connect:
#   User 1---many Monitor 1---many CheckResult
#                         1---many Incident
#   User 1---many ApiKey
#
# A class attribute like `email: Mapped[str]` means "this table has an email
# column which holds text". SQLAlchemy turns these classes into SQL for us.
#
# IMPORTANT: if you change a table here, you must also create a migration
# (see docs/05-database.md).
# =============================================================================

from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.database import Base


# Returns the current time in UTC. We always work in UTC inside the app,
# and only convert to a local time zone when showing things to a human.
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# A custom column type for dates.
# Problem: SQLite forgets time zones, so a saved UTC time comes back "naive"
# (without a time zone) and comparing it with a normal time crashes.
# Fix: we store the time as plain UTC, and always return it with UTC attached.
# This makes SQLite and PostgreSQL behave the same.
class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    # Runs when saving: convert to UTC and drop the time zone label.
    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Please use time-zone aware datetimes (use utcnow()).")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    # Runs when loading: attach the UTC label again.
    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


# The three states a monitor can be in.
# StrEnum means each value is also a normal string ("up", "down", "unknown"),
# so it is easy to store in the database and to show in JSON.
class MonitorStatus(StrEnum):
    UNKNOWN = "unknown"  # not enough checks yet
    UP = "up"  # the website is answering correctly
    DOWN = "down"  # the website failed several checks in a row


# TABLE: users
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # unique=True: two users cannot share an email. index=True: fast lookups by email.
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    # We NEVER store the real password, only a one-way "hash" of it.
    hashed_password: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# TABLE: api_keys
# An API key lets the MCP server know which user is calling.
class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    # ondelete="CASCADE": if the user is deleted, their keys are deleted too.
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    # The first few characters of the key. Safe to show, helps users tell keys apart.
    key_prefix: Mapped[str] = mapped_column(String(12))
    # We only store a hash of the key, never the key itself (same idea as passwords).
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)


# TABLE: monitors
# One row = one website that we check again and again.
class Monitor(Base):
    __tablename__ = "monitors"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    url: Mapped[str] = mapped_column(String(2048))

    # --- Settings chosen by the user ---
    interval_seconds: Mapped[int] = mapped_column(Integer, default=60)  # check every N seconds
    expected_status: Mapped[int] = mapped_column(Integer, default=200)  # the "healthy" HTTP status
    failure_threshold: Mapped[int] = mapped_column(Integer, default=3)  # failures in a row before DOWN
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # False = paused
    alert_webhook_url: Mapped[str | None] = mapped_column(String(2048), default=None)

    # --- Current state, updated by the monitoring engine ---
    status: Mapped[str] = mapped_column(String(10), default=MonitorStatus.UNKNOWN.value)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    # The scheduler looks at this column to find out which monitors are due.
    next_check_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    # An index makes "find all active monitors that are due" fast, even with
    # thousands of monitors. The scheduler runs this query every few seconds.
    __table_args__ = (Index("ix_monitors_due", "is_active", "next_check_at"),)


# TABLE: check_results
# One row = one check of one website. This table grows fast, so old rows
# are deleted regularly (see app/workers/scheduler.py).
class CheckResult(Base):
    __tablename__ = "check_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    monitor_id: Mapped[int] = mapped_column(ForeignKey("monitors.id", ondelete="CASCADE"))
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    is_up: Mapped[bool] = mapped_column(Boolean)
    status_code: Mapped[int | None] = mapped_column(Integer, default=None)  # None if no answer at all
    response_time_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    error: Mapped[str | None] = mapped_column(String(500), default=None)

    # Most queries are "results of monitor X, newest first", so index both columns.
    __table_args__ = (Index("ix_check_results_monitor_time", "monitor_id", "checked_at"),)


# TABLE: incidents
# One row = one outage. `resolved_at` stays empty (None) while the site is still down.
class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    monitor_id: Mapped[int] = mapped_column(ForeignKey("monitors.id", ondelete="CASCADE"))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    reason: Mapped[str | None] = mapped_column(String(500), default=None)

    __table_args__ = (Index("ix_incidents_monitor_started", "monitor_id", "started_at"),)
