# 5. The database

## The tables

```mermaid
erDiagram
    USERS ||--o{ API_KEYS : "has"
    USERS ||--o{ MONITORS : "owns"
    MONITORS ||--o{ CHECK_RESULTS : "has history of"
    MONITORS ||--o{ INCIDENTS : "has outages"

    USERS {
        int id PK
        string email UK
        string hashed_password
        datetime created_at
    }
    API_KEYS {
        int id PK
        int user_id FK
        string name
        string key_prefix
        string key_hash UK
        datetime created_at
        datetime last_used_at
    }
    MONITORS {
        int id PK
        int user_id FK
        string name
        string url
        int interval_seconds
        int expected_status
        int failure_threshold
        bool is_active
        string alert_webhook_url
        string status
        int consecutive_failures
        datetime last_checked_at
        datetime next_check_at
        datetime created_at
    }
    CHECK_RESULTS {
        int id PK
        int monitor_id FK
        datetime checked_at
        bool is_up
        int status_code
        int response_time_ms
        string error
    }
    INCIDENTS {
        int id PK
        int monitor_id FK
        datetime started_at
        datetime resolved_at
        string reason
    }
```

`PK` = primary key (unique id of the row), `FK` = foreign key (a link to a row in another table), `UK` = unique.

All of this is defined as Python classes in `app/models.py`.

## What each table is for

| Table | One row is... | Grows how fast? |
|---|---|---|
| `users` | one person | slowly |
| `api_keys` | one secret key for the MCP server (only its **hash** is stored) | slowly |
| `monitors` | one website being watched, plus its **current** state | slowly |
| `check_results` | the answer of **one check** | **fast** (1 row per check) |
| `incidents` | one outage | slowly |

## Current state vs history

```mermaid
flowchart LR
    subgraph Now["Current state (monitors table)"]
        A["status = down<br/>consecutive_failures = 4<br/>last_checked_at"]
    end
    subgraph History["History (other tables)"]
        B["check_results<br/>one row per check"]
        C["incidents<br/>one row per outage"]
    end
    Now -. "updated after every check" .- History
```

The monitor row answers "what is it **now**?" fast. The history tables answer "what **happened**?".

## Important columns

| Column | Why it exists |
|---|---|
| `monitors.next_check_at` | The scheduler asks "which monitors have `next_check_at <= now`?". After claiming a monitor, we set it to `now + interval`. This is the whole scheduling mechanism ([doc 7](07-monitoring-engine.md)). |
| `monitors.consecutive_failures` | Counts failed checks in a row. Reaching `failure_threshold` makes the monitor DOWN ([doc 8](08-incidents-and-alerts.md)). |
| `incidents.resolved_at` | `NULL` (None) means the outage is **still happening**. |
| `api_keys.key_hash` | We store only a hash of the key. If the database leaks, the keys cannot be used. |
| `check_results.status_code` | `NULL` when we got no answer (timeout, DNS error...). |

## Indexes: why lookups stay fast

An **index** is like the index at the back of a book: the database can jump to the right rows instead of reading the whole table.

| Index | Used by | Why it matters |
|---|---|---|
| `monitors (is_active, next_check_at)` | the scheduler, every 5 seconds | must stay fast with thousands of monitors |
| `check_results (monitor_id, checked_at)` | history and reports | "last 50 checks of monitor 5" without scanning millions of rows |
| `incidents (monitor_id, started_at)` | incident lists | same idea |
| `users (email)` unique | login | fast lookup and no duplicate emails |
| `api_keys (key_hash)` unique | every MCP call | fast key lookup |

## Deleting data (cascade)

Foreign keys use `ON DELETE CASCADE`:

```mermaid
flowchart LR
    D["Delete a monitor"] --> A["its check_results are deleted by the database"]
    D --> B["its incidents are deleted by the database"]
```

We do not write code for this; the database does it. (`app/database.py` turns on foreign keys for SQLite, which has them off by default.)

Old check results are also deleted regularly: results older than `CHECK_RETENTION_DAYS` (default 30) are removed by the cleanup loop, so the table does not grow forever.

## Sessions and transactions in simple words

A **session** is one conversation with the database. You queue changes, then `commit()` saves them **all together**: either everything is saved, or nothing.

```python
session.add(result)             # queue: save this check result
monitor.status = "down"         # queue: change the monitor
await session.commit()          # save both at once
```

This is why `run_check` can never end up with a saved result but a wrong status.

## Migrations: changing tables safely

When you change `models.py` (new column, new table), existing databases must change too. A **migration** is a small script that does this step. They live in `alembic/versions/` and work like git commits for your tables.

```mermaid
flowchart LR
    E["Edit models.py"] --> G["alembic revision --autogenerate -m 'add column'"]
    G --> R["Review the new file in alembic/versions/"]
    R --> U["alembic upgrade head"]
    U --> DB[("Database is updated")]
```

| Command | What it does |
|---|---|
| `alembic upgrade head` | Apply all new migrations (also creates tables the first time) |
| `alembic revision --autogenerate -m "message"` | Create a migration by comparing `models.py` with the database |
| `alembic downgrade -1` | Undo the last migration |
| `alembic current` | Show which version the database is at |
| `alembic check` | Fail if `models.py` and the migrations disagree |

**Always read an auto-generated migration before applying it.** One known quirk in this project: autogenerate writes our custom `UTCDateTime` type into the file; replace it with `sa.DateTime()` (see `alembic/versions/0001_create_tables.py` for how it was done). Both are the same column in the database.

In Docker, the container runs `alembic upgrade head` automatically each time it starts.

## SQLite vs PostgreSQL

| | SQLite | PostgreSQL |
|---|---|---|
| Setup | None (a single file) | A database server |
| Use for | Learning, tests | **Production** |
| Several app copies | Not safe | Safe (`skip_locked`, see [doc 7](07-monitoring-engine.md)) |
| Heavy parallel writes | Can lock | Handles well |

The same code runs on both. The 91 tests pass on both ([doc 11](11-testing.md)). The only line that changes is `DATABASE_URL`:

```
sqlite+aiosqlite:///./uptime.db                          (SQLite)
postgresql+asyncpg://user:password@host:5432/dbname      (PostgreSQL)
```

## The date/time trap (and how we avoid it)

SQLite forgets time zones, PostgreSQL may not. Comparing a "naive" time with an "aware" one crashes Python. We solved it once, in `UTCDateTime` (`models.py`): every date is stored as plain UTC and always returned with UTC attached. Everywhere else you simply use `utcnow()`.

## Where to look in the code

| Topic | File |
|---|---|
| Tables | `app/models.py` |
| Engine and sessions | `app/database.py` |
| Migrations | `alembic/`, `alembic.ini` |
| Counting queries (uptime %) | `app/services/reports.py` |
