"""Admin dashboard + user-management (CMS) API.

Mounted at ``/api/admin`` and gated **only** on the ADMIN role (NOT on
``DEBUG_UI_ENABLED``), so the dashboard and CMS are available to admins whether
or not the debug arena is enabled. Mirrors the structure of
``internal/debug/router.py`` and reuses the app's ``require_admin`` dependency.
"""
from __future__ import annotations

from typing import Any, Callable, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from business_models import AuthSessionPayload, UserRole
from business_repositories import (
    ConcurrencyConflictError,
    LastAdminError,
    UserNotFoundError,
    admin_repository,
)


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdminUserAPI(StrictBaseModel):
    id: str
    kind: str
    role: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    status: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    last_seen_at: Optional[str] = None


class AdminUserListAPI(StrictBaseModel):
    items: List[AdminUserAPI]
    total: int
    limit: int
    offset: int


class AdminUserCreateAPI(StrictBaseModel):
    email: str
    password: str
    display_name: Optional[str] = None
    role: str = UserRole.USER.value
    status: str = "active"


class AdminUserUpdateAPI(StrictBaseModel):
    # expected_updated_at is the optimistic-concurrency token: the updated_at the
    # client last saw. The server rejects (409) if it no longer matches.
    expected_updated_at: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None
    display_name: Optional[str] = None


_VALID_ROLES = {r.value for r in UserRole}


def create_admin_router(require_admin: Callable[..., Any]) -> APIRouter:
    router = APIRouter(prefix="/api/admin", tags=["admin"])

    @router.get("/session")
    async def session_info(session: AuthSessionPayload = Depends(require_admin)):
        # Debug-independent admin identity probe for the dashboard bootstrap.
        return {
            "ok": True,
            "user": {
                "id": session.user.id,
                "email": session.user.email,
                "display_name": session.user.display_name,
                "role": session.user.role.value,
            },
        }

    @router.get("/stats")
    async def get_stats(_: AuthSessionPayload = Depends(require_admin)):
        return await admin_repository.get_stats()

    @router.get("/users", response_model=AdminUserListAPI)
    async def list_users(
        _: AuthSessionPayload = Depends(require_admin),
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        search: Optional[str] = Query(default=None),
        role: Optional[str] = Query(default=None),
        status: Optional[str] = Query(default=None),
        kind: Optional[str] = Query(default=None),
    ):
        items, total = await admin_repository.list_users(
            limit=limit, offset=offset, search=search, role=role, status=status, kind=kind
        )
        return AdminUserListAPI(
            items=[AdminUserAPI(**item) for item in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    @router.post("/users", response_model=AdminUserAPI, status_code=201)
    async def create_user(
        payload: AdminUserCreateAPI,
        _: AuthSessionPayload = Depends(require_admin),
    ):
        try:
            created = await admin_repository.create_user(
                email=payload.email,
                password=payload.password,
                display_name=payload.display_name,
                role=payload.role,
                status=payload.status,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return AdminUserAPI(**created)

    @router.patch("/users/{user_id}", response_model=AdminUserAPI)
    async def update_user(
        user_id: str,
        payload: AdminUserUpdateAPI,
        session: AuthSessionPayload = Depends(require_admin),
    ):
        provided = payload.model_fields_set
        new_role = payload.role if ("role" in provided and payload.role is not None) else None
        new_status = payload.status if ("status" in provided and payload.status is not None) else None

        if new_role is not None and new_role not in _VALID_ROLES:
            raise HTTPException(status_code=400, detail="invalid role")
        if new_status is not None and new_status not in admin_repository.ALLOWED_STATUSES:
            raise HTTPException(status_code=400, detail="invalid status")

        # Permission guards (server is authoritative; the UI mirrors these).
        if user_id == session.user.id:
            if new_role is not None and new_role != UserRole.ADMIN.value:
                raise HTTPException(status_code=400, detail="You cannot change your own admin role")
            if new_status is not None and new_status != "active":
                raise HTTPException(status_code=400, detail="You cannot deactivate your own account")

        if new_role is not None or new_status is not None:
            target = await admin_repository.get_user(user_id)
            if target is None:
                raise HTTPException(status_code=404, detail="user not found")
            removes_admin = (
                target["role"] == UserRole.ADMIN.value
                and target["status"] == "active"
                and (
                    (new_role is not None and new_role != UserRole.ADMIN.value)
                    or (new_status is not None and new_status != "active")
                )
            )
            if removes_admin and await admin_repository.count_active_admins(exclude_user_id=user_id) == 0:
                raise HTTPException(status_code=400, detail="Cannot remove the last active admin")

        try:
            updated = await admin_repository.update_user(
                user_id=user_id,
                expected_updated_at=payload.expected_updated_at,
                role=new_role,
                status=new_status,
                display_name=payload.display_name if "display_name" in provided else None,
                display_name_provided="display_name" in provided,
            )
        except UserNotFoundError:
            raise HTTPException(status_code=404, detail="user not found")
        except ConcurrencyConflictError:
            raise HTTPException(
                status_code=409,
                detail="This user was modified elsewhere. Reload and try again.",
            )
        except LastAdminError:
            raise HTTPException(status_code=400, detail="Cannot remove the last active admin")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return AdminUserAPI(**updated)

    @router.delete("/users/{user_id}", response_model=AdminUserAPI)
    async def delete_user(
        user_id: str,
        session: AuthSessionPayload = Depends(require_admin),
    ):
        if user_id == session.user.id:
            raise HTTPException(status_code=400, detail="You cannot delete your own account")
        target = await admin_repository.get_user(user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="user not found")
        if (
            target["role"] == UserRole.ADMIN.value
            and target["status"] == "active"
            and await admin_repository.count_active_admins(exclude_user_id=user_id) == 0
        ):
            raise HTTPException(status_code=400, detail="Cannot remove the last active admin")
        try:
            deleted = await admin_repository.soft_delete_user(user_id=user_id)
        except UserNotFoundError:
            raise HTTPException(status_code=404, detail="user not found")
        except LastAdminError:
            raise HTTPException(status_code=400, detail="Cannot remove the last active admin")
        return AdminUserAPI(**deleted)

    return router
