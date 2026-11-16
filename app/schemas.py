# =============================================================================
# schemas.py  -  THE SHAPE OF DATA GOING IN AND OUT
# =============================================================================
# Do not confuse these with models.py!
#
#   models.py    =  how data is stored in the DATABASE (tables)
#   schemas.py   =  how data looks in the API / MCP (JSON)
#
# Why keep them apart? Because we never want to send everything we store.
# For example the User table has `hashed_password`, but UserRead below does
# not, so the password hash can never leak by accident.
#
# These classes are "Pydantic models". Pydantic does two jobs for us:
#   1. VALIDATION: if someone sends interval_seconds=5 but the minimum is 30,
#      Pydantic rejects the request with a clear error. We write no `if` checks.
#   2. DOCUMENTATION: FastAPI reads these classes and builds the interactive
#      docs page (/docs) automatically. FastMCP uses them to describe tool
#      outputs to the AI.
#
# Naming rule used in this project:
#   XxxCreate   data needed to create something
#   XxxUpdate   data allowed when changing something (all fields optional)
#   XxxRead     data we send back
#
# Read more: docs/02-fastapi-basics.md
# =============================================================================

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl


# ----- Users and login -------------------------------------------------------


# What a person sends to register.
class UserCreate(BaseModel):
    email: EmailStr
    # Min 8 characters. Max 128 stops someone sending a gigantic "password" to slow us down.
    password: str = Field(min_length=8, max_length=128)


# What we send back about a user. Notice: no password!
class UserRead(BaseModel):
    # from_attributes=True lets Pydantic read the data straight from a database object.
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    created_at: datetime


# What we send back after a successful login.
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ----- API keys --------------------------------------------------------------


# What a user sends to create an API key.
class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100, examples=["Claude Desktop"])


# How we describe an existing key. The secret itself is NOT here, only the prefix.
class ApiKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    key_prefix: str
    created_at: datetime
    last_used_at: datetime | None


# Returned ONLY once, right after creating a key. It contains the full secret key.
class ApiKeyCreated(ApiKeyRead):
    key: str


# ----- Monitors --------------------------------------------------------------

# A reusable type: "a whole number of seconds between 30 seconds and 1 day".
IntervalSeconds = Annotated[int, Field(ge=30, le=86400)]


# What a user sends to create a monitor.
# Only `name` and `url` are required. Everything else has a sensible default.
class MonitorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100, examples=["My website"])
    # HttpUrl checks that this really is an http:// or https:// address.
    url: HttpUrl = Field(examples=["https://example.com"])
    interval_seconds: IntervalSeconds = 60
    expected_status: int = Field(default=200, ge=100, le=599)
    # How many failed checks in a row before we call the site DOWN.
    # This avoids false alarms caused by one random network hiccup.
    failure_threshold: int = Field(default=3, ge=1, le=10)
    # Optional: we POST a JSON message to this address when the status changes.
    alert_webhook_url: HttpUrl | None = None


# What a user sends to change a monitor. Every field is optional:
# only the fields that are sent will be changed.
class MonitorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    url: HttpUrl | None = None
    interval_seconds: IntervalSeconds | None = None
    expected_status: int | None = Field(default=None, ge=100, le=599)
    failure_threshold: int | None = Field(default=None, ge=1, le=10)
    alert_webhook_url: HttpUrl | None = None
    # Setting this to False pauses the monitor, True resumes it.
    is_active: bool | None = None


# What we send back about a monitor.
class MonitorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    url: str
    interval_seconds: int
    expected_status: int
    failure_threshold: int
    is_active: bool
    alert_webhook_url: str | None
    status: str  # "unknown", "up" or "down"
    consecutive_failures: int
    last_checked_at: datetime | None
    created_at: datetime


# ----- Checks, incidents and reports -----------------------------------------


# The result of one check of a website.
class CheckResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    monitor_id: int
    checked_at: datetime
    is_up: bool
    status_code: int | None
    response_time_ms: int | None
    error: str | None


# One outage. `resolved_at` is None while the site is still down.
class IncidentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    monitor_id: int
    started_at: datetime
    resolved_at: datetime | None
    reason: str | None


# A summary of how a monitor performed over a period of time.
class UptimeReport(BaseModel):
    monitor_id: int
    period_hours: int
    total_checks: int
    failed_checks: int
    # None when there were no checks in the period (we cannot divide by zero).
    uptime_percent: float | None
    average_response_ms: float | None
    incident_count: int


# A quick overview of all monitors of one user.
class Summary(BaseModel):
    total_monitors: int
    up: int
    down: int
    unknown: int
    paused: int
    open_incidents: int
