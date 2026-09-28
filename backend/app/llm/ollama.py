"""Thin Ollama HTTP client: batched embeddings + streaming chat."""

import json
import threading
from collections.abc import Iterator

import httpx
import numpy as np

from ..config import get_settings


class OllamaError(RuntimeError):
    pass


# One client for the process. On Windows, building an httpx client costs ~0.5 s and a fresh
# connection to "localhost" waits ~2 s for IPv6 before falling back, so a client per call added
# ~2.4 s to every Ollama request. Reused, the connection stays open and a call takes milliseconds.
_shared: httpx.Client | None = None
_shared_lock = threading.Lock()


def _client() -> httpx.Client:
    global _shared
    url = get_settings().ollama_url
    with _shared_lock:
        if _shared is None or str(_shared.base_url).rstrip("/") != url.rstrip("/"):
            _shared = httpx.Client(base_url=url, timeout=300)
        return _shared


def embed(texts: list[str]) -> list[np.ndarray]:
    """Embed texts with the configured model, L2-normalized, in batches."""
    s = get_settings()
    out: list[np.ndarray] = []
    for i in range(0, len(texts), s.embed_batch):
        batch = texts[i : i + s.embed_batch]
        body = {"model": s.embed_model, "input": batch}
        if s.embed_on_cpu:
            body["options"] = {"num_gpu": 0}  # never evicts the chat model from VRAM
        r = _client().post("/api/embed", json=body)
        if r.status_code != 200:
            raise OllamaError(f"embed failed ({r.status_code}): {r.text[:200]}")
        for v in r.json()["embeddings"]:
            a = np.asarray(v, dtype=np.float32)
            norm = np.linalg.norm(a)
            out.append(a / norm if norm else a)
    return out


def strip_reasoning(text: str) -> str:
    """Drop a reasoning trace. Some thinking models ignore think=false and emit it inline,
    sometimes with only the closing tag (the template opens it)."""
    return text.rsplit("</think>", 1)[-1].lstrip() if "</think>" in text else text


def hide_leading_think(tokens: Iterator[str]) -> Iterator[str]:
    """Pass tokens through, but swallow a leading <think>...</think> block."""
    head = ""
    after_think = False
    for tok in tokens:
        head += tok
        if after_think:
            head = head.lstrip()
        else:
            stripped = head.lstrip()
            if stripped.startswith("<think>"):
                if "</think>" not in head:
                    continue  # still inside the reasoning block
                head, after_think = strip_reasoning(head), True
            elif "<think>".startswith(stripped):
                continue  # could still become "<think>"
        if not head:
            continue  # only whitespace after the reasoning so far
        yield head
        yield from tokens  # past the head: stream the rest untouched
        return
    if head and not head.lstrip().startswith("<think>"):
        yield head


def chat_stream(messages: list[dict]) -> Iterator[str]:
    """Yield content tokens from a streaming chat completion."""
    s = get_settings()
    body = {
        "model": s.llm_model,
        "messages": messages,
        "stream": True,
        "think": False,  # skip reasoning on models that support it; ignored by others
        "keep_alive": s.llm_keep_alive,
        "options": {"num_ctx": s.num_ctx, "temperature": s.temperature},
    }

    def raw() -> Iterator[str]:
        with _client().stream("POST", "/api/chat", json=body) as r:
            if r.status_code != 200:
                r.read()
                raise OllamaError(f"chat failed ({r.status_code}): {r.text[:200]}")
            for line in r.iter_lines():
                if not line:
                    continue
                msg = json.loads(line)
                if "error" in msg:
                    raise OllamaError(msg["error"])
                token = msg.get("message", {}).get("content", "")
                if token:
                    yield token
                if msg.get("done"):
                    return

    yield from hide_leading_think(raw())


def status() -> dict:
    """Reachability + whether configured models are pulled."""
    s = get_settings()
    try:
        names = {m["name"] for m in _client().get("/api/tags", timeout=5).json().get("models", [])}
    except httpx.HTTPError as e:
        return {"reachable": False, "error": str(e)}

    def pulled(model: str) -> bool:
        return model in names or f"{model}:latest" in names

    return {
        "reachable": True,
        "llm_model": s.llm_model,
        "llm_pulled": pulled(s.llm_model),
        "embed_model": s.embed_model,
        "embed_pulled": pulled(s.embed_model),
    }


def loaded() -> list[dict] | None:
    """Models Ollama holds in memory (/api/ps), with size and size_vram; None if Ollama is unreachable."""
    try:
        return _client().get("/api/ps", timeout=5).json().get("models", [])
    except httpx.HTTPError:
        return None
