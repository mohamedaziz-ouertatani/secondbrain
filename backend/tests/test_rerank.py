import math
import time

import pytest


@pytest.fixture
def on(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("RERANK", "on")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def hits(*texts):
    return [{"chunk_id": i, "text": t, "score": 0.5} for i, t in enumerate(texts, start=1)]


def keyword_scorer(word):
    """Fake cross-encoder: a big logit for passages containing `word`, a small one otherwise."""
    return lambda question, texts: [5.0 if word in t else -5.0 for t in texts]


def counting_loader(score, calls):
    def load(settings):
        calls.append(1)
        return score
    return load


def broken_loader(settings):
    from app.rag.rerank import Unavailable

    raise Unavailable("DirectML not available")


def throwing_scorer(question, texts):
    raise RuntimeError("device lost")


def test_reorders_by_score_and_keeps_the_dense_rank(on):
    from app.rag.rerank import Reranker

    out = Reranker(loader=lambda s: keyword_scorer("gradient")).rerank(
        "q", hits("docker", "the gradient", "kubernetes"))
    assert [h["chunk_id"] for h in out] == [2, 1, 3]
    assert out[0]["dense_rank"] == 2 and out[0]["rerank_score"] == pytest.approx(1 / (1 + math.exp(-5)))
    assert 0 < out[1]["rerank_score"] < 0.01


def test_off_unless_forced(on, monkeypatch):
    from app.config import get_settings
    from app.rag.rerank import Reranker

    monkeypatch.setenv("RERANK", "off")
    get_settings.cache_clear()
    r = Reranker(loader=lambda s: keyword_scorer("x"))
    assert r.rerank("q", hits("a")) is None
    assert r.status() == {"state": "off", "reason": "turned off in Settings"}
    assert r.rerank("q", hits("a", "x"), force=True)[0]["chunk_id"] == 2


def test_loads_once_on_first_use(on):
    from app.rag.rerank import Reranker

    calls = []
    r = Reranker(loader=counting_loader(keyword_scorer("a"), calls))
    assert r.status()["state"] == "not loaded"
    r.rerank("q", hits("a"))
    r.rerank("q", hits("b"))
    assert len(calls) == 1 and r.status() == {"state": "ready", "reason": None}


def test_a_load_failure_sticks_until_reset(on):
    from app.rag.rerank import Reranker

    calls = []

    def broken(settings):
        calls.append(1)
        broken_loader(settings)

    r = Reranker(loader=broken)
    assert r.rerank("q", hits("a")) is None and r.rerank("q", hits("a")) is None
    assert len(calls) == 1 and r.status() == {"state": "off", "reason": "DirectML not available"}
    r.reset()
    assert r.status()["state"] == "not loaded"


def test_scoring_errors_fall_back_and_three_in_a_row_turn_it_off(on):
    from app.rag.rerank import Reranker

    state = {"fail": True}

    def flaky(question, texts):
        if state["fail"]:
            throwing_scorer(question, texts)
        return [0.0] * len(texts)

    r = Reranker(loader=lambda s: flaky)
    assert r.rerank("q", hits("a")) is None and r.status()["state"] == "ready"
    state["fail"] = False
    assert r.rerank("q", hits("a")) is not None  # a success resets the count
    state["fail"] = True
    for _ in range(3):
        assert r.rerank("q", hits("a")) is None
    assert r.status()["state"] == "off" and "device lost" in r.status()["reason"]


def test_idle_unload_frees_the_model(on, monkeypatch):
    from app.config import get_settings
    from app.rag.rerank import Reranker

    monkeypatch.setenv("RERANK_KEEP_ALIVE", "0")
    get_settings.cache_clear()
    calls = []
    r = Reranker(loader=counting_loader(keyword_scorer("a"), calls))
    r.rerank("q", hits("a"))
    time.sleep(0.2)
    assert r.status()["state"] == "not loaded"
    r.rerank("q", hits("a"))
    assert len(calls) == 2


def test_empty_hits_are_left_alone(on):
    from app.rag.rerank import Reranker

    assert Reranker(loader=lambda s: keyword_scorer("a")).rerank("q", []) is None


def test_missing_model_file_is_a_reason(on, monkeypatch, tmp_path):
    from app.config import get_settings
    from app.rag.rerank import Reranker

    monkeypatch.setenv("RERANK_MODEL_PATH", str(tmp_path / "nope.onnx"))
    get_settings.cache_clear()
    r = Reranker()
    assert r.rerank("q", hits("a")) is None
    assert r.status()["state"] == "off" and "model file missing" in r.status()["reason"]


def test_real_model_ranks_the_on_topic_passage_first(on):
    from app.config import get_settings
    from app.rag.rerank import Reranker, model_path

    if not model_path(get_settings()).is_file():
        pytest.skip("no reranker model file")
    r = Reranker()
    out = r.rerank("What is top-p sampling?", hits(
        "Docker images are built from a Dockerfile, layer by layer.",
        "Top-p (nucleus) sampling keeps the smallest set of tokens whose probabilities sum to p."))
    if out is None:
        pytest.skip(r.status()["reason"])
    assert out[0]["chunk_id"] == 2 and out[0]["rerank_score"] > 0.5 > out[1]["rerank_score"]
