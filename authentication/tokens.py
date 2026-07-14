from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from django.conf import settings

from accounts.models import UserAccount


JWT_ALGORITHM = "HS256"


class TokenError(Exception):
    """Invalid or expired token."""


def create_access_token(user: UserAccount) -> tuple[str, datetime]:
    """Create a JWT for a company user."""
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.JWT_ACCESS_TOKEN_LIFETIME_MINUTES
    )
    payload = {
        "user_id": str(user.id),
        "company_id": str(user.company_id),
        "exp": expires_at,
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return token, expires_at


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode a JWT."""
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Invalid token.") from exc
