import asyncio
import json
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import allowed_model_ids, enforce_spending_limit, user_workspace
from app.core.config import ModelDefinition
from app.core.database import SessionFactory, get_db
from app.core.dependencies import current_user
from app.models import (
    Conversation,
    Feedback,
    Message,
    ModelConfiguration,
    UsageRecord,
    User,
)
from app.providers.openai_compatible import ProviderError
from app.providers.router import model_router
from app.schemas import (
    ConversationCreate,
    ConversationRename,
    ConversationResponse,
    FeedbackCreate,
    MessageCreate,
    MessageResponse,
)

router = APIRouter(prefix="/api", tags=["conversations"])
DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(current_user)]


def sse(event: dict[str, object]) -> str:
    return f"data: {json.dumps(event, separators=(',', ':'))}\n\n"


async def owned_conversation(db: AsyncSession, conversation_id: str, user: User) -> Conversation:
    workspace = await user_workspace(db, user.id)
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.workspace_id == workspace.id,
            Conversation.user_id == user.id,
        )
    )
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation was not found.")
    return conversation


async def stored_model(db: AsyncSession, model_id: str) -> ModelConfiguration:
    model = await db.scalar(
        select(ModelConfiguration).where(
            ModelConfiguration.id == model_id,
            ModelConfiguration.is_enabled.is_(True),
        )
    )
    if model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That model is unavailable.")
    return model


def model_definition(model: ModelConfiguration) -> ModelDefinition:
    return ModelDefinition(
        id=model.id,
        provider=model.provider_id,
        label=model.label,
        description=model.description,
        input_cost_per_million=model.input_cost_per_million,
        output_cost_per_million=model.output_cost_per_million,
        context_window=model.context_window,
    )


async def provider_history(
    db: AsyncSession, conversation_id: str, user_content: str
) -> list[dict[str, str]]:
    previous = (
        await db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.status == "complete")
            .order_by(Message.created_at.desc())
            .limit(30)
        )
    ).all()
    history = [{"role": item.role, "content": item.content} for item in reversed(previous)]
    history.append({"role": "user", "content": user_content})
    return history


async def save_usage(
    *,
    workspace_id: str,
    user_id: str,
    conversation_id: str,
    model_id: str,
    message_id: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    cost: float,
    succeeded: bool,
) -> None:
    async with SessionFactory() as session:
        session.add(
            UsageRecord(
                workspace_id=workspace_id,
                user_id=user_id,
                conversation_id=conversation_id,
                message_id=message_id,
                model_id=model_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                estimated_cost_usd=cost,
                succeeded=succeeded,
            )
        )
        await session.commit()


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(db: DbSession, user: CurrentUser) -> list[Conversation]:
    workspace = await user_workspace(db, user.id)
    return list(
        (
            await db.scalars(
                select(Conversation)
                .where(Conversation.workspace_id == workspace.id, Conversation.user_id == user.id)
                .order_by(Conversation.updated_at.desc())
                .limit(200)
            )
        ).all()
    )


@router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    payload: ConversationCreate, db: DbSession, user: CurrentUser
) -> Conversation:
    workspace = await user_workspace(db, user.id)
    conversation = Conversation(
        workspace_id=workspace.id,
        user_id=user.id,
        title=payload.title.strip(),
        mode=payload.mode,
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
async def list_messages(conversation_id: str, db: DbSession, user: CurrentUser) -> list[Message]:
    conversation = await owned_conversation(db, conversation_id, user)
    return list(
        (
            await db.scalars(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.created_at)
            )
        ).all()
    )


@router.patch("/conversations/{conversation_id}", response_model=ConversationResponse)
async def rename_conversation(
    conversation_id: str, payload: ConversationRename, db: DbSession, user: CurrentUser
) -> Conversation:
    conversation = await owned_conversation(db, conversation_id, user)
    conversation.title = payload.title.strip()
    conversation.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(conversation)
    return conversation


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conversation_id: str, db: DbSession, user: CurrentUser) -> Response:
    conversation = await owned_conversation(db, conversation_id, user)
    await db.delete(conversation)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/conversations/{conversation_id}/export")
async def export_conversation(
    conversation_id: str, db: DbSession, user: CurrentUser
) -> dict[str, object]:
    conversation = await owned_conversation(db, conversation_id, user)
    messages = await list_messages(conversation_id, db, user)
    return {
        "title": conversation.title,
        "created_at": conversation.created_at.isoformat(),
        "messages": [
            MessageResponse.model_validate(message).model_dump(mode="json") for message in messages
        ],
    }


async def complete_model_response(
    *,
    definition: ModelDefinition,
    history: list[dict[str, str]],
    workspace_id: str,
    user_id: str,
    conversation_id: str,
) -> AsyncIterator[str]:
    message_id = None
    output: list[str] = []
    input_tokens = output_tokens = 0
    started = time.perf_counter()
    async with SessionFactory() as db:
        assistant = Message(
            conversation_id=conversation_id,
            role="assistant",
            content="",
            model_id=definition.id,
            status="streaming",
        )
        db.add(assistant)
        await db.commit()
        await db.refresh(assistant)
        message_id = assistant.id
    yield sse({"type": "start", "model_id": definition.id, "message_id": message_id})
    try:
        async for event in model_router.stream(definition, history):
            if event.text:
                output.append(event.text)
                yield sse(
                    {
                        "type": "token",
                        "model_id": definition.id,
                        "message_id": message_id,
                        "text": event.text,
                    }
                )
            input_tokens = event.input_tokens or input_tokens
            output_tokens = event.output_tokens or output_tokens
        text = "".join(output)
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        cost = (
            input_tokens * definition.input_cost_per_million
            + output_tokens * definition.output_cost_per_million
        ) / 1_000_000
        async with SessionFactory() as db:
            assistant = await db.get(Message, message_id)
            if assistant is None:
                raise RuntimeError("The streamed response record was lost.")
            assistant.content = text
            assistant.input_tokens = input_tokens
            assistant.output_tokens = output_tokens
            assistant.latency_ms = elapsed_ms
            assistant.estimated_cost_usd = cost
            assistant.status = "complete"
            await db.commit()
        await save_usage(
            workspace_id=workspace_id,
            user_id=user_id,
            conversation_id=conversation_id,
            model_id=definition.id,
            message_id=message_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=elapsed_ms,
            cost=cost,
            succeeded=True,
        )
        yield sse(
            {
                "type": "complete",
                "model_id": definition.id,
                "message_id": message_id,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "latency_ms": elapsed_ms,
                "estimated_cost_usd": cost,
            }
        )
    except asyncio.CancelledError:
        async with SessionFactory() as db:
            assistant = await db.get(Message, message_id)
            if assistant:
                assistant.content = "".join(output)
                assistant.status = "stopped"
                await db.commit()
        raise
    except (ProviderError, ValueError) as error:
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        async with SessionFactory() as db:
            assistant = await db.get(Message, message_id)
            if assistant:
                assistant.content = "".join(output)
                assistant.status = "failed"
                assistant.latency_ms = elapsed_ms
                await db.commit()
        await save_usage(
            workspace_id=workspace_id,
            user_id=user_id,
            conversation_id=conversation_id,
            model_id=definition.id,
            message_id=message_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=elapsed_ms,
            cost=0,
            succeeded=False,
        )
        yield sse({"type": "error", "model_id": definition.id, "message": str(error)})


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    payload: MessageCreate,
    db: DbSession,
    user: CurrentUser,
) -> StreamingResponse:
    conversation = await owned_conversation(db, conversation_id, user)
    workspace = await user_workspace(db, user.id)
    await enforce_spending_limit(db, workspace)
    model = await stored_model(db, payload.model_id)
    allowed = await allowed_model_ids(db, workspace)
    if allowed is not None and model.id not in allowed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "This model is not enabled for your workspace."
        )
    history = await provider_history(db, conversation_id, payload.content)
    user_message = Message(
        conversation_id=conversation_id, role="user", content=payload.content.strip()
    )
    db.add(user_message)
    if conversation.title == "New conversation":
        conversation.title = payload.content.strip()[:70]
    conversation.updated_at = datetime.now(UTC)
    await db.commit()

    async def events() -> AsyncIterator[str]:
        try:
            candidates = model_router.candidates(model.id, payload.auto_route, allowed)
        except ValueError as error:
            yield sse({"type": "error", "message": str(error)})
            return
        for index, candidate in enumerate(candidates):
            if index:
                yield sse(
                    {
                        "type": "retry",
                        "model_id": candidate.id,
                        "message": "Trying a fallback model.",
                    }
                )
            had_error = False
            async for chunk in complete_model_response(
                definition=candidate,
                history=history,
                workspace_id=workspace.id,
                user_id=user.id,
                conversation_id=conversation_id,
            ):
                event = json.loads(chunk[6:].strip())
                had_error = had_error or event.get("type") == "error"
                yield chunk
            if not had_error:
                return

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


class CompareRequest(BaseModel):
    content: str = Field(min_length=1, max_length=50_000)
    model_ids: list[str]


@router.post("/conversations/{conversation_id}/compare")
async def compare_models(
    conversation_id: str,
    payload: CompareRequest,
    db: DbSession,
    user: CurrentUser,
) -> StreamingResponse:
    if not 2 <= len(payload.model_ids) <= 4 or len(set(payload.model_ids)) != len(
        payload.model_ids
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose between two and four different models."
        )
    conversation = await owned_conversation(db, conversation_id, user)
    workspace = await user_workspace(db, user.id)
    await enforce_spending_limit(db, workspace)
    models = [await stored_model(db, model_id) for model_id in payload.model_ids]
    allowed = await allowed_model_ids(db, workspace)
    if allowed is not None and any(model.id not in allowed for model in models):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "A selected model is not enabled for this workspace."
        )
    history = await provider_history(db, conversation_id, payload.content)
    db.add(Message(conversation_id=conversation_id, role="user", content=payload.content.strip()))
    conversation.title = (
        payload.content.strip()[:70]
        if conversation.title == "New conversation"
        else conversation.title
    )
    conversation.mode = "compare"
    conversation.updated_at = datetime.now(UTC)
    await db.commit()

    async def events() -> AsyncIterator[str]:
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        async def run_model(model: ModelConfiguration) -> None:
            try:
                async for event in complete_model_response(
                    definition=model_definition(model),
                    history=history,
                    workspace_id=workspace.id,
                    user_id=user.id,
                    conversation_id=conversation_id,
                ):
                    await queue.put(event)
            except Exception:
                await queue.put(
                    sse(
                        {
                            "type": "error",
                            "model_id": model.id,
                            "message": "Response could not be completed.",
                        }
                    )
                )
            finally:
                await queue.put(None)

        tasks = [asyncio.create_task(run_model(model)) for model in models]
        finished = 0
        try:
            while finished < len(tasks):
                event = await queue.get()
                if event is None:
                    finished += 1
                else:
                    yield event
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.post("/messages/{message_id}/feedback", status_code=status.HTTP_201_CREATED)
async def create_feedback(
    message_id: str,
    payload: FeedbackCreate,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, str]:
    message = await db.get(Message, message_id)
    if message is None or message.role != "assistant":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assistant response was not found.")
    conversation = await owned_conversation(db, message.conversation_id, user)
    existing = await db.scalar(
        select(Feedback).where(Feedback.message_id == message.id, Feedback.user_id == user.id)
    )
    if existing:
        existing.rating = payload.rating
        existing.comment = payload.comment
        await db.commit()
        return {"status": "updated"}
    db.add(
        Feedback(
            message_id=message.id, user_id=user.id, rating=payload.rating, comment=payload.comment
        )
    )
    await db.commit()
    return {"status": "created", "conversation_id": conversation.id}
