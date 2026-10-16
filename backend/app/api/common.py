from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    UsageRecord,
    Workspace,
    WorkspaceMembership,
    WorkspaceModelPermission,
)


async def user_workspace(db: AsyncSession, user_id: str) -> Workspace:
    membership = await db.scalar(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.user_id == user_id)
        .order_by(WorkspaceMembership.created_at)
    )
    if membership is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No workspace is available for this account."
        )
    workspace = await db.get(Workspace, membership.workspace_id)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace was not found.")
    return workspace


async def allowed_model_ids(db: AsyncSession, workspace: Workspace) -> set[str] | None:
    if not workspace.model_permissions_restricted:
        return None
    permissions = (
        await db.scalars(
            select(WorkspaceModelPermission).where(
                WorkspaceModelPermission.workspace_id == workspace.id
            )
        )
    ).all()
    return {permission.model_id for permission in permissions if permission.is_allowed}


async def enforce_spending_limit(db: AsyncSession, workspace: Workspace) -> None:
    if workspace.monthly_budget_usd is None:
        return
    month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    current_spend = await db.scalar(
        select(func.coalesce(func.sum(UsageRecord.estimated_cost_usd), 0)).where(
            UsageRecord.workspace_id == workspace.id,
            UsageRecord.created_at >= month_start,
            UsageRecord.succeeded.is_(True),
        )
    )
    if float(current_spend or 0) >= workspace.monthly_budget_usd:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "The workspace monthly spending limit has been reached.",
        )
