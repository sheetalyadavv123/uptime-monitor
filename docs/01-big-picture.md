# 1. The big picture

## In one sentence

You tell the app *"watch this website"*, and it checks the site again and again, keeps the history, and warns you when the site goes down or comes back.

## The parts

```mermaid
flowchart TB
    subgraph Outside["Outside world"]
        User["You (browser, curl, script)"]
        AI["AI assistant (Claude...)"]
        Sites["Websites being watched"]
        Hook["Your alert webhook"]
    end

    subgraph App["The app (ONE Python process)"]
        direction TB
        subgraph Doors["Front doors"]
            REST["REST API<br/>app/routers/"]
            MCP["MCP server<br/>app/mcp_server.py"]
        end
        Services["Services (the logic)<br/>app/services/"]
        subgraph BG["Background tasks<br/>app/workers/scheduler.py"]
            Sched["Scheduler loop"]
            Queue["Queue"]
            Workers["5 workers"]
            Clean["Cleanup loop"]
        end
    end

    DB[("Database<br/>PostgreSQL or SQLite")]

    User --> REST
    AI --> MCP
    REST --> Services
    MCP --> Services
    Sched --> Queue --> Workers --> Services
    Clean --> Services
    Services --> DB
    Workers -- "HTTP request" --> Sites
    Services -- "alert (POST)" --> Hook
```

Everything runs inside one Python process started by `uvicorn app.main:app`.
When it starts, `app/main.py` also starts the background tasks. When it stops, they stop too.

## The life of one check

This is the most important flow in the app. Follow the numbers.

```mermaid
sequenceDiagram
    autonumber
    participant S as Scheduler loop
    participant DB as Database
    participant Q as Queue
    participant W as Worker
    participant Site as Website
    participant H as Webhook

    S->>DB: Which monitors are due? (next_check_at <= now)
    DB-->>S: monitor 7
    S->>DB: Claim it: next_check_at = now + interval
    S->>Q: put(7)
    W->>Q: get() -> 7
    W->>DB: Load monitor 7
    W->>Site: GET https://example.com
    Site-->>W: 503 Service Unavailable
    W->>DB: Save CheckResult (is_up = false)
    W->>W: decide_next_state (3rd failure in a row -> DOWN)
    W->>DB: Update status = down, open an Incident
    W->>H: POST {"event": "monitor.down", ...}
```

Code for each step:

| Step | Where |
|---|---|
| 1-3 | `claim_due_monitors` in `app/services/monitoring.py`, called by `_scheduler_loop` in `app/workers/scheduler.py` |
| 4-5 | `_worker_loop` in `app/workers/scheduler.py` |
| 6-7 | `perform_http_check` in `app/services/checks.py` |
| 8-10 | `run_check` in `app/services/monitoring.py` and `decide_next_state` in `app/services/incidents.py` |
| 11 | `send_alert` in `app/services/alerts.py` |

## The life of one API request

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant R as Router<br/>(routers/monitors.py)
    participant D as Dependencies<br/>(dependencies.py)
    participant S as Service<br/>(services/monitors.py)
    participant DB as Database

    C->>R: POST /api/v1/monitors  + token + JSON body
    R->>R: FastAPI validates the JSON with MonitorCreate
    R->>D: Who is the user? (token -> user)
    D->>DB: Load the user
    D-->>R: user
    R->>S: create_monitor(session, user.id, data)
    S->>DB: INSERT monitor
    S-->>R: monitor
    R-->>C: 201 Created + JSON (MonitorRead)
```

More detail in [doc 2](02-fastapi-basics.md).

## The life of one MCP call

```mermaid
sequenceDiagram
    autonumber
    participant You
    participant AI as AI assistant
    participant M as MCP server<br/>(mcp_server.py)
    participant S as Services

    You->>AI: "Is anything down?"
    AI->>M: call tool get_incidents(only_open=true)<br/>+ Authorization: Bearer upm_...
    M->>M: ApiKeyVerifier checks the key -> user id
    M->>S: list_incidents(session, user_id, only_open=True)
    S-->>M: incidents
    M-->>AI: structured result
    AI-->>You: "Yes, example.com has been down since 14:02 (HTTP 503)."
```

More detail in [doc 3](03-fastmcp-basics.md) and [doc 9](09-mcp-server.md).

## Key design decisions (and why)

| Decision | Why |
|---|---|
| Logic lives in `services/`, not in routes | The REST API and the MCP server share it. Write once, test once. |
| The database is the source of truth for "what is due" (`next_check_at`) | Nothing is lost if the app restarts, and several copies of the app can share the work. |
| "Claim" a monitor before checking it | Two workers (or two app copies) never check the same monitor at the same time. |
| DOWN only after N failures in a row | One network hiccup should not wake you at 3 am. |
| Alerts are sent *after* the result is saved | A broken webhook can never make us lose data. |
| Async code (`async` / `await`) | One process can wait for many slow websites at the same time. |
| PostgreSQL for production, SQLite for learning and tests | SQLite needs no installation. Tests also pass on PostgreSQL. |
| Pinned library versions | Everyone gets the exact same, tested setup. |

## What is NOT in this project (on purpose)

A frontend, email sending, billing, and multi-region checks. They are natural extensions, see the exercises in [doc 13](13-glossary-and-exercises.md).
