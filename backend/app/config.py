from functools import lru_cache
from pathlib import Path

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Precedence: env vars > .env > config.yaml > defaults below."""

    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", yaml_file=ROOT / "config.yaml", extra="ignore"
    )

    database_url: str = "postgresql://secondbrain:secondbrain@localhost:5433/secondbrain"
    ollama_url: str = "http://127.0.0.1:11434"  # not localhost: on Windows that tries IPv6 first (~2 s)

    llm_model: str = "qwen3:4b-instruct"
    embed_model: str = "bge-m3"
    embed_on_cpu: bool = True
    llm_keep_alive: str = "30m"
    embed_dim: int = 1024
    num_ctx: int = 4096
    temperature: float = 0.2

    watch_dir: Path = Path("inbox")
    chunk_tokens: int = 500
    chunk_overlap: int = 80
    embed_batch: int = 16

    retrieval_mode: str = "dense"  # or "hybrid"
    top_k: int = 5
    candidate_k: int = 20  # per list, before fusion
    rrf_k: int = 60
    min_score: float = 0.35

    cors_origins: list[str] = ["http://localhost:3000"]

    # Blackboard sync (python -m app.sync.blackboard)
    blackboard_url: str = "https://esprit.blackboard.com"
    blackboard_browser: str = "msedge"  # or "chrome": an installed browser, so no Playwright download
    blackboard_course_map: dict[str, str] = {}  # Blackboard course name or id -> inbox folder
    blackboard_delay: float = 0.5  # seconds between API requests

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings, env_settings, dotenv_settings, YamlConfigSettingsSource(settings_cls))

    @property
    def inbox(self) -> Path:
        p = self.watch_dir
        return (p if p.is_absolute() else ROOT / p).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
