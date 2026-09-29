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

    # Reranker (app.rag.rerank): bge-reranker-v2-m3, fp16 ONNX on DirectML, reorders the candidate_k candidates
    rerank: Literal["off", "on"] = "on"
    rerank_max_length: int = 384  # tokens per question+passage pair; 512 doesn't fit beside the LLM in 4 GB
    rerank_keep_alive: float = 30  # minutes idle before the model is unloaded; 0 unloads after every question
    rerank_model_path: Path = Path("data/models/bge-reranker-v2-m3.fp16.onnx")  # relative to backend/

    backup_keep: int = 30  # daily backups of query_log and excluded_paths kept in backend/data/backups

    cors_origins: list[str] = ["http://localhost:3000"]

    # Blackboard sync (python -m app.sync.blackboard)
    blackboard_url: str = "https://esprit.blackboard.com"
    blackboard_browser: str = "msedge"  # or "chrome": an installed browser, so no Playwright download
    blackboard_course_map: dict[str, str] = {}  # Blackboard course name or id -> inbox folder
    blackboard_delay: float = 0.5  # seconds between API requests
    sync_auto_days: int = 7  # days between automatic syncs from the backend; 0 turns them off

    # Summaries, concepts and tags per document (app.enrich), made in the background after ingest
    enrich_enabled: bool = True
    enrich_paused: bool = False  # Pause/Resume in the admin panel writes this to config.local.yaml
    tag_merge_threshold: float = 0.85  # cosine at which a raw tag joins an existing tag

    # Retrieval experiments with summaries (off unless the evaluation shows a gain)
    doc_boost: float = 0.0  # adds doc_boost x similarity(question, file summary) to each passage's score
    doc_context: Literal["off", "on"] = "off"  # on: each passage in the prompt gets its file's summary line

    # Planner: extra module aliases for one-line capture, e.g. {"ml": "Optimization for ML"}
    planner_aliases: dict[str, str] = {}

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
