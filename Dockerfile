# =============================================================================
# Dockerfile  -  HOW TO PACKAGE THE APP INTO A CONTAINER
# =============================================================================
# A Docker image is a sealed box containing Python, our libraries and our code,
# so the app runs the same way on every computer and server.
# Each line below is one step. Read more: docs/12-deployment.md
# =============================================================================

# Start from a small official image that already has Python 3.13.
FROM python:3.13-slim

# Do not create .pyc files, and print logs immediately instead of buffering them.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /code

# Install libraries FIRST, in their own step. Docker remembers (caches) each
# step, so when only our code changes, this slow step is skipped on rebuilds.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Now copy our code and the migration files.
COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app

# Do not run as the all-powerful "root" user: if the app were ever hacked,
# the attacker would have far fewer rights.
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

# Docker calls this regularly to find out if the app is healthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# When the container starts:
#   1. apply database migrations (creates / updates the tables),
#   2. start the server.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
