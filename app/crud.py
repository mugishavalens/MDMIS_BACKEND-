"""Generic org-scoped CRUD router factory.

Per SRS Section 2.2 (Multi-Tenant Data Isolation): every query MUST filter
by organisation at the application layer. system_admin is the only role
that sees across organisations. This mirrors the Django backend's
OrgScopedQuerysetMixin, but as a router factory instead of a viewset mixin.
"""
from typing import Any, Awaitable, Callable, Optional, Type
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.models import User
from app.authz import check_role, get_owned
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
    write_roles: tuple[str, ...] = (),
    delete_roles: tuple[str, ...] = ("org_admin",),
    parents: Optional[dict[str, tuple[Type[Any], str]]] = None,
    check: Optional[Callable[[dict, User], Awaitable[None] | None]] = None,
) -> APIRouter:
    """Builds list/create/retrieve[/update][/delete] endpoints for `model`,
    scoped to the caller's organisation.

    on_create(data, user) -> data: hook to inject/override fields at create
    time (e.g. setting operator=user, or a generated business id) beyond the
    default of stamping `org_field` with the user's organisation.

    write_roles / delete_roles: who may create+update / delete (system_admin
    always may; see app.authz). Reading is open to every role in the org.
    parents: {field: (Model, label)} for foreign keys in the create payload;
    each must point at a row the caller's organisation owns, and the new
    row takes that parent's organisation (so a system_admin's writes land
    in the right org). check(data, user): extra rules on create/update
    data (e.g. who may set a status); raise HTTPException to refuse.
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
            check_role(user, write_roles, f"create {tags[0]}")
            data = payload.model_dump()
            data[org_field] = user.organisation_id
            for field, (parent_model, label) in (parents or {}).items():
                parent = await get_owned(db, parent_model, data.get(field), user, label)
                data[org_field] = parent.organisation_id
            if check is not None:
                await _maybe_await(check(data, user))
            if on_create is not None:
                data = on_create(data, user)
            obj = model(**data)
            db.add(obj)
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                raise HTTPException(status.HTTP_409_CONFLICT, "That ID is already in use.")
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
            check_role(user, write_roles, f"edit {tags[0]}")
            obj = (await db.execute(_scope(select(model).where(model.id == item_id), user))).scalar_one_or_none()
            if obj is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
            updates = payload.model_dump(exclude_unset=True)
            if check is not None:
                await _maybe_await(check(updates, user))
            for field, value in updates.items():
                setattr(obj, field, value)
            await db.commit()
            await db.refresh(obj)
            return obj

    if allow_delete:

        @router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
        async def delete_item(
            item_id: id_type, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
        ):
            check_role(user, delete_roles, f"delete {tags[0]}")
            obj = (await db.execute(_scope(select(model).where(model.id == item_id), user))).scalar_one_or_none()
            if obj is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
            await db.delete(obj)
            await db.commit()

    return router


async def _maybe_await(result) -> None:
    if result is not None and hasattr(result, "__await__"):
        await result
