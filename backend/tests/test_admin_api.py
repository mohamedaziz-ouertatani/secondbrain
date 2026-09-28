import subprocess

import pytest
from fakes import fake_embed, words


@pytest.fixture
def client(env, monkeypatch):
    from fastapi.testclient import TestClient

    from app.ingest import pipeline
    from app.main import create_app

    monkeypatch.setattr(pipeline.ollama, "embed", fake_embed)
    monkeypatch.setattr(pipeline, "bge_m3_counter", lambda: words)
    return TestClient(create_app())  # no `with`: no watcher


def write(inbox, rel, body="Text about gaussian vectors and their characteristic functions. " * 10):
    p = inbox / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def test_library_exclude_include_reindex(env, client):
    from app.ingest.pipeline import rescan

    inbox, _ = env
    write(inbox, "Prob/a.md")
    write(inbox, "Prob/b.md")
    (inbox / "Prob" / "scan.txt").write_text("", encoding="utf-8")  # no text: a problem file
    rescan(fake_embed, words)

    lib = client.get("/admin/library").json()
    assert lib["modules"] == [{"course": "Prob", "documents": 3, "chunks": lib["modules"][0]["chunks"], "problems": 1}]
    assert [p["path"] for p in lib["problems"]] == ["Prob/scan.txt"]

    assert client.post("/admin/exclude", json={"path": "Prob/a.md"}).json() == {"removed": True}
    lib = client.get("/admin/library").json()
    assert lib["modules"][0]["documents"] == 2
    assert [(e["path"], e["on_disk"]) for e in lib["excluded"]] == [("Prob/a.md", True)]

    assert client.post("/admin/include", json={"path": "Prob/a.md"}).json() == {"status": "ok"}
    assert client.post("/admin/include", json={"path": "Prob/a.md"}).status_code == 404

    assert client.post("/admin/reindex", json={"course": "Prob"}).json() == {"ok": 2, "empty_text": 1}
    assert client.post("/admin/reindex", json={"path": "Prob/b.md"}).json() == {"ok": 1}
    assert client.post("/admin/reindex", json={}).status_code == 400
    assert client.post("/admin/reindex", json={"path": "Prob/b.md", "course": "Prob"}).status_code == 400
    assert client.post("/admin/reindex", json={"path": "Prob/nope.md"}).status_code == 404
    assert client.post("/admin/reindex", json={"course": "Nope"}).status_code == 404
    assert client.post("/admin/exclude", json={"path": "../outside.md"}).status_code == 400


def test_status_parts(env, client, monkeypatch):
    from app.admin import status
    from app.config import get_settings
    from app.llm import ollama

    _, db = env
    model = get_settings().llm_model
    monkeypatch.setattr(ollama, "status", lambda: {"reachable": True, "llm_pulled": True, "embed_pulled": True})
    monkeypatch.setattr(ollama, "loaded", lambda: [
        {"name": model, "size": 4000, "size_vram": 2680, "expires_at": "2026-09-28T10:30:00Z"}])
    monkeypatch.setattr(status.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 0, stdout="NVIDIA GeForce RTX 2050, 3712, 4096\n"))

    s = client.get("/admin/status").json()
    assert s["services"]["db"] == {"ok": True}
    assert s["llm"] == {"loaded": True, "model": model, "gpu_share": 0.67, "expires_at": "2026-09-28T10:30:00Z"}
    assert s["gpu"] == {"available": True, "name": "NVIDIA GeForce RTX 2050", "used_mib": 3712, "total_mib": 4096}
    assert s["answers"] == {"count": 0, "median_ms": None, "max_ms": None, "last_at": None}
    assert s["index"]["documents"] == 0 and s["index"]["excluded"] == 0 and s["index"]["db_bytes"] > 0

    with db.get_pool().connection() as conn:
        for ms in (4000, 8000, 60000):
            conn.execute("INSERT INTO query_log (question, latency_ms) VALUES ('q', %s)", (ms,))
    monkeypatch.setattr(ollama, "loaded", list)

    def no_smi(*a, **k):
        raise FileNotFoundError("nvidia-smi")

    monkeypatch.setattr(status.subprocess, "run", no_smi)
    s = client.get("/admin/status").json()
    assert s["llm"] == {"loaded": False, "model": model}
    assert s["gpu"] == {"available": False}
    assert s["answers"]["count"] == 3 and s["answers"]["median_ms"] == 8000 and s["answers"]["max_ms"] == 60000

    monkeypatch.setattr(ollama, "loaded", lambda: None)  # Ollama unreachable
    assert client.get("/admin/status").json()["llm"] is None
