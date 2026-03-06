"""Async Anthropic client for proof pair classification."""

import asyncio
import json
import logging
from typing import Any

import anthropic
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


class LLMClient:
    """Wrapper around anthropic.AsyncAnthropic with rate limiting and retries."""

    def __init__(
        self,
        api_key: str,
        model: str,
        concurrency: int = 5,
        request_interval: float = 5.0,
    ) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model
        self._semaphore = asyncio.Semaphore(concurrency)
        self._request_interval = request_interval
        self._last_request: float = 0.0
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        await self._client.close()

    async def __aenter__(self) -> "LLMClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def _wait_for_interval(self) -> None:
        """Enforce minimum interval between requests."""
        async with self._lock:
            now = asyncio.get_event_loop().time()
            elapsed = now - self._last_request
            if elapsed < self._request_interval:
                await asyncio.sleep(self._request_interval - elapsed)
            self._last_request = asyncio.get_event_loop().time()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=10, max=120),
        retry=retry_if_exception_type(
            (anthropic.RateLimitError, anthropic.APIConnectionError)
        ),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    async def classify_pair(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> tuple[dict[str, Any], int, int]:
        """Send a proof pair to Claude for classification.

        Returns (parsed_json_response, input_tokens, output_tokens).
        """
        async with self._semaphore:
            await self._wait_for_interval()

            response = await self._client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )

            # Extract text content
            text = ""
            for block in response.content:
                if block.type == "text":
                    text = block.text
                    break

            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens

            # Parse JSON (strip markdown fences if present)
            text = text.strip()
            if text.startswith("```"):
                # Remove ```json ... ``` wrapper
                lines = text.split("\n")
                text = "\n".join(lines[1:-1]) if len(lines) > 2 else text

            parsed: dict[str, Any] = json.loads(text)
            return parsed, input_tokens, output_tokens
