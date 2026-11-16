# =============================================================================
# services/users.py  -  CREATING USERS AND CHECKING LOGINS
# =============================================================================
# "Services" hold the real logic of the app. They know nothing about HTTP or
# MCP: they receive plain values and a database session, and return objects.
# Because of that, both the REST routes and the MCP tools can reuse them.
#
# Read more: docs/04-folder-structure.md
# =============================================================================

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import AuthenticationError, ConflictError
from app.models import User
from app.security import DUMMY_PASSWORD_HASH, hash_password, verify_password


# Creates a new user. Emails are stored in lowercase so "A@x.com" and "a@x.com"
# count as the same person. Raises ConflictError if the email is already taken.
async def register_user(session: AsyncSession, email: str, password: str) -> User:
    email = email.lower()

    # Friendly check first...
    existing = await session.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise ConflictError("A user with this email already exists.")

    user = User(email=email, hashed_password=hash_password(password))
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        # ...and a safety net: two people registering the same email at the
        # exact same moment would both pass the check above, but the database's
        # "unique" rule on the email column stops the second one.
        await session.rollback()
        raise ConflictError("A user with this email already exists.")
    return user


# Checks an email + password. Returns the user, or raises AuthenticationError.
async def authenticate_user(session: AsyncSession, email: str, password: str) -> User:
    user = await session.scalar(select(User).where(User.email == email.lower()))

    if user is None:
        # Do the slow password check anyway, so that "no such email" and
        # "wrong password" take the same time (see security.py).
        verify_password(password, DUMMY_PASSWORD_HASH)
        raise AuthenticationError("Incorrect email or password")

    if not verify_password(password, user.hashed_password):
        raise AuthenticationError("Incorrect email or password")

    return user
