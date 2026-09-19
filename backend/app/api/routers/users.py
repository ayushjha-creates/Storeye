"""Users API routes (OWNER-provisioned accounts).

Creating a user is provisioning: an OWNER creates an account with an email and
password inside their own store. There is no public self-registration endpoint —
Storeye is a local, per-store deployment.

Roles follow the canonical RBAC set (OWNER / MANAGER / STAFF). Legacy strings
such as ASSOCIATE / "Store Manager" are accepted and authorized via
app.core.auth aliases.
"""

from __future__ import annotations

from typing import Optional

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..authz import require_same_store, scoped_get
from ..deps import get_db, require_role
from ...core.auth import ROLE_OWNER, canonical_role, hash_password
from ...models import Store, User
from ...schemas import UserCreate, UserList, UserRead, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=UserList)
def list_users(
    store_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(ROLE_OWNER)),
):
    if store_id is not None:
        require_same_store(current_user, store_id)
    stmt = select(User).where(User.store_id == current_user.store_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(User.name)).all()
    return UserList(items=[UserRead.model_validate(i) for i in items], total=total)


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(ROLE_OWNER)),
):
    require_same_store(current_user, payload.store_id)
    if db.get(Store, payload.store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    email = (payload.email or "").strip().lower() or None
    if email is not None:
        exists = db.scalar(select(User).where(User.email == email))
        if exists is not None:
            raise HTTPException(
                status_code=409, detail="An account with this email already exists"
            )
    dump = payload.model_dump()
    dump.pop("password", None)
    user = User(**dump)
    user.email = email
    user.role = canonical_role(payload.role)
    if payload.password:
        user.password_hash = hash_password(payload.password)
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserRead.model_validate(user)


@router.get("/{user_id}", response_model=UserRead)
def get_user(
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(ROLE_OWNER)),
):
    return UserRead.model_validate(scoped_get(db, current_user, User, user_id))


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: UUID,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(ROLE_OWNER)),
):
    user = scoped_get(db, current_user, User, user_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "password":
            if value:
                user.password_hash = hash_password(value)
            continue
        if field == "email" and value is not None:
            email = value.strip().lower()
            existing = db.scalar(
                select(User).where(User.email == email, User.id != user.id)
            )
            if existing is not None:
                raise HTTPException(
                    status_code=409,
                    detail="An account with this email already exists",
                )
            setattr(user, field, email)
            continue
        if field == "role":
            setattr(user, field, canonical_role(value))
            continue
        setattr(user, field, value)
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserRead.model_validate(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(ROLE_OWNER)),
):
    user = scoped_get(db, current_user, User, user_id)
    db.delete(user)
    db.commit()