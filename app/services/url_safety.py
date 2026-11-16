# =============================================================================
# url_safety.py  -  STOPPING USERS FROM ATTACKING OUR OWN NETWORK (SSRF)
# =============================================================================
# THE PROBLEM
# Our app makes web requests to addresses typed in by users. A bad user could
# type  http://localhost:5432  or  http://169.254.169.254  (a cloud server's
# secret metadata address) and make OUR server talk to places only it can reach.
# This attack is called SSRF (Server-Side Request Forgery).
#
# THE FIX
# Before we request an address, we look up which IP addresses it points to.
# If ANY of them is private (localhost, 192.168.x.x, 10.x.x.x, ...) we refuse.
#
# We run this check in two places:
#   1. When a monitor is created or edited  -> fast, friendly error message.
#   2. Right before EVERY real request (including redirects) -> see http_client.py
#
# Known limit: an attacker who controls DNS could answer differently between our
# check and the real request ("DNS rebinding"). See docs/10-security.md.
# =============================================================================

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

from app.config import settings
from app.errors import InvalidInputError


# Raises InvalidInputError if the URL points to a private or unreachable address.
async def ensure_public_url(url: str) -> None:
    # Tests (and special setups) can turn this check off with ALLOW_PRIVATE_URLS=true.
    if settings.allow_private_urls:
        return

    host = urlparse(url).hostname
    if not host:
        raise InvalidInputError("The URL has no host name.")

    # Ask the operating system which IP addresses this host name points to.
    # We use the async version so that we do not block the whole server while waiting.
    loop = asyncio.get_running_loop()
    try:
        addresses = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise InvalidInputError(f"Could not find the host '{host}'.")

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        # `is_global` is True only for normal internet addresses.
        # It is False for localhost, private networks, link-local, etc.
        if not ip.is_global:
            raise InvalidInputError("Private or local addresses are not allowed.")
