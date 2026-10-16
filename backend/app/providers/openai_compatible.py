import json
from collections.abc import AsyncIterator

import httpx

from app.providers.base import ProviderEvent


class ProviderError(Exception):
    pass


class OpenAICompatibleProvider:
    def __init__(self, timeout_seconds: float = 90) -> None:
        self.timeout_seconds = timeout_seconds

    async def stream(
        self, *, model: str, messages: list[dict[str, str]], api_key: str, base_url: str
    ) -> AsyncIterator[ProviderEvent]:
        if not api_key:
            raise ProviderError(
                "This provider is not configured. Add its API key to the backend environment."
            )
        endpoint = f"{base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        timeout = httpx.Timeout(self.timeout_seconds, connect=10)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST", endpoint, headers=headers, json=payload
                ) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", errors="replace")
                        raise ProviderError(
                            f"Provider returned HTTP {response.status_code}: {body[:500]}"
                        )
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            yield ProviderEvent(done=True)
                            return
                        try:
                            event = json.loads(data)
                        except json.JSONDecodeError as error:
                            raise ProviderError(
                                "Provider returned malformed stream data."
                            ) from error
                        usage = event.get("usage") or {}
                        choices = event.get("choices") or []
                        delta = choices[0].get("delta", {}) if choices else {}
                        content = delta.get("content", "")
                        if isinstance(content, str) and content:
                            yield ProviderEvent(text=content)
                        if usage:
                            yield ProviderEvent(
                                input_tokens=int(usage.get("prompt_tokens") or 0),
                                output_tokens=int(usage.get("completion_tokens") or 0),
                            )
        except httpx.TimeoutException as error:
            raise ProviderError(
                "The model provider timed out. Try again or choose another model."
            ) from error
        except httpx.HTTPError as error:
            raise ProviderError("The model provider could not be reached.") from error
