from collections.abc import AsyncIterator

from app.core.config import ModelDefinition, settings
from app.providers.base import ProviderEvent
from app.providers.openai_compatible import OpenAICompatibleProvider


class ModelRouter:
    def __init__(self) -> None:
        self.provider = OpenAICompatibleProvider()

    def candidates(
        self,
        selected_model: str,
        auto_route: bool,
        allowed_model_ids: set[str] | None = None,
    ) -> list[ModelDefinition]:
        catalog = [model for model in settings.model_catalog() if model.enabled]
        if allowed_model_ids is not None:
            catalog = [model for model in catalog if model.id in allowed_model_ids]
        selected = next((model for model in catalog if model.id == selected_model), None)
        if selected is None:
            raise ValueError("The selected model is not in the enabled model catalog.")
        if not auto_route:
            return [selected]
        ordered = sorted(
            catalog, key=lambda model: (model.input_cost_per_million, model.output_cost_per_million)
        )
        return [selected, *(model for model in ordered if model.id != selected.id)]

    async def stream(
        self, model: ModelDefinition, messages: list[dict[str, str]]
    ) -> AsyncIterator[ProviderEvent]:
        api_key, base_url = settings.provider_credentials(model.provider)
        if not base_url:
            raise ValueError(
                f"No OpenAI-compatible endpoint is configured for provider '{model.provider}'."
            )
        async for event in self.provider.stream(
            model=model.id,
            messages=messages,
            api_key=api_key,
            base_url=base_url,
        ):
            yield event


model_router = ModelRouter()
