import pytest

KEYS = ("top_k", "candidate_k", "rrf_k", "min_score", "retrieval_mode", "llm_model",
        "temperature", "num_ctx", "llm_keep_alive", "embed_model", "sync_auto_days")


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """Point the settings layers at temp files, clear any real env overrides, fake Ollama's model list."""
    from app import config
    from app.llm import ollama

    base = tmp_path / "config.yaml"
    base.write_text("top_k: 5\ncandidate_k: 20\nllm_model: qwen3:4b-instruct\n", encoding="utf-8")
    monkeypatch.setattr(config, "BASE_CONFIG", base)
    monkeypatch.setattr(config, "LOCAL_CONFIG", tmp_path / "config.local.yaml")
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")
    for k in KEYS:
        monkeypatch.delenv(k.upper(), raising=False)
    monkeypatch.setattr(ollama, "pulled", lambda: ["bge-m3:latest", "qwen2.5:3b", "qwen3:4b-instruct"])
    config.get_settings.cache_clear()
    yield tmp_path
    config.get_settings.cache_clear()


def local(tmp):
    import yaml

    p = tmp / "config.local.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else None


def test_precedence_and_sources(cfg, monkeypatch):
    from app.admin.settings import source
    from app.config import get_settings

    assert get_settings().top_k == 5 and source("top_k") == ("config", None)
    assert source("rrf_k") == ("default", None)

    (cfg / "config.local.yaml").write_text("top_k: 3\n", encoding="utf-8")
    get_settings.cache_clear()
    assert get_settings().top_k == 3 and source("top_k") == ("local", None)

    (cfg / ".env").write_text("RRF_K=40\n", encoding="utf-8")
    monkeypatch.setenv("TOP_K", "7")
    get_settings.cache_clear()
    assert get_settings().top_k == 7 and source("top_k") == ("env", "TOP_K")
    assert get_settings().rrf_k == 40 and source("rrf_k") == ("env", "RRF_K")


def test_update_writes_validates_and_resets(cfg):
    from app.admin.settings import Invalid, update
    from app.config import get_settings

    update({"top_k": 4, "retrieval_mode": "hybrid", "llm_model": "qwen2.5:3b"})
    assert local(cfg) == {"llm_model": "qwen2.5:3b", "retrieval_mode": "hybrid", "top_k": 4}
    assert get_settings().top_k == 4  # cache cleared, no restart

    bad = [
        ({"top_k": 11}, "top_k"),
        ({"top_k": True}, "top_k"),
        ({"candidate_k": 3}, "candidate_k"),  # below the effective top_k (4)
        ({"llm_keep_alive": "forever"}, "llm_keep_alive"),
        ({"llm_model": "llama3:70b"}, "llm_model"),  # not pulled
        ({"llm_model": "bge-m3:latest"}, "llm_model"),  # the embed model
        ({"retrieval_mode": "sparse"}, "retrieval_mode"),
        ({"embed_model": "x"}, "embed_model"),  # read-only
        ({"nope": 1}, "nope"),
        ({"top_k": 3, "rrf_k": 0}, "rrf_k"),  # all or nothing: top_k must not be written either
    ]
    for change, key in bad:
        with pytest.raises(Invalid) as e:
            update(change)
        assert key in e.value.errors, change
        assert local(cfg)["top_k"] == 4, change

    update({"top_k": None})  # reset
    assert "top_k" not in local(cfg)
    assert get_settings().top_k == 5


def test_env_locked_key_is_refused(cfg, monkeypatch):
    from app.admin.settings import Invalid, update, view

    monkeypatch.setenv("TOP_K", "6")
    row = next(r for g in view()["groups"] for r in g["rows"] if r["key"] == "top_k")
    assert row["source"] == "env" and row["locked_by"] == "TOP_K" and row["value"] == 6
    with pytest.raises(Invalid) as e:
        update({"top_k": 2})
    assert "TOP_K" in e.value.errors["top_k"]


def test_routes(cfg):
    from fastapi.testclient import TestClient

    from app.main import create_app

    client = TestClient(create_app())
    v = client.get("/admin/settings").json()
    assert [g["name"] for g in v["groups"]] == ["Retrieval", "Answers", "Blackboard"]
    model = next(r for r in v["groups"][1]["rows"] if r["key"] == "llm_model")
    assert model["options"] == ["qwen2.5:3b", "qwen3:4b-instruct"]
    assert {r["key"] for r in v["readonly"]} >= {"embed_model", "database_url", "watch_dir"}
    assert "secondbrain:secondbrain@" not in next(r["value"] for r in v["readonly"] if r["key"] == "database_url")

    r = client.put("/admin/settings", json={"top_k": 99})
    assert r.status_code == 422 and "top_k" in r.json()["detail"]
    r = client.put("/admin/settings", json={"top_k": 3})
    assert r.status_code == 200
    assert next(x for x in r.json()["groups"][0]["rows"] if x["key"] == "top_k")["value"] == 3

    pre = client.options("/admin/settings", headers={
        "Origin": "http://localhost:3000", "Access-Control-Request-Method": "PUT"})
    assert pre.status_code == 200
