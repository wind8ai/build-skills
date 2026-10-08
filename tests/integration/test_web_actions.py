"""Owned workers and explicit retries preserve successful results and boundaries."""

import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
import tomli_w
from fastapi.testclient import TestClient

from build_skills.config import load_config
from build_skills.web.server import create_app

H = {"X-Build-Skills": "local"}
ROOT = Path(__file__).resolve().parents[2]


def wait(client, job):
    for _ in range(600):
        state = client.get(f"/api/jobs/{job}").json()
        if not state["busy"]:
            return state
        time.sleep(0.02)
    raise AssertionError("Worker did not settle")


def new_job(client):
    options = client.get("/api/options").json()
    material = client.post(
        "/api/materials", headers=H, files={"files": ("notes.txt", b"Copy exactly")}
    ).json()
    settings = {
        k: options[k]
        for k in ("builder", "executors", "max_rounds", "repetitions", "minimum_score")
    }
    return client.post(
        "/api/jobs",
        headers=H,
        json=settings | {"material": material["id"], "name": "action-test", "goal": "Copy exactly"},
    ).json()["id"]


def test_retry_failed_calls_preserves_success_and_delivers(tmp_path):
    config = load_config(ROOT / "examples/web/config.toml")
    config.providers["demo_b"].command += ["fail-once", str(tmp_path / "marker")]
    path = tmp_path / "config.toml"
    path.write_text(tomli_w.dumps(config.model_dump(exclude_none=True)))
    client = TestClient(create_app(path, tmp_path / "data"))
    job = new_job(client)
    state = wait(client, job)
    client.post(
        f"/api/jobs/{job}/accept-materials", headers=H, json={"digest": state["parsing_digest"]}
    )
    state = wait(client, job)
    client.post(f"/api/jobs/{job}/approve", headers=H, json={"digest": state["brief_digest"]})
    state = wait(client, job)
    assert state["status"] == "failed" and "retry_development" in state["allowed_actions"]
    assert client.post(f"/api/jobs/{job}/resume", headers=H, json={}).status_code == 409
    one = state["usage"]["execute:executor_1"]["calls"]
    two = state["usage"]["execute:executor_2"]["calls"]
    client.post(f"/api/jobs/{job}/actions/retry_development", headers=H, json={}).raise_for_status()
    state = wait(client, job)
    assert state["status"] == "delivered", state
    # One subsequent holdout call per model; only failed development cell repeats.
    assert state["usage"]["execute:executor_1"]["calls"] == one + 1
    assert state["usage"]["execute:executor_2"]["calls"] == two + 2
    assert (
        client.post(f"/api/jobs/{job}/actions/retry_holdout", headers=H, json={}).status_code == 409
    )


def test_cancel_owned_worker_and_restart_activity_detection(tmp_path):
    config = load_config(ROOT / "examples/web/config.toml")
    config.providers[config.roles["build"]].command += ["timeout"]
    path = tmp_path / "config.toml"
    path.write_text(tomli_w.dumps(config.model_dump(exclude_none=True)))
    data = tmp_path / "data"
    client = TestClient(create_app(path, data))
    job = new_job(client)
    state = wait(client, job)
    client.post(
        f"/api/jobs/{job}/accept-materials", headers=H, json={"digest": state["parsing_digest"]}
    )
    for _ in range(200):
        state = client.get(f"/api/jobs/{job}").json()
        if state.get("pending_call"):
            break
        time.sleep(0.02)
    assert state["busy"] and "cancel" in state["allowed_actions"]
    other = TestClient(create_app(path, data))
    assert other.get(f"/api/jobs/{job}").json()["busy"]
    assert other.post(f"/api/jobs/{job}/actions/cancel", headers=H, json={}).status_code == 409
    client.post(f"/api/jobs/{job}/actions/cancel", headers=H, json={}).raise_for_status()
    state = wait(client, job)
    assert state["status"] == "interrupted" and not state.get("pending_call")
    assert "resume" in state["allowed_actions"]


def test_interruption_after_material_confirmation_can_initialize_on_resume(tmp_path):
    from build_skills.config import digest
    from build_skills.web.materials import accept_materials

    data = tmp_path / "data"
    client = TestClient(create_app(ROOT / "examples/web/config.toml", data))
    job = new_job(client)
    state = wait(client, job)
    # Simulate interruption exactly after freezing inputs and before creating core state.
    accept_materials(data / "jobs" / job, digest(state["parsing"]))
    assert not (data / "jobs" / job / "runs" / job / "state.json").exists()
    client.post(f"/api/jobs/{job}/resume", headers=H, json={}).raise_for_status()
    state = wait(client, job)
    assert state["status"] == "awaiting_approval", state
    assert state["brief"] and not state.get("approval")


def test_worker_failure_saves_inside_run_lock(tmp_path, monkeypatch):
    from build_skills.web.jobs import lock_busy
    from build_skills.web.worker import perform
    from build_skills.workflow import Workflow
    from build_skills.workspace import WorkflowError

    data = tmp_path / "data"
    client = TestClient(create_app(ROOT / "examples/web/config.toml", data))
    job = new_job(client)
    state = wait(client, job)
    client.post(
        f"/api/jobs/{job}/accept-materials", headers=H, json={"digest": state["parsing_digest"]}
    ).raise_for_status()
    wait(client, job)
    original = Workflow.save
    writes = []

    def fail(self):
        raise WorkflowError("synthetic failure", 5)

    def save(self):
        writes.append(lock_busy(self.root / ".lock"))
        original(self)

    monkeypatch.setattr(Workflow, "loop", fail)
    monkeypatch.setattr(Workflow, "save", save)
    assert perform(data / "jobs" / job, "resume", {})["status"] == "failed"
    assert writes == [True]


@pytest.mark.parametrize("failed_file", ["request", "operation"])
def test_start_storage_failure_releases_reservation(tmp_path, monkeypatch, failed_file):
    from build_skills.web.jobs import JobRunner
    from build_skills.workspace import write_json

    job = tmp_path / "abcdef"
    job.mkdir()
    runner = JobRunner()

    def fail(path, value):
        if (failed_file == "request" and path.parent.name == "requests") or (
            failed_file == "operation" and path.name == "operation.json"
        ):
            raise OSError("synthetic disk full")
        write_json(path, value)

    monkeypatch.setattr("build_skills.web.jobs.write_json", fail)
    monkeypatch.setattr(
        "build_skills.web.jobs.subprocess.Popen",
        lambda *a, **kw: pytest.fail("Must not spawn after failed persistence"),
    )
    with pytest.raises(OSError):
        runner.start(job, "parse")
    assert not runner.busy(job) and not runner.owned(job)


def test_failed_parse_can_retry_in_same_job_and_preserves_evidence(tmp_path):
    import sys

    config = load_config(ROOT / "examples/web/config.toml")
    # Deterministic first-call failure, subsequent parser fixture succeeds.
    marker = tmp_path / "attempted"
    wrapper = tmp_path / "parser.py"
    wrapper.write_text(
        "import pathlib,sys,runpy\n"
        f"p=pathlib.Path({str(marker)!r})\n"
        "if not p.exists():\n p.write_text('first');sys.exit(7)\n"
        f"sys.argv=[{str(ROOT / 'tests/fixtures/agent.py')!r}]\n"
        f"runpy.run_path({str(ROOT / 'tests/fixtures/agent.py')!r},run_name='__main__')\n"
    )
    config.providers[config.roles["build"]].command = [sys.executable, str(wrapper)]
    path = tmp_path / "config.toml"
    path.write_text(tomli_w.dumps(config.model_dump(exclude_none=True)))
    data = tmp_path / "data"
    client = TestClient(create_app(path, data))
    options = client.get("/api/options").json()
    material = client.post(
        "/api/materials", headers=H, files={"files": ("sample.pdf", b"synthetic PDF")}
    ).json()
    settings = {
        k: options[k]
        for k in ("builder", "executors", "max_rounds", "repetitions", "minimum_score")
    }
    job = client.post(
        "/api/jobs",
        headers=H,
        json=settings | {"material": material["id"], "name": "parse-retry", "goal": "Copy"},
    ).json()["id"]
    state = wait(client, job)
    assert state["status"] == "failed" and state["allowed_actions"] == ["retry_parse"]
    client.post(f"/api/jobs/{job}/actions/retry_parse", headers=H, json={}).raise_for_status()
    state = wait(client, job)
    assert state["parsing"] and state["allowed_actions"] == ["accept_materials"]
    assert len(list((data / "jobs" / job / "parsing-history").glob("*/call/attempt.json"))) == 1
