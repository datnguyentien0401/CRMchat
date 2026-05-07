from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlmodel import Session

from app.deps import get_db
from app.models import Role, User


def seed_users(session: Session) -> None:
    existing = session.get(User, "booker-1")
    if existing:
        return
    session.add_all(
        [
            User(id="system", role=Role.manager, team_id="system"),
            User(id="booker-1", role=Role.booker, team_id="team-a"),
            User(id="booker-2", role=Role.booker, team_id="team-a"),
            User(id="manager-1", role=Role.manager, team_id="team-a"),
            User(id="manager-2", role=Role.manager, team_id="team-b"),
        ]
    )
    session.commit()


def get_current_user(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    session: Session = Depends(get_db),
) -> User:
    if not x_user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-User-Id")
    user = session.get(User, x_user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user")
    return user

