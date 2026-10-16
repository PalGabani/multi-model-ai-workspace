import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.database import SessionFactory
from app.main import app
from app.models import User, Workspace

pytestmark = pytest.mark.integration


def test_auth_conversations_model_permissions_and_failure_usage() -> None:
    suffix = uuid4().hex
    client = TestClient(app)
    user_ids: list[str] = []
    workspace_ids: list[str] = []

    try:
        with client:
            accounts = []
            for label in ("first", "second"):
                response = client.post(
                    "/api/auth/register",
                    json={
                        "email": f"{label}-{suffix}@example.com",
                        "password": "a sufficiently strong password",
                        "display_name": label.title(),
                        "workspace_name": f"{label.title()} test workspace",
                    },
                )
                assert response.status_code == 201, response.text
                account = response.json()
                user_ids.append(account["user"]["id"])
                accounts.append(account)
                authorization = {"Authorization": f"Bearer {account['access_token']}"}
                workspace = client.get("/api/auth/workspace", headers=authorization)
                assert workspace.status_code == 200
                workspace_ids.append(workspace.json()["id"])

            owner, other = accounts
            owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
            other_headers = {"Authorization": f"Bearer {other['access_token']}"}

            created = client.post(
                "/api/conversations",
                headers=owner_headers,
                json={"title": "Tenant-only thread", "mode": "chat"},
            )
            assert created.status_code == 201
            conversation_id = created.json()["id"]

            denied_history = client.get(
                f"/api/conversations/{conversation_id}/messages", headers=other_headers
            )
            assert denied_history.status_code == 404

            restricted = client.patch(
                "/api/auth/workspace",
                headers=owner_headers,
                json={"allowed_model_ids": []},
            )
            assert restricted.status_code == 200, restricted.text
            model_listing = client.get("/api/models", headers=owner_headers)
            assert model_listing.status_code == 200
            assert all(not model["enabled"] for model in model_listing.json())
            denied_route = client.post("/api/models/route?task=coding", headers=owner_headers)
            assert denied_route.status_code == 404

            reenabled = client.patch(
                "/api/auth/workspace",
                headers=owner_headers,
                json={"allowed_model_ids": ["gpt-4o-mini"]},
            )
            assert reenabled.status_code == 200, reenabled.text
            routed = client.post(
                "/api/models/route?task=coding&budget_per_million=1",
                headers=owner_headers,
            )
            assert routed.status_code == 200
            assert routed.json()["model_id"] == "gpt-4o-mini"

            failed_generation = client.post(
                f"/api/conversations/{conversation_id}/messages",
                headers=owner_headers,
                json={
                    "content": "This should fail without a provider key.",
                    "model_id": "gpt-4o-mini",
                    "auto_route": False,
                },
            )
            assert failed_generation.status_code == 200
            assert '"type":"error"' in failed_generation.text
            assert "not configured" in failed_generation.text

            usage = client.get("/api/usage/summary", headers=owner_headers)
            assert usage.status_code == 200
            assert usage.json()["requests"] == 1
            assert usage.json()["failed_requests"] == 1

    finally:

        async def cleanup() -> None:
            async with SessionFactory() as session:
                if workspace_ids:
                    await session.execute(delete(Workspace).where(Workspace.id.in_(workspace_ids)))
                if user_ids:
                    users = (await session.scalars(select(User).where(User.id.in_(user_ids)))).all()
                    for user in users:
                        await session.delete(user)
                await session.commit()

        asyncio.run(cleanup())
