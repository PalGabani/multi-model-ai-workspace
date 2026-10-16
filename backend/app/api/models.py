from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import allowed_model_ids, user_workspace
from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import current_user
from app.models import (
    ModelConfiguration,
    ModelProvider,
    User,
    WorkspaceModelPermission,
)
from app.schemas import ModelResponse

router = APIRouter(prefix="/api/models", tags=["models"])
DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get("", response_model=list[ModelResponse])
async def list_models(
    user: Annotated[User, Depends(current_user)],
    db: DbSession,
) -> list[ModelResponse]:
    workspace = await user_workspace(db, user.id)
    records = (
        await db.scalars(select(ModelConfiguration).where(ModelConfiguration.is_enabled))
    ).all()
    permissions = list(
        (
            await db.scalars(
                select(WorkspaceModelPermission).where(
                    WorkspaceModelPermission.workspace_id == workspace.id
                )
            )
        ).all()
    )
    allowed_ids = (
        {permission.model_id for permission in permissions if permission.is_allowed}
        if workspace.model_permissions_restricted
        else None
    )
    response = []
    for model in records:
        provider = await db.get(ModelProvider, model.provider_id)
        api_key, base_url = settings.provider_credentials(model.provider_id)
        response.append(
            ModelResponse(
                id=model.id,
                provider_id=model.provider_id,
                label=model.label,
                description=model.description,
                input_cost_per_million=model.input_cost_per_million,
                output_cost_per_million=model.output_cost_per_million,
                context_window=model.context_window,
                enabled=(
                    model.is_enabled
                    and bool(provider and provider.is_enabled)
                    and (allowed_ids is None or model.id in allowed_ids)
                ),
                available=bool(provider and provider.is_enabled and api_key and base_url),
            )
        )
    return response


@router.post("/route")
async def route_model(
    task: str,
    user: Annotated[User, Depends(current_user)],
    db: DbSession,
    budget_per_million: Annotated[float | None, Query(ge=0)] = None,
) -> dict[str, object]:
    workspace = await user_workspace(db, user.id)
    permitted_ids = await allowed_model_ids(db, workspace)
    models = list(
        (await db.scalars(select(ModelConfiguration).where(ModelConfiguration.is_enabled))).all()
    )
    if permitted_ids is not None:
        models = [model for model in models if model.id in permitted_ids]
    if task.lower() in {"reasoning", "analysis", "coding"}:
        models.sort(key=lambda item: (-item.context_window, item.output_cost_per_million))
    else:
        models.sort(key=lambda item: item.input_cost_per_million + item.output_cost_per_million)
    selected = None
    for model in models:
        if (
            budget_per_million is not None
            and max(model.input_cost_per_million, model.output_cost_per_million)
            > budget_per_million
        ):
            continue
        provider = await db.get(ModelProvider, model.provider_id)
        if provider and provider.is_enabled:
            selected = model
            break
    if selected is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No enabled model meets that cost ceiling.")
    api_key, _ = settings.provider_credentials(selected.provider_id)
    return {"model_id": selected.id, "task": task, "available": bool(api_key)}
