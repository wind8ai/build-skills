"""Model choices must map to the actual CLI workflow and persist locally."""

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from build_skills.web.server import create_app


def test_web_has_requested_model_defaults(tmp_path: Path) -> None:
    client = TestClient(create_app(None, tmp_path))
    options = client.get("/api/options").json()
    assert options["agent_timeout_seconds"] == 600
    assert options["builder"]["model"] == "gpt-5.6-sol"
    assert options["builder"]["reasoning_effort"] == "high"
    assert [p["model"] for p in options["executors"]] == ["Qwen3.8-Flash"]


def test_saved_choices_drive_all_stages_and_duplicate_executions(tmp_path: Path) -> None:
    import json
    import time

    import tomli_w

    from build_skills.config import load_config

    root = Path(__file__).resolve().parents[2]
    config = load_config(root / "examples/local-files/config.toml")
    config.providers["demo_a"].command.append("improve")
    path = tmp_path / "config.toml"
    path.write_text(tomli_w.dumps(config.model_dump(exclude_none=True)))
    data_root = tmp_path / "data"
    client = TestClient(create_app(path, data_root))
    headers = {"X-Build-Skills": "local"}
    selected = {
        "builder": {"provider": "demo_a", "model": "build-v1", "reasoning_effort": "high"},
        "executors": [{"provider": "demo_b", "model": "execute-v1"}] * 2,
        "max_rounds": 3,
        "repetitions": 2,
        "minimum_score": 0.8,
        "parsing_timeout_seconds": 600,
    }
    response = client.put("/api/defaults", headers=headers, json=selected)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert Path(saved["defaults_path"]).is_relative_to(data_root)
    # Restarting reads personal defaults without changing the trusted command template.
    client = TestClient(create_app(path, data_root))
    assert client.get("/api/options").json()["executors"] == saved["executors"]
    uploaded = client.post(
        "/api/materials", headers=headers, files={"files": ("notes.txt", b"Copy exactly")}
    ).json()
    response = client.post(
        "/api/jobs",
        headers=headers,
        json=selected
        | {
            "material": uploaded["id"],
            "name": "repeat-test",
            "goal": "Copy exactly",
        },
    )
    assert response.status_code == 200, response.text
    identifier = response.json()["id"]

    def wait() -> dict:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            state = client.get(f"/api/jobs/{identifier}").json()
            if not state["busy"]:
                return state
            time.sleep(0.05)
        raise AssertionError("Workflow did not finish")

    state = wait()
    assert state["status"] == "awaiting_material_approval", state
    # Editing defaults cannot rewrite an existing task's model selection.
    selected["builder"] = {"provider": "demo_b", "model": "next-builder"}
    assert client.put("/api/defaults", headers=headers, json=selected).status_code == 200
    response = client.post(
        f"/api/jobs/{identifier}/accept-materials",
        headers=headers,
        json={"digest": state["parsing_digest"]},
    )
    assert response.status_code == 200
    state = wait()
    assert state["status"] == "awaiting_approval", state
    response = client.post(
        f"/api/jobs/{identifier}/approve",
        headers=headers,
        json={"digest": state["brief_digest"]},
    )
    assert response.status_code == 200
    state = wait()
    assert state["status"] == "delivered", state
    assert state["round"] == 2  # The broken first candidate required refactoring.
    actual = load_config(data_root / "jobs" / identifier / "config.toml")
    assert set(actual.roles.values()) == {"builder"}
    assert actual.execution.models == ["executor_1", "executor_2"]
    assert actual.execution.repetitions == 2
    assert actual.limits.build.timeout_seconds == 600
    assert actual.limits.improve.timeout_seconds == 600
    assert actual.providers["builder"].model == "build-v1"
    assert actual.providers["builder"].reasoning_effort == "high"
    attempts = [json.loads(p.read_text()) for p in Path(state["path"]).glob("calls/*/attempt.json")]
    for stage in ("prepare", "build", "evaluate", "improve"):
        assert {a["model"] for a in attempts if a["stage"] == stage} == {"build-v1"}
    assert {a["model"] for a in attempts if a["stage"] == "execute"} == {"execute-v1"}
    assert state["usage"]["execute:executor_1"]["calls"] == 6
    assert state["usage"]["execute:executor_2"]["calls"] == 6
    assert load_config(path).providers["demo_a"].model == ""


def test_model_settings_reject_unknown_connections_and_empty_execution(tmp_path: Path) -> None:
    client = TestClient(create_app(None, tmp_path))
    options = client.get("/api/options").json()
    selected = {
        key: options[key]
        for key in (
            "builder",
            "executors",
            "max_rounds",
            "repetitions",
            "minimum_score",
            "parsing_timeout_seconds",
        )
    }
    assert client.put("/api/defaults", json=selected).status_code == 403
    headers = {"X-Build-Skills": "local"}
    assert (
        client.put("/api/defaults", headers=headers, json=selected | {"executors": []}).status_code
        == 422
    )
    assert (
        client.put(
            "/api/defaults",
            headers=headers,
            json=selected | {"builder": {"provider": "unknown", "model": "x"}},
        ).status_code
        == 400
    )
