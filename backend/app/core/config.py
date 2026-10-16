import json
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelDefinition(BaseModel):
    id: str
    provider: str
    label: str
    description: str = ""
    input_cost_per_million: float = Field(default=0, ge=0)
    output_cost_per_million: float = Field(default=0, ge=0)
    context_window: int = Field(default=128_000, gt=0)
    enabled: bool = True


DEFAULT_MODELS = [
    ModelDefinition(
        id="gpt-4o-mini",
        provider="openai",
        label="GPT-4o mini",
        description="Fast, cost-efficient general purpose model",
        input_cost_per_million=0.15,
        output_cost_per_million=0.6,
    ),
    ModelDefinition(
        id="gpt-4o",
        provider="openai",
        label="GPT-4o",
        description="Capable model for complex work",
        input_cost_per_million=2.5,
        output_cost_per_million=10,
    ),
    ModelDefinition(
        id="deepseek/deepseek-chat",
        provider="openrouter",
        label="DeepSeek Chat",
        description="General-purpose model available through OpenRouter",
        context_window=64_000,
    ),
    ModelDefinition(
        id="google/gemini-2.5-flash",
        provider="openrouter",
        label="Gemini 2.5 Flash",
        description="Fast multimodal model available through OpenRouter",
        context_window=1_000_000,
    ),
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Modelspace"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://multimodel:multimodel@localhost:5433/multimodel"
    redis_url: str = "redis://localhost:6380/0"
    jwt_secret: SecretStr = SecretStr("development-only-secret-change-before-deploying")
    access_token_minutes: int = Field(default=60, gt=0, le=1440)
    frontend_origin: str = "http://localhost:3000"
    openai_api_key: SecretStr = SecretStr("")
    openai_base_url: str = "https://api.openai.com/v1"
    provider_configs_json: str = "{}"
    model_catalog_json: str = ""
    cors_origins: str = "http://localhost:3000"

    @model_validator(mode="after")
    def require_production_secrets(self) -> "Settings":
        if self.environment == "production":
            if len(self.jwt_secret.get_secret_value()) < 32:
                raise ValueError("JWT_SECRET must contain at least 32 characters in production.")
            if self.jwt_secret.get_secret_value().startswith("development-only"):
                raise ValueError("Replace the development JWT secret before deploying.")
        return self

    def model_catalog(self) -> list[ModelDefinition]:
        if not self.model_catalog_json.strip():
            return DEFAULT_MODELS
        try:
            records: Any = json.loads(self.model_catalog_json)
            if not isinstance(records, list):
                raise ValueError("The model catalog must be a JSON array.")
            return [ModelDefinition.model_validate(record) for record in records]
        except (json.JSONDecodeError, ValueError) as error:
            raise ValueError("MODEL_CATALOG_JSON is invalid.") from error

    def provider_configs(self) -> dict[str, dict[str, str]]:
        if not self.provider_configs_json.strip():
            return {}
        try:
            value = json.loads(self.provider_configs_json)
            if not isinstance(value, dict) or any(
                not isinstance(item, dict) for item in value.values()
            ):
                raise ValueError("Provider settings must be a JSON object keyed by provider.")
            return value
        except (json.JSONDecodeError, ValueError) as error:
            raise ValueError("PROVIDER_CONFIGS_JSON is invalid.") from error

    def provider_credentials(self, provider: str) -> tuple[str, str]:
        configs = self.provider_configs()
        configured = configs.get(provider, {})
        if provider == "openai":
            return (
                str(configured.get("api_key") or self.openai_api_key.get_secret_value()),
                str(configured.get("base_url") or self.openai_base_url),
            )
        return str(configured.get("api_key", "")), str(configured.get("base_url", ""))

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
