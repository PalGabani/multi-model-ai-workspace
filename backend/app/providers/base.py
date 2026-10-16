from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass
class ProviderEvent:
    text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    done: bool = False


class ModelProvider(Protocol):
    async def stream(
        self, *, model: str, messages: list[dict[str, str]], api_key: str, base_url: str
    ) -> AsyncIterator[ProviderEvent]: ...
