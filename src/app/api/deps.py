import jwt
from fastapi import Depends, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import UnauthorizedError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User
from app.schemas.token import TokenPayload

settings = get_settings()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(settings.cookie_name)
    if token is None:
        raise UnauthorizedError("Not authenticated")

    try:
        payload = TokenPayload(**decode_access_token(token))
    except (jwt.InvalidTokenError, ValidationError) as exc:
        raise UnauthorizedError("Invalid or expired token") from exc

    user = db.get(User, int(payload.sub))
    if user is None:
        raise UnauthorizedError("User not found")

    return user
