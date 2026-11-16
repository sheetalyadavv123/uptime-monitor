# =============================================================================
# config.py  -  ALL SETTINGS OF THE APP LIVE HERE
# =============================================================================
# Settings are things that change between your laptop and a real server:
# the database address, the secret key, how many workers to run, and so on.
#
# We never write these values directly inside the code. Instead we read them
# from "environment variables" (or from a file called .env). This is how
# almost every production app is configured.
#
# How it works:
#   1. You put DATABASE_URL=... in the .env file (see .env.example).
#   2. The `Settings` class below reads it and checks it has the right type.
#   3. Any other file can do:  from app.config import settings
#                              settings.database_url
#
# Read more: docs/12-deployment.md
# =============================================================================

from pydantic_settings import BaseSettings, SettingsConfigDict

# The default secret key. It is only OK for local development.
# In production the app refuses to start if you forget to change it.
INSECURE_DEFAULT_SECRET = "insecure-dev-secret-do-not-use-in-production"
MIN_SECRET_LENGTH = 32


# One class = one list of settings.
# Each line is:  name: type = default value
# Pydantic automatically reads the matching environment variable
# (for example `database_url` is read from DATABASE_URL) and converts it
# to the right type (so "5" becomes the number 5).
class Settings(BaseSettings):
    # Tells Pydantic to also read a file called ".env" and to ignore unknown keys.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- General -------------------------------------------------------------
    app_name: str = "Uptime Monitor"
    # "development", "test" or "production". Production turns on extra safety checks.
    environment: str = "development"

    # --- Database ------------------------------------------------------------
    # SQLite is a single file: perfect for learning and for tests.
    # For production use PostgreSQL, for example:
    #   postgresql+asyncpg://user:password@localhost:5432/uptime
    database_url: str = "sqlite+aiosqlite:///./uptime.db"

    # --- Security ------------------------------------------------------------
    # This secret is used to sign login tokens. Anyone who knows it can fake logins!
    secret_key: str = INSECURE_DEFAULT_SECRET
    # How long a login token stays valid.
    access_token_expire_minutes: int = 60

    # --- Monitoring engine ---------------------------------------------------
    # If False, the app only serves the API and never checks websites.
    # (The tests turn this off so that nothing runs in the background.)
    run_background_workers: bool = True
    # How often the scheduler looks for monitors that are due, in seconds.
    scheduler_interval_seconds: int = 5
    # How many websites can be checked at the same time.
    worker_count: int = 5
    # How long we wait for a website to answer before calling it "down".
    request_timeout_seconds: int = 10
    # Old check results are deleted after this many days (keeps the database small).
    check_retention_days: int = 30

    # --- Safety limits -------------------------------------------------------
    # Maximum monitors one user can create.
    max_monitors_per_user: int = 50
    # Normally we REFUSE to check private addresses like localhost or 192.168.x.x,
    # otherwise a user could make our server probe our internal network (SSRF).
    # Only set this to True in tests or when you really know what you are doing.
    allow_private_urls: bool = False

    # Stops the app from starting with an unsafe setup in production.
    def check_is_safe_to_run(self) -> None:
        if self.environment != "production":
            return
        if self.secret_key == INSECURE_DEFAULT_SECRET or len(self.secret_key) < MIN_SECRET_LENGTH:
            raise RuntimeError(
                "SECRET_KEY is missing or too short. Set a random SECRET_KEY of at least "
                f"{MIN_SECRET_LENGTH} characters. Make one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )


# We create ONE settings object and every file imports this same object.
settings = Settings()
