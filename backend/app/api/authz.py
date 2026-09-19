"""Authorization helpers: store isolation + scoped object access.

Every business router enforces store scoping through these helpers:

    require_same_store(user, store_id)   -> 403 when the requested store_id is
                                            not the authenticated user's store
    scoped_get(db, user, Model, id)      -> 404 for missing OR other-store rows
    effective_store_id(user, store_id)   -> defaults an omitted store_id to the
                                            authenticated user's store

The authenticated user's `store_id` is the ONLY source of truth for which
store a request may touch. Client-supplied store_id in URLs, query parameters
or bodies is validated against it, never trusted on its own.
"""

from __future__ import annotations

from typing import Optional, Type, TypeVar
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models import User

_STORED = TypeVar("_STORED", bound="object")

_UNAUTH = (status.HTTP_403_FORBIDDEN, "Not authorized for this store")


def require_same_store(user: User, store_id: UUID) -> None:
    """Reject a request whose store_id does not match the user's store."""
    if store_id is None or user.store_id != store_id:
        raise HTTPException(status_code=_UNAUTH[0], detail=_UNAUTH[1])


def effective_store_id(user: User, store_id: Optional[UUID]) -> UUID:
    """Return the store_id that governs a request, defaulting to user.store_id.

    Used by list endpoints: when the client omits `store_id` we scope the query
    to the user's own store instead of returning every store's data.
    """
    if store_id is None:
        return user.store_id
    require_same_store(user, store_id)
    return user.store_id


def scoped_get(db: Session, user: User, model: Type[_STORED], obj_id) -> _STORED:
    """Fetch `model` by id, guaranteeing the row belongs to the user's store.

    Missing rows and other-store rows are indistinguishable (404) so a caller
    cannot probe for objects that exist in another store.
    """
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Not found")
    # Store rows are their own scope (their primary key IS the store id);
    # every other scoped model carries an explicit `store_id` foreign key.
    owner_store_id = getattr(obj, "store_id", None)
    if owner_store_id is None:
        owner_store_id = getattr(obj, "id", None)
    if owner_store_id != user.store_id:
        raise HTTPException(status_code=404, detail="Not found")
    return obj