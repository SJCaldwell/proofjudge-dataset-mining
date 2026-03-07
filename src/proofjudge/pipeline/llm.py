"""Async Anthropic client for proof pair classification."""

import asyncio
import json
import logging
import re
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

            # Extract JSON from response text
            parsed = _extract_json(text)
            if parsed is None:
                raise ValueError(
                    f"No valid JSON in Claude response "
                    f"(stop_reason={response.stop_reason}, "
                    f"text={text[:200]!r})"
                )
            return parsed, input_tokens, output_tokens


def _extract_json(text: str) -> dict[str, Any] | None:
    """Extract a JSON object from LLM response text.

    Handles: raw JSON, markdown fences, text before/after JSON.
    """
    text = text.strip()
    if not text:
        return None

    # Strip markdown fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        inner = [line for line in lines[1:] if line.strip() != "```"]
        text = "\n".join(inner).strip()

    # Try direct parse first
    try:
        result: dict[str, Any] = json.loads(text)
        return result
    except json.JSONDecodeError:
        pass

    # Find JSON object within surrounding text
    match = re.search(r"\{", text)
    if match:
        # Find the matching closing brace by counting depth
        start = match.start()
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            c = text[i]
            if escape:
                escape = False
                continue
            if c == "\\":
                escape = True
                continue
            if c == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        result = json.loads(text[start : i + 1])
                        return result
                    except json.JSONDecodeError:
                        break

    return None
