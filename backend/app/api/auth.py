from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.models import (
    ModelConfiguration,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceModelPermission,
)
from app.schemas import TokenResponse, UserCreate, UserLogin, UserResponse, WorkspacePreferences

router = APIRouter(prefix="/api/auth", tags=["authentication"])
DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, db: DbSession) -> TokenResponse:
    user = User(
        email=str(payload.email).lower(),
        display_name=payload.display_name.strip(),
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    try:
        await db.flush()
        workspace = Workspace(name=payload.workspace_name.strip(), created_by=user.id)
        db.add(workspace)
        await db.flush()
        db.add(WorkspaceMembership(workspace_id=workspace.id, user_id=user.id, role="owner"))
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "An account with this email already exists."
        ) from error
    return TokenResponse(
        access_token=create_access_token(user.id),
        user=UserResponse.model_validate(user),
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: UserLogin, db: DbSession) -> TokenResponse:
    user = await db.scalar(select(User).where(User.email == str(payload.email).lower()))
    if (
        user is None
        or not user.is_active
        or not verify_password(payload.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email or password is incorrect.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenResponse(
        access_token=create_access_token(user.id), user=UserResponse.model_validate(user)
    )


@router.get("/me", response_model=UserResponse)
async def me(user: Annotated[User, Depends(current_user)]) -> User:
    return user


@router.patch("/me", response_model=UserResponse)
async def update_profile(
    display_name: str,
    user: Annotated[User, Depends(current_user)],
    db: DbSession,
) -> User:
    normalized = display_name.strip()
    if not normalized or len(normalized) > 100:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Name must be between 1 and 100 characters."
        )
    user.display_name = normalized
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/workspace")
async def workspace(
    user: Annotated[User, Depends(current_user)],
    db: DbSession,
) -> dict[str, object]:
    membership = await db.scalar(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.user_id == user.id)
        .order_by(WorkspaceMembership.created_at)
    )
    if membership is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No workspace is available for this account."
        )
    workspace = await db.get(Workspace, membership.workspace_id)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace was not found.")
    permissions = list(
        (
            await db.scalars(
                select(WorkspaceModelPermission).where(
                    WorkspaceModelPermission.workspace_id == workspace.id
                )
            )
        ).all()
    )
    return {
        "id": workspace.id,
        "name": workspace.name,
        "role": membership.role,
        "default_model_id": workspace.default_model_id,
        "monthly_budget_usd": workspace.monthly_budget_usd,
        "allowed_model_ids": (
            [permission.model_id for permission in permissions if permission.is_allowed]
            if workspace.model_permissions_restricted
            else None
        ),
    }


@router.patch("/workspace")
async def update_workspace(
    payload: WorkspacePreferences,
    user: Annotated[User, Depends(current_user)],
    db: DbSession,
) -> dict[str, object]:
    membership = await db.scalar(
        select(WorkspaceMembership).where(WorkspaceMembership.user_id == user.id)
    )
    if membership is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No workspace is available for this account."
        )
    if membership.role not in {"owner", "admin"}:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Workspace administrator access is required."
        )
    workspace = await db.get(Workspace, membership.workspace_id)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace was not found.")
    if payload.default_model_id is not None:
        model = await db.get(ModelConfiguration, payload.default_model_id)
        if model is None or not model.is_enabled:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Default model is unavailable.")
        workspace.default_model_id = model.id
    if "monthly_budget_usd" in payload.model_fields_set:
        workspace.monthly_budget_usd = payload.monthly_budget_usd
    if "allowed_model_ids" in payload.model_fields_set and payload.allowed_model_ids is not None:
        workspace.model_permissions_restricted = True
        models = list(
            (
                await db.scalars(
                    select(ModelConfiguration).where(
                        ModelConfiguration.id.in_(set(payload.allowed_model_ids)),
                        ModelConfiguration.is_enabled.is_(True),
                    )
                )
            ).all()
        )
        if {model.id for model in models} != set(payload.allowed_model_ids):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "One or more model IDs are unavailable."
            )
        existing = list(
            (
                await db.scalars(
                    select(WorkspaceModelPermission).where(
                        WorkspaceModelPermission.workspace_id == workspace.id
                    )
                )
            ).all()
        )
        existing_by_id = {permission.model_id: permission for permission in existing}
        for model in models:
            permission = existing_by_id.get(model.id)
            if permission:
                permission.is_allowed = True
            else:
                db.add(
                    WorkspaceModelPermission(
                        workspace_id=workspace.id,
                        model_id=model.id,
                        is_allowed=True,
                    )
                )
        for permission in existing:
            if permission.model_id not in payload.allowed_model_ids:
                permission.is_allowed = False
    elif "allowed_model_ids" in payload.model_fields_set:
        workspace.model_permissions_restricted = False
        existing = list(
            (
                await db.scalars(
                    select(WorkspaceModelPermission).where(
                        WorkspaceModelPermission.workspace_id == workspace.id
                    )
                )
            ).all()
        )
        for permission in existing:
            await db.delete(permission)
    if (
        workspace.model_permissions_restricted
        and workspace.default_model_id
        and payload.allowed_model_ids is not None
        and workspace.default_model_id not in payload.allowed_model_ids
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "The default model must be workspace-enabled."
        )
    await db.commit()
    permissions = list(
        (
            await db.scalars(
                select(WorkspaceModelPermission).where(
                    WorkspaceModelPermission.workspace_id == workspace.id
                )
            )
        ).all()
    )
    return {
        "id": workspace.id,
        "name": workspace.name,
        "role": membership.role,
        "default_model_id": workspace.default_model_id,
        "monthly_budget_usd": workspace.monthly_budget_usd,
        "allowed_model_ids": (
            [permission.model_id for permission in permissions if permission.is_allowed]
            if workspace.model_permissions_restricted
            else None
        ),
    }
