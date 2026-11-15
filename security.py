"""Small local-session auth layer for this educational single-origin prototype."""
import base64, hashlib, hmac, secrets
from datetime import datetime, timedelta, timezone
from fastapi import Depends, Header, Cookie, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from .database import get_db
from .models import AuthSession, User

ITERATIONS = 420_000
ROLES = {"ADMINISTRATOR", "MEDICAL_OFFICER", "RESEARCHER", "ASTRONAUT"}

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"

def verify_password(password: str, encoded: str) -> bool:
    try:
        method, rounds, salt, expected = encoded.split("$")
        if method != "pbkdf2_sha256": return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.urlsafe_b64decode(salt), int(rounds))
        return hmac.compare_digest(actual, base64.urlsafe_b64decode(expected))
    except (ValueError, TypeError):
        return False

def new_session(db: Session, user: User) -> tuple[str, datetime]:
    raw = secrets.token_urlsafe(36)
    expires = datetime.now(timezone.utc) + timedelta(hours=10)
    db.add(AuthSession(user_id=user.id, token_hash=hashlib.sha256(raw.encode()).hexdigest(), expires_at=expires))
    return raw, expires

def current_user(authorization: str | None = Header(default=None), astra_session: str | None = Cookie(default=None), db: Session = Depends(get_db)) -> User:
    raw = astra_session
    if not raw and authorization and authorization.startswith("Bearer "):
        raw = authorization[7:].strip()
    if not raw:
        raise HTTPException(401, "Please sign in to continue.")
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))
    if not session:
        raise HTTPException(401, "Your session has ended. Please sign in again.")
    expiry = session.expires_at
    if expiry.tzinfo is None: expiry = expiry.replace(tzinfo=timezone.utc)
    if expiry <= datetime.now(timezone.utc):
        db.delete(session); db.commit()
        raise HTTPException(401, "Your session has expired. Please sign in again.")
    user = db.get(User, session.user_id)
    if not user or not user.active:
        raise HTTPException(401, "This account is inactive. Contact an administrator.")
    return user

def require_roles(*roles: str):
    def check(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "Your account does not have permission for this action.")
        return user
    return check
