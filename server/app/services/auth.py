from sqlalchemy import select

from server.app.services.db import get_session
from server.app.services.db_models import User


def _get_or_create_user(telegram_id: int, username: str | None = None) -> User:
    """Fetch an existing user by Telegram ID or create a new one.

    This helper is used by role/authorization operations.
    """
    with get_session() as session:
        user = (
            session.execute(
                select(User).where(User.telegram_id == telegram_id)
            ).scalar_one_or_none()
        )
        if user is None:
            user = User(telegram_id=telegram_id, username=username, role="user")
            session.add(user)
        else:
            if username and user.username != username:
                user.username = username
        session.commit()
        session.refresh(user)
        return user


def get_user_role(telegram_id: int) -> str | None:
    """Return the role of a user by Telegram ID, or None if not found."""
    with get_session() as session:
        user = (
            session.execute(
                select(User).where(User.telegram_id == telegram_id)
            ).scalar_one_or_none()
        )
        return user.role if user else None


def set_user_role(telegram_id: int, role: str, username: str | None = None) -> None:
    """Set the role (and optionally username) for a Telegram user."""
    with get_session() as session:
        user = (
            session.execute(
                select(User).where(User.telegram_id == telegram_id)
            ).scalar_one_or_none()
        )
        if user is None:
            user = User(telegram_id=telegram_id, username=username, role=role)
            session.add(user)
        else:
            user.role = role
            if username:
                user.username = username
        session.commit()


def is_owner(telegram_id: int) -> bool:
    """Checks if a user is the owner."""
    return get_user_role(telegram_id) == "owner"


def is_admin(telegram_id: int) -> bool:
    """Checks if a user is an admin."""
    return get_user_role(telegram_id) == "admin"


def is_authorized(telegram_id: int) -> bool:
    """Checks if a user is authorized (owner, admin, or user)."""
    role = get_user_role(telegram_id)
    return role in ["owner", "admin", "user"]


def grant_access(telegram_id: int, username: str | None = None) -> None:
    """Grant standard user access to a Telegram user."""
    set_user_role(telegram_id, "user", username)


def revoke_access(telegram_id: int) -> None:
    """Revoke access from a user by deleting their record."""
    with get_session() as session:
        user = (
            session.execute(
                select(User).where(User.telegram_id == telegram_id)
            ).scalar_one_or_none()
        )
        if user is not None:
            session.delete(user)
            session.commit()
