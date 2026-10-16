from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import user_workspace
from app.core.database import get_db
from app.core.dependencies import current_user
from app.models import ModelConfiguration, UsageRecord, User

router = APIRouter(prefix="/api/usage", tags=["usage"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(current_user)]


@router.get("/summary")
async def usage_summary(db: DbSession, user: CurrentUser) -> dict[str, object]:
    workspace = await user_workspace(db, user.id)
    totals = (
        await db.execute(
            select(
                func.count(UsageRecord.id).label("requests"),
                func.coalesce(func.sum(UsageRecord.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(UsageRecord.output_tokens), 0).label("output_tokens"),
                func.coalesce(func.sum(UsageRecord.estimated_cost_usd), 0).label(
                    "estimated_cost_usd"
                ),
                func.coalesce(func.avg(UsageRecord.latency_ms), 0).label("average_latency_ms"),
                func.count(UsageRecord.id)
                .filter(UsageRecord.succeeded.is_(False))
                .label("failed_requests"),
            ).where(UsageRecord.workspace_id == workspace.id)
        )
    ).one()
    rows = (
        await db.execute(
            select(
                UsageRecord.model_id,
                ModelConfiguration.label,
                func.count(UsageRecord.id).label("requests"),
                func.sum(UsageRecord.input_tokens).label("input_tokens"),
                func.sum(UsageRecord.output_tokens).label("output_tokens"),
                func.sum(UsageRecord.estimated_cost_usd).label("estimated_cost_usd"),
                func.avg(UsageRecord.latency_ms).label("average_latency_ms"),
                func.count(UsageRecord.id)
                .filter(UsageRecord.succeeded.is_(False))
                .label("failed_requests"),
            )
            .join(ModelConfiguration, ModelConfiguration.id == UsageRecord.model_id)
            .where(UsageRecord.workspace_id == workspace.id)
            .group_by(UsageRecord.model_id, ModelConfiguration.label)
            .order_by(func.sum(UsageRecord.estimated_cost_usd).desc())
        )
    ).all()
    return {
        "requests": totals.requests,
        "input_tokens": totals.input_tokens,
        "output_tokens": totals.output_tokens,
        "estimated_cost_usd": float(totals.estimated_cost_usd),
        "average_latency_ms": round(float(totals.average_latency_ms)),
        "failed_requests": totals.failed_requests,
        "by_model": [
            {
                "model_id": row.model_id,
                "label": row.label,
                "requests": row.requests,
                "input_tokens": row.input_tokens,
                "output_tokens": row.output_tokens,
                "estimated_cost_usd": float(row.estimated_cost_usd or 0),
                "average_latency_ms": round(float(row.average_latency_ms or 0)),
                "failed_requests": row.failed_requests,
            }
            for row in rows
        ],
    }
