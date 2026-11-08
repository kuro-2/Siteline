"""Rate limits (slowapi, in memory: fine for one API instance)."""

from __future__ import annotations

import hashlib

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def user_or_ip(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth:
        return "u:" + hashlib.sha256(auth.encode()).hexdigest()[:16]
    return "ip:" + get_remote_address(request)


limiter = Limiter(key_func=get_remote_address, default_limits=[])
