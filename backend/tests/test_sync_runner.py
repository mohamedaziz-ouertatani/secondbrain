import os
import sys
from pathlib import Path

import pytest

FAKE = Path(__file__).parent / "fake_sync.py"
NOW = 1_800_000_000.0
DAY = 86_400


@pytest.fixture
def runner(tmp_path, monkeypatch):
    from app import config
    from app.admin.sync import SyncRunner

    (tmp_path / "inbox" / "Probability 2").mkdir(parents=True)
    monkeypatch.setenv("WATCH_DIR", str(tmp_path / "inbox"))
    monkeypatch.setenv("SYNC_AUTO_DAYS", "7")
    monkeypatch.delenv("FAKE_SYNC", raising=False)
    config.get_settings.cache_clear()
    clock = [NOW]
    r = SyncRunner(command=[sys.executable, str(FAKE)], runs_file=tmp_path / "runs.json",
                   state_file=tmp_path / "state.json", clock=lambda: clock[0])
    r.test_clock = clock
    yield r
    r.cancel()
    config.get_settings.cache_clear()


def logs(job):
    return " ".join(e["text"] for e in job["events"] if e["type"] == "log")


def test_run_collects_events_counts_and_history(runner):
    job = runner.start("sync")
    assert job["state"] == "running" and job["mode"] == "sync"
    runner.wait()
    s = runner.status()
    j = s["job"]
    assert j["state"] == "ok" and j["exit_code"] == 0
    assert j["counts"]["downloaded"] == 1 and j["counts"]["failed"] == 1 and j["bytes"] == 12288
    assert j["deadlines"] == {"type": "deadlines", "new": 2, "updated": 0, "removed": 0}
    assert s["runs"][0]["deadlines"] == j["deadlines"]
    assert j["courses"][1] == {"name": "Engineering Internship", "folder": None}
    assert "--json --headless" in logs(j) and "--dry-run" not in logs(j)
    assert s["runs"][0]["state"] == "ok" and "events" not in s["runs"][0]
    assert s["modules"] == ["Probability 2"]


def test_modes_pass_the_right_flags(runner):
    runner.start("preview", course="Probability 2")
    runner.wait()
    j = runner.status()["job"]
    assert "--headless --dry-run --course Probability 2" in logs(j) and j["counts"]["would_download"] == 1
    runner.start("login")
    runner.wait()
    assert "--headless" not in logs(runner.status()["job"])  # login opens a visible window


def test_busy_and_cancel(runner, monkeypatch):
    from app.admin.sync import Busy

    monkeypatch.setenv("FAKE_SYNC", "slow")
    runner.start("sync")
    with pytest.raises(Busy):
        runner.start("preview")
    assert runner.cancel()["state"] == "cancelled"
    assert runner.status()["runs"][0]["state"] == "cancelled"
    assert runner.cancel() is None  # nothing running


def test_login_required_sets_flag_and_ok_clears_it(runner, monkeypatch):
    monkeypatch.setenv("FAKE_SYNC", "login")
    runner.start("sync")
    runner.wait()
    s = runner.status()
    assert s["job"]["state"] == "login_required" and s["login_needed"] is True
    assert runner.due() is False and s["next_auto"] is None

    monkeypatch.setenv("FAKE_SYNC", "ok")
    runner.start("login")
    runner.wait()
    assert runner.login_needed() is False


def test_crash_is_failed_with_message(runner, monkeypatch):
    monkeypatch.setenv("FAKE_SYNC", "crash")
    runner.start("sync")
    runner.wait()
    j = runner.status()["job"]
    assert j["state"] == "failed" and j["error"] == "boom"


def test_due_follows_last_sync_setting_and_state_file(runner, monkeypatch):
    from app import config

    assert runner.due() is True  # never synced
    runner.state_file.write_text("{}", encoding="utf-8")  # the command-line sync ran two days ago
    os.utime(runner.state_file, (NOW - 2 * DAY, NOW - 2 * DAY))
    assert runner.due() is False
    assert runner.status()["next_auto"] is not None
    os.utime(runner.state_file, (NOW - 8 * DAY, NOW - 8 * DAY))
    assert runner.due() is True
    monkeypatch.setenv("SYNC_AUTO_DAYS", "0")
    config.get_settings.cache_clear()
    assert runner.due() is False and runner.status()["next_auto"] is None


def test_routes(runner, monkeypatch):
    from fastapi.testclient import TestClient

    from app.admin import sync
    from app.llm import ollama
    from app.main import create_app

    monkeypatch.setattr(sync, "runner", runner)
    monkeypatch.setattr(ollama, "status", lambda: {"reachable": False})
    client = TestClient(create_app())
    assert client.post("/admin/sync", json={"mode": "preview", "course": "Nope"}).status_code == 400
    assert client.post("/admin/sync", json={"mode": "bogus"}).status_code == 422
    assert client.post("/admin/sync/cancel").status_code == 404
    r = client.post("/admin/sync", json={"mode": "probe"})
    assert r.status_code == 202 and r.json()["mode"] == "probe"
    runner.wait()
    assert client.get("/admin/sync").json()["job"]["courses"][0]["folder"] == "Probability 2"
    assert client.get("/health").json()["blackboard_login_needed"] is False
