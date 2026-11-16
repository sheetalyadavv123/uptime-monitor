# =============================================================================
# services/api_keys.py  -  CREATING AND CHECKING API KEYS
# =============================================================================
# API keys are how an AI tool (through MCP) proves which user it acts for.
# The flow:
#   1. The user logs in to the REST API and creates a key.   (create_api_key)
#   2. The user pastes that key into the AI tool's settings.
#   3. On every MCP call, the AI tool sends the key.
#   4. We look the key up and learn the user id.              (find_user_id_by_key)
#
# Read more: docs/06-authentication.md
# =============================================================================

from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import NotFoundError
from app.models import ApiKey, utcnow
from app.security import generate_api_key, hash_api_key


# Creates a key for a user. Returns the saved row AND the full secret key.
# The full key is not stored anywhere, so this is the only time it can be shown.
async def create_api_key(session: AsyncSession, user_id: int, name: str) -> tuple[ApiKey, str]:
    full_key, prefix, key_hash = generate_api_key()
    api_key = ApiKey(user_id=user_id, name=name, key_prefix=prefix, key_hash=key_hash)
    session.add(api_key)
    await session.commit()
    return api_key, full_key


# Lists all keys of a user (without the secrets), newest first.
async def list_api_keys(session: AsyncSession, user_id: int) -> list[ApiKey]:
    result = await session.scalars(
        select(ApiKey).where(ApiKey.user_id == user_id).order_by(ApiKey.created_at.desc())
    )
    return list(result)


# Deletes one key. The key stops working immediately.
# We include user_id in the query so nobody can delete someone else's key.
async def delete_api_key(session: AsyncSession, user_id: int, key_id: int) -> None:
    result = await session.execute(
        delete(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user_id)
    )
    if result.rowcount == 0:
        raise NotFoundError("API key not found.")
    await session.commit()


# Finds which user owns a key. Returns the user id, or None if the key is unknown.
async def find_user_id_by_key(session: AsyncSession, raw_key: str) -> int | None:
    api_key = await session.scalar(select(ApiKey).where(ApiKey.key_hash == hash_api_key(raw_key)))
    if api_key is None:
        return None

    # Remember when the key was last used, but only update once a minute
    # so that we do not write to the database on every single MCP call.
    now = utcnow()
    if api_key.last_used_at is None or now - api_key.last_used_at > timedelta(minutes=1):
        api_key.last_used_at = now
        await session.commit()

    return api_key.user_id
