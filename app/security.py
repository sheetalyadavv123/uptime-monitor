# =============================================================================
# security.py  -  PASSWORDS, LOGIN TOKENS AND API KEYS
# =============================================================================
# This file has the small building blocks for security. It does NOT talk to the
# database or to FastAPI; it only transforms data. That makes it easy to test.
#
# 1. PASSWORDS   We never store passwords. We store a "hash": a scrambled
#                version that cannot be turned back into the password.
#                To log in, we hash what the user typed and compare the hashes.
#
# 2. JWT TOKENS  After login the user gets a token (a signed piece of text).
#                It says "this is user 7, valid until 15:30". The user sends it
#                with every request. We can trust it because only we know the
#                secret key that signs it.
#
# 3. API KEYS    Long random keys for the MCP server. We show the key ONCE,
#                and store only its hash.
#
# Read more: docs/06-authentication.md
# =============================================================================

import hashlib
import secrets
from datetime import timedelta

import jwt
from pwdlib import PasswordHash

from app.config import settings
from app.errors import AuthenticationError
from app.models import utcnow

# ----- Passwords -------------------------------------------------------------

# `recommended()` picks Argon2, a modern algorithm that is deliberately slow,
# which makes guessing passwords very expensive for attackers.
_password_hasher = PasswordHash.recommended()

# A fake hash used when the email does not exist (see authenticate_user).
# It lets us spend the same time on "unknown email" and "wrong password",
# so attackers cannot learn which emails are registered by measuring speed.
DUMMY_PASSWORD_HASH = _password_hasher.hash("this-is-not-a-real-password")


# Turns a plain password into a safe hash we can store.
def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


# Checks if a typed password matches a stored hash.
def verify_password(password: str, hashed_password: str) -> bool:
    return _password_hasher.verify(password, hashed_password)


# ----- JWT login tokens ------------------------------------------------------

JWT_ALGORITHM = "HS256"


# Creates a signed token that says "this is user <id>" and expires soon.
# "sub" (subject) and "exp" (expiry) are standard names defined by the JWT spec.
def create_access_token(user_id: int) -> str:
    expires_at = utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": str(user_id), "exp": expires_at}
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)


# Reads a token and returns the user id inside it.
# Raises AuthenticationError if the token is fake, changed, or expired.
def decode_access_token(token: str) -> int:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[JWT_ALGORITHM])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise AuthenticationError("Invalid or expired token")


# ----- API keys --------------------------------------------------------------

API_KEY_PREFIX = "upm_"  # "upm" = uptime monitor. Makes keys easy to recognise.


# Turns an API key into a fixed-length hash.
# SHA-256 is fine here (unlike for passwords) because API keys are long random
# values, so they cannot be guessed. It also lets us find a key by its hash.
def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


# Creates a brand new key. Returns (full_key, prefix, hash).
#   full_key  shown to the user once, never stored
#   prefix    first characters, stored so the user can recognise the key later
#   hash      stored, used to check keys
def generate_api_key() -> tuple[str, str, str]:
    full_key = API_KEY_PREFIX + secrets.token_urlsafe(32)
    return full_key, full_key[:8], hash_api_key(full_key)
