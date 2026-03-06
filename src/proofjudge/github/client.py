"""Async GitHub HTTP client with rate limiting and retries."""

import asyncio
import logging
import time
from typing import Any

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"

RETRYABLE_STATUS_CODES = {429, 500, 502, 503}


class GitHubAPIError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"GitHub API {status_code}: {message}")


class RetryableGitHubError(GitHubAPIError):
    pass


class RateLimiter:
    """Token bucket rate limiter with GitHub header awareness."""

    def __init__(self, api_type: str, max_per_second: float) -> None:
        self.api_type = api_type
        self.max_per_second = max_per_second
        self.remaining = 5000
        self.reset_at: float = 0.0
        self._lock = asyncio.Lock()
        self._last_request: float = 0.0

    async def acquire(self) -> None:
        """Wait until a request is allowed."""
        async with self._lock:
            now = time.monotonic()

            # If we've nearly exhausted the quota, sleep until reset
            if self.remaining <= 50:
                sleep_time = max(0, self.reset_at - time.time())
                if sleep_time > 0:
                    logger.info(
                        "Rate limit near exhaustion for %s, sleeping %.0fs",
                        self.api_type,
                        sleep_time,
                    )
                    await asyncio.sleep(sleep_time)

            # Enforce minimum interval between requests
            min_interval = 1.0 / self.max_per_second
            elapsed = now - self._last_request
            if elapsed < min_interval:
                await asyncio.sleep(min_interval - elapsed)

            self._last_request = time.monotonic()

    def update_from_headers(self, headers: httpx.Headers) -> None:
        """Update state from GitHub response headers."""
        if "x-ratelimit-remaining" in headers:
            self.remaining = int(headers["x-ratelimit-remaining"])
        if "x-ratelimit-reset" in headers:
            self.reset_at = float(headers["x-ratelimit-reset"])
        if self.remaining <= 100:
            logger.warning(
                "Rate limit low for %s: %d remaining, resets at %s",
                self.api_type,
                self.remaining,
                time.ctime(self.reset_at),
            )


class GitHubClient:
    """Async GitHub API client with rate limiting."""

    def __init__(self, token: str) -> None:
        self.token = token
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.v3+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
            http2=True,
        )
        self.rest_limiter = RateLimiter("rest", max_per_second=1.2)
        self.graphql_limiter = RateLimiter("graphql", max_per_second=1.2)
        self.search_limiter = RateLimiter("search", max_per_second=0.45)

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "GitHubClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=4, max=120),
        retry=retry_if_exception_type(RetryableGitHubError),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    async def rest_get(self, path: str, **params: str | int) -> httpx.Response:
        """Make an authenticated GET request to the GitHub REST API."""
        await self.rest_limiter.acquire()
        url = f"{GITHUB_API_BASE}{path}" if path.startswith("/") else f"{GITHUB_API_BASE}/{path}"
        response = await self._client.get(url, params=params)
        self.rest_limiter.update_from_headers(response.headers)

        if response.status_code in RETRYABLE_STATUS_CODES:
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", "60"))
                await asyncio.sleep(retry_after)
            raise RetryableGitHubError(response.status_code, response.text[:200])

        if response.status_code >= 400:
            raise GitHubAPIError(response.status_code, response.text[:200])

        return response

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=4, max=120),
        retry=retry_if_exception_type(RetryableGitHubError),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    async def graphql(
        self, query: str, variables: dict[str, object] | None = None
    ) -> dict[str, Any]:
        """Execute a GraphQL query against the GitHub API."""
        await self.graphql_limiter.acquire()
        payload: dict[str, object] = {"query": query}
        if variables:
            payload["variables"] = variables

        response = await self._client.post(GITHUB_GRAPHQL_URL, json=payload)
        self.graphql_limiter.update_from_headers(response.headers)

        if response.status_code in RETRYABLE_STATUS_CODES:
            raise RetryableGitHubError(response.status_code, response.text[:200])

        if response.status_code >= 400:
            raise GitHubAPIError(response.status_code, response.text[:200])

        data: dict[str, Any] = response.json()
        if "errors" in data:
            errors: list[dict[str, str]] = data["errors"]
            error_msgs = "; ".join(e.get("message", "unknown") for e in errors)
            logger.warning("GraphQL errors: %s", error_msgs)

        return data

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=4, max=120),
        retry=retry_if_exception_type(RetryableGitHubError),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    async def search(self, query: str, page: int = 1, per_page: int = 30) -> httpx.Response:
        """Execute a search API query with its own rate limiter."""
        await self.search_limiter.acquire()
        response = await self._client.get(
            f"{GITHUB_API_BASE}/search/issues",
            params={"q": query, "page": page, "per_page": per_page},
        )
        self.search_limiter.update_from_headers(response.headers)

        if response.status_code in RETRYABLE_STATUS_CODES:
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", "60"))
                await asyncio.sleep(retry_after)
            raise RetryableGitHubError(response.status_code, response.text[:200])

        if response.status_code >= 400:
            raise GitHubAPIError(response.status_code, response.text[:200])

        return response

    async def rest_get_all_pages(
        self, path: str, per_page: int = 100, **params: str | int
    ) -> list[dict[str, Any]]:
        """Fetch all pages of a paginated REST endpoint."""
        all_items: list[dict[str, Any]] = []
        page = 1
        while True:
            response = await self.rest_get(path, per_page=per_page, page=page, **params)
            items: list[dict[str, Any]] = response.json()
            if not items:
                break
            all_items.extend(items)
            # Check for Link header indicating more pages
            if "next" not in response.headers.get("link", ""):
                break
            page += 1
        return all_items
