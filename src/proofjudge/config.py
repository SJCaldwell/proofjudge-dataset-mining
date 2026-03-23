"""Configuration via environment variables and pydantic-settings."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # API tokens
    github_token: str
    anthropic_api_key: str = ""

    # Target repository
    github_owner: str = "leanprover-community"
    github_repo: str = "mathlib4"

    # Data paths
    data_dir: Path = Path("data")

    # Rate limiting
    rest_requests_per_second: float = 1.2
    graphql_requests_per_second: float = 1.2
    search_requests_per_second: float = 0.45
    extraction_concurrency: int = 3

    # Summarization
    summarization_model: str = "claude-sonnet-4-20250514"
    summarization_concurrency: int = 5
    summarization_request_interval: float = 5.0

    # Error handling
    max_retries_per_pr: int = 3

    @property
    def repo_full_name(self) -> str:
        return f"{self.github_owner}/{self.github_repo}"

    @property
    def discovery_dir(self) -> Path:
        return self.data_dir / "discovery"

    @property
    def enrichment_dir(self) -> Path:
        return self.data_dir / "enrichment"

    @property
    def extraction_dir(self) -> Path:
        return self.data_dir / "extraction"

    @property
    def parsing_dir(self) -> Path:
        return self.data_dir / "parsing"

    @property
    def summarization_dir(self) -> Path:
        return self.data_dir / "summarization"

    @property
    def contexts_dir(self) -> Path:
        return self.data_dir / "contexts"

    @property
    def dataset_dir(self) -> Path:
        return self.data_dir / "dataset"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "proofjudge.db"
