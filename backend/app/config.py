from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

ROOT = Path(__file__).resolve().parents[2]
BASE_CONFIG = ROOT / "config.yaml"
LOCAL_CONFIG = ROOT / "config.local.yaml"  # written by the admin panel; git-ignored
ENV_FILE = ROOT / ".env"


class Settings(BaseSettings):
    """Precedence: env vars > .env > config.local.yaml (admin panel) > config.yaml > defaults below."""

    model_config = SettingsConfigDict(extra="ignore")

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
    ocr_enabled: bool = True  # read text inside images (backend/data/tessdata; python -m app.ingest.ocr --setup)
    ocr_min_words: int = 25  # PDF pages with fewer words than this (and an image) are OCR'd
    ocr_languages: str = "eng+fra"  # Tesseract languages; add +ara for Arabic slides

    retrieval_mode: Literal["dense", "hybrid"] = "dense"
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
    sync_auto_days: int = 7  # days between automatic syncs from the backend; 0 turns them off

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # module globals, read per call, so tests can point them at temp files
        return (
            init_settings,
            env_settings,
            DotEnvSettingsSource(settings_cls, env_file=ENV_FILE),
            YamlConfigSettingsSource(settings_cls, yaml_file=LOCAL_CONFIG),
            YamlConfigSettingsSource(settings_cls, yaml_file=BASE_CONFIG),
        )

    @property
    def inbox(self) -> Path:
        p = self.watch_dir
        return (p if p.is_absolute() else ROOT / p).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
