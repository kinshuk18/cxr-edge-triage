"""RS256 bearer-token verification and tenant extraction."""

import base64
from typing import Optional

from fastapi import Header, HTTPException
import jwt

from app.config import settings


def _public_key() -> str:
    value = settings.jwt_public_key_b64.strip()
    if not value:
        raise HTTPException(status_code=503, detail="JWT public key is not configured")
    try:
        return base64.b64decode(value, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=503, detail="JWT public key is invalid") from exc


def decode_bearer(token: str) -> dict:
    try:
        claims = jwt.decode(
            token,
            _public_key(),
            algorithms=["RS256"],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "aud", "iss", "tenant"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid bearer token") from exc
    tenant = claims.get("tenant")
    if not isinstance(tenant, str) or not tenant or len(tenant) > 128:
        raise HTTPException(status_code=401, detail="Token has no valid tenant claim")
    return claims


async def require_tenant(
    authorization: Optional[str] = Header(default=None),
) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    token = authorization[7:].strip()
    if not token or len(token) > 16_384:
        raise HTTPException(status_code=401, detail="Invalid bearer token")
    return decode_bearer(token)["tenant"]
