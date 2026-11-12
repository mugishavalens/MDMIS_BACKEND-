import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode("utf-8"))


# A real bcrypt hash of a random password, checked when the email isn't
# found so a login for an unknown address takes as long as for a known one
# (otherwise response time reveals which emails have accounts).
DUMMY_PASSWORD_HASH = bcrypt.hashpw(secrets.token_bytes(16), bcrypt.gensalt(rounds=12)).decode("utf-8")


def _create_token(subject: str, token_type: str, expires_delta: timedelta, version: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": subject, "type": token_type, "ver": version, "iat": now, "exp": now + expires_delta}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


# version = the user's token_version when issued; tokens with an older
# version are rejected (see app.deps.get_current_user and /auth/refresh/).
def create_access_token(user_id: str, version: int = 0) -> str:
    return _create_token(user_id, "access", timedelta(minutes=settings.access_token_expire_minutes), version)


def create_refresh_token(user_id: str, version: int = 0) -> str:
    return _create_token(user_id, "refresh", timedelta(days=settings.refresh_token_expire_days), version)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(code: str) -> str:
    return bcrypt.hashpw(code.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("utf-8")


def verify_otp(code: str, code_hash: str) -> bool:
    return bcrypt.checkpw(code.encode("utf-8"), code_hash.encode("utf-8"))


def generate_invite_token() -> str:
    return secrets.token_urlsafe(32)
