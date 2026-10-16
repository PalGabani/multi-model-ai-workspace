import jwt

from app.core.config import ModelDefinition, Settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.providers.router import ModelRouter


def test_password_hashes_verify_and_mismatch_fails() -> None:
    encoded = hash_password("a strong test password")

    assert encoded != "a strong test password"
    assert verify_password("a strong test password", encoded)
    assert not verify_password("another password", encoded)


def test_access_tokens_identify_user_and_expire() -> None:
    token = create_access_token("user-123")

    assert decode_access_token(token)["sub"] == "user-123"
    try:
        jwt.decode(token, "wrong-secret-key-that-is-at-least-32-bytes-long", algorithms=["HS256"])
    except jwt.InvalidTokenError:
        pass
    else:
        raise AssertionError("Tokens signed with a different secret must be rejected.")


def test_provider_credentials_are_separate_from_model_catalog() -> None:
    configured = Settings(
        openai_api_key="private-openai-key",
        provider_configs_json='{"router":{"api_key":"private-router-key","base_url":"https://router.example/v1"}}',
    )

    assert configured.provider_credentials("openai") == (
        "private-openai-key",
        "https://api.openai.com/v1",
    )
    assert configured.provider_credentials("router") == (
        "private-router-key",
        "https://router.example/v1",
    )


def test_model_router_fallback_stays_within_workspace_allowlist() -> None:
    router = ModelRouter()
    selected = "gpt-4o-mini"
    candidates = router.candidates(
        selected,
        auto_route=True,
        allowed_model_ids={selected, "gpt-4o"},
    )

    assert candidates[0].id == selected
    assert {model.id for model in candidates} == {selected, "gpt-4o"}


def test_model_catalog_validates_cost_and_identity_fields() -> None:
    model = ModelDefinition(
        id="vendor/model",
        provider="router",
        label="Example",
        input_cost_per_million=1.2,
        output_cost_per_million=2.4,
    )

    assert model.id == "vendor/model"
