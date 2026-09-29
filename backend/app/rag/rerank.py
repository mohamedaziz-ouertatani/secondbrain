"""Cross-encoder reranking of retrieval candidates: bge-reranker-v2-m3, fp16 ONNX on DirectML.

Off, missing or broken, rerank() returns None and retrieval keeps its own order: a question never fails because
of it. The model loads on first use and leaves the GPU after rerank_keep_alive idle minutes.
"""

import logging
import math
import threading
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np

from ..config import get_settings

log = logging.getLogger(__name__)

MODEL = "BAAI/bge-reranker-v2-m3"
BACKEND = Path(__file__).resolve().parents[2]
FAIL_LIMIT = 3  # scoring errors in a row before the reranker counts as broken

Scorer = Callable[[str, list[str]], list[float]]


class Unavailable(Exception):
    """The reranker can't run here; the message is the reason shown in the Status card."""


def model_path(settings) -> Path:
    p = Path(settings.rerank_model_path)
    return p if p.is_absolute() else BACKEND / p


def _tokenizer(max_length: int):
    from huggingface_hub import hf_hub_download
    from tokenizers import Tokenizer

    try:
        path = hf_hub_download(MODEL, "tokenizer.json", local_files_only=True)
    except Exception:
        path = hf_hub_download(MODEL, "tokenizer.json")
    tok = Tokenizer.from_file(path)
    tok.enable_truncation(max_length, strategy="longest_first")  # trims the passage for any normal question
    tok.enable_padding(pad_id=tok.token_to_id("<pad>"), pad_token="<pad>")
    return tok


def load_onnx(settings) -> Scorer:
    try:
        import onnxruntime as ort
    except ImportError as e:
        raise Unavailable("onnxruntime-directml isn't installed (Windows only)") from e
    path = model_path(settings)
    if not path.is_file():
        raise Unavailable(f"model file missing: {path} (see README, Reranker)")
    if "DmlExecutionProvider" not in ort.get_available_providers():
        raise Unavailable("DirectML not available")
    sess = ort.InferenceSession(str(path), providers=["DmlExecutionProvider"])
    tok = _tokenizer(settings.rerank_max_length)

    def score(question: str, texts: list[str]) -> list[float]:
        enc = tok.encode_batch([(question, t) for t in texts])
        feed = {"input_ids": np.array([e.ids for e in enc], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64)}
        return sess.run(None, feed)[0].reshape(-1).astype(np.float32).tolist()

    return score


class Reranker:
    def __init__(self, loader: Callable[..., Scorer] = load_onnx):
        self._loader = loader
        self._lock = threading.Lock()
        self._score: Scorer | None = None
        self._off_reason: str | None = None
        self._fails = 0
        self._last_used = 0.0
        self._timer: threading.Timer | None = None

    def reset(self) -> None:
        """Forget a failure and unload: called when the setting is toggled."""
        with self._lock:
            self._drop()
            self._off_reason, self._fails = None, 0

    def status(self) -> dict:
        with self._lock:
            if self._off_reason:  # a failure first: the evaluation forces the reranker even when it's turned off
                return {"state": "off", "reason": self._off_reason}
            loaded = self._score is not None
        if get_settings().rerank != "on":
            return {"state": "off", "reason": "turned off in Settings"}
        return {"state": "ready" if loaded else "not loaded", "reason": None}

    def rerank(self, question: str, hits: list[dict], force: bool = False) -> list[dict] | None:
        s = get_settings()
        if not hits or (s.rerank != "on" and not force):
            return None
        with self._lock:
            if self._off_reason:
                return None
            if self._score is None:
                try:
                    self._score = self._loader(s)
                except Exception as e:  # Unavailable, or a session that won't build
                    self._off(str(e) if isinstance(e, Unavailable) else f"couldn't load: {type(e).__name__}: {e}")
                    return None
            try:
                logits = self._score(question, [h["text"] for h in hits])
            except Exception as e:
                self._fails += 1
                log.warning("reranking failed (%d in a row): %s", self._fails, e)
                if self._fails >= FAIL_LIMIT:
                    self._off(f"scoring failed {FAIL_LIMIT} times in a row: {e}")
                return None
            self._fails = 0
            self._last_used = time.monotonic()
            self._schedule_unload(s.rerank_keep_alive * 60)
        scored = [{**h, "dense_rank": i, "rerank_score": 1 / (1 + math.exp(-x))}
                  for i, (h, x) in enumerate(zip(hits, logits, strict=True), start=1)]
        return sorted(scored, key=lambda h: -h["rerank_score"])

    # --- under the lock ---------------------------------------------------------------------
    def _off(self, reason: str) -> None:
        log.warning("reranker off: %s", reason)
        self._drop()
        self._off_reason = reason

    def _drop(self) -> None:
        self._score = None
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def _schedule_unload(self, seconds: float) -> None:
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(seconds, self._idle_unload, args=(seconds,))
        self._timer.daemon = True
        self._timer.start()

    def _idle_unload(self, seconds: float) -> None:
        with self._lock:
            if self._score and time.monotonic() - self._last_used >= seconds:
                self._score = None  # the session goes with the closure: its VRAM is freed
                log.info("reranker unloaded after %.0f idle minutes", seconds / 60)


reranker = Reranker()
