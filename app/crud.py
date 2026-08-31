"""Generic org-scoped CRUD router factory.

Per SRS Section 2.2 (Multi-Tenant Data Isolation): every query MUST filter
by organisation at the application layer. system_admin is the only role
that sees across organisations. This mirrors the Django backend's
OrgScopedQuerysetMixin, but as a router factory instead of a viewset mixin.
"""
from typing import Any, Callable, Optional, Type
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.models import User
from app.database import get_db
from app.deps import get_current_user


def org_scoped_crud_router(
    *,
    model: Type[Any],
    out_schema: Type[BaseModel],
    create_schema: Optional[Type[BaseModel]] = None,
    update_schema: Optional[Type[BaseModel]] = None,
    prefix: str,
    tags: list[str],
    org_field: str = "organisation_id",
    id_type: type = UUID,
    on_create: Optional[Callable[[dict, User], dict]] = None,
    allow_update: bool = True,
    allow_delete: bool = True,
) -> APIRouter:
    """Builds list/create/retrieve[/update][/delete] endpoints for `model`,
    scoped to the caller's organisation.

    on_create(data, user) -> data: hook to inject/override fields at create
    time (e.g. setting operator=user, or a generated business id) beyond the
    default of stamping `org_field` with the user's organisation.
    """
    router = APIRouter(prefix=prefix, tags=tags)

    def _scope(query, user: User):
        if user.role == "system_admin":
            return query
        return query.where(getattr(model, org_field) == user.organisation_id)

    @router.get("/", response_model=list[out_schema])
    async def list_items(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
        result = await db.execute(_scope(select(model), user))
        return result.scalars().all()

    @router.get("/{item_id}", response_model=out_schema)
    async def get_item(item_id: id_type, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
        obj = (await db.execute(_scope(select(model).where(model.id == item_id), user))).scalar_one_or_none()
        if obj is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
        return obj

    if create_schema is not None:

        @router.post("/", response_model=out_schema, status_code=status.HTTP_201_CREATED)
        async def create_item(
            payload: create_schema,  # type: ignore[valid-type]
            db: AsyncSession = Depends(get_db),
            user: User = Depends(get_current_user),
        ):
            data = payload.model_dump()
            data.setdefault(org_field, user.organisation_id)
            if on_create is not None:
                data = on_create(data, user)
            obj = model(**data)
            db.add(obj)
            await db.commit()
            await db.refresh(obj)
            return obj

    if update_schema is not None and allow_update:

        @router.patch("/{item_id}", response_model=out_schema)
        async def update_item(
            item_id: id_type,
            payload: update_schema,  # type: ignore[valid-type]
            db: AsyncSession = Depends(get_db),
            user: User = Depends(get_current_user),
        ):
            obj = (await db.execute(_scope(select(model).where(model.id == item_id), user))).scalar_one_or_none()
            if obj is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
            for field, value in payload.model_dump(exclude_unset=True).items():
                setattr(obj, field, value)
            await db.commit()
            await db.refresh(obj)
            return obj

    if allow_delete:

        @router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
        async def delete_item(
            item_id: id_type, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
        ):
            obj = (await db.execute(_scope(select(model).where(model.id == item_id), user))).scalar_one_or_none()
            if obj is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
            await db.delete(obj)
            await db.commit()

    return router
