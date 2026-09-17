"""Review questions are answered through the UI API, without editing a Brief."""

import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from build_skills.config import load_config
from build_skills.web.server import create_app
from build_skills.workspace import read_json, write_json

HEADERS = {"X-Build-Skills": "local"}


def wait(client: TestClient, job: str) -> dict:
    for _ in range(200):
        state = client.get(f"/api/jobs/{job}").json()
        if not state["busy"]:
            return state
        time.sleep(0.05)
    raise AssertionError("Review did not finish")


def test_answer_questions_then_review_revised_brief(tmp_path: Path) -> None:
    import tomli_w

    config = load_config(Path(__file__).resolve().parents[2] / "examples/web/config.toml")
    config.providers[config.roles["build"]].command.append("questions")
    path = tmp_path / "config.toml"
    path.write_text(tomli_w.dumps(config.model_dump(exclude_none=True)))
    client = TestClient(create_app(path, tmp_path / "data"))
    options = client.get("/api/options").json()
    material = client.post(
        "/api/materials", headers=HEADERS, files={"files": ("notes.txt", b"Copy text")}
    ).json()
    settings = {
        key: options[key]
        for key in ("builder", "executors", "max_rounds", "repetitions", "minimum_score")
    }
    response = client.post(
        "/api/jobs",
        headers=HEADERS,
        json=settings
        | {
            "material": material["id"],
            "name": "review",
            "goal": "Copy text",
        },
    )
    job = response.json()["id"]
    state = wait(client, job)
    client.post(
        f"/api/jobs/{job}/accept-materials",
        headers=HEADERS,
        json={"digest": state["parsing_digest"]},
    )
    state = wait(client, job)
    assert "error" not in state, "Expected approval is not an error"
    # Existing runs with questions must also be supported.
    run = Path(state["path"])
    brief = read_json(run / "brief.json")
    brief["questions"] = ["Should whitespace be preserved?"]
    write_json(run / "brief.json", brief)
    state = client.get(f"/api/jobs/{job}").json()
    original = state["brief_digest"]
    assert (
        client.post(
            f"/api/jobs/{job}/approve", headers=HEADERS, json={"digest": original}
        ).status_code
        == 400
    )
    for payload, code in [
        ({"digest": original, "answers": [" "]}, 400),
        ({"digest": "stale", "answers": ["yes"]}, 409),
    ]:
        assert (
            client.post(f"/api/jobs/{job}/review", headers=HEADERS, json=payload).status_code
            == code
        )
    response = client.post(
        f"/api/jobs/{job}/review",
        headers=HEADERS,
        json={"digest": original, "answers": ["fixture-failure"]},
    )
    assert response.status_code == 200
    state = wait(client, job)
    assert state["error"] and state["brief_digest"] == original
    response = client.post(
        f"/api/jobs/{job}/review", headers=HEADERS, json={"digest": original, "answers": ["unsure"]}
    )
    assert response.status_code == 200
    state = wait(client, job)
    assert state["brief"]["questions"] == ["Should leading spaces also be preserved?"]
    assert (
        client.post(
            f"/api/jobs/{job}/approve", headers=HEADERS, json={"digest": state["brief_digest"]}
        ).status_code
        == 400
    )
    original = state["brief_digest"]
    response = client.post(
        f"/api/jobs/{job}/review",
        headers=HEADERS,
        json={"digest": original, "answers": ["Preserve all whitespace."]},
    )
    assert response.status_code == 200, response.text
    state = wait(client, job)
    assert state["status"] == "awaiting_approval", state
    assert not state["brief"]["questions"]
    assert "Preserve all whitespace." in state["brief"]["criteria"]
    assert not state.get("approval") and state["round"] == 0
    assert state["brief_digest"] != original

    assert list((run / "history").glob("brief-*.json"))
    assert state["usage"]["prepare"]["calls"] == 4
    # Natural-language edits also work when there are no remaining questions.
    response = client.post(
        f"/api/jobs/{job}/review",
        headers=HEADERS,
        json={"digest": state["brief_digest"], "feedback": "Copy UTF-8 only."},
    )
    assert response.status_code == 200
    state = wait(client, job)
    assert state["brief"]["scope"] == "Copy UTF-8 only."
    assert len(state["review_history"]) == 4
    assert state["review_history"][2]["answers"][0]["answer"] == "Preserve all whitespace."
    assert state["review_history"][3]["requested_changes"] == "Copy UTF-8 only."
    response = client.post(
        f"/api/jobs/{job}/approve", headers=HEADERS, json={"digest": state["brief_digest"]}
    )
    assert response.status_code == 200
    state = wait(client, job)
    assert state["status"] == "delivered", state
    assert (
        client.post(
            f"/api/jobs/{job}/review",
            headers=HEADERS,
            json={"digest": state["brief_digest"], "feedback": "change"},
        ).status_code
        == 409
    )


def test_prepare_timeout_is_visible_and_retry_stays_in_review(tmp_path: Path) -> None:
    import sys

    import tomli_w

    config = load_config(Path(__file__).resolve().parents[2] / "examples/web/config.toml")
    original_command = config.providers[config.roles["build"]].command
    marker = tmp_path / "attempted"
    script = tmp_path / "slow-once.py"
    script.write_text(
        "import pathlib,sys,time,subprocess\n"
        f"marker=pathlib.Path({str(marker)!r})\n"
        "data=sys.stdin.read()\n"
        "if not marker.exists():\n marker.touch()\n time.sleep(5)\n"
        f"p=subprocess.run({original_command!r},input=data,text=True)\n"
        "sys.exit(p.returncode)\n"
    )
    config.providers[config.roles["build"]].command = [sys.executable, str(script)]
    path = tmp_path / "config.toml"
    path.write_text(tomli_w.dumps(config.model_dump(exclude_none=True)))
    client = TestClient(create_app(path, tmp_path / "data"))
    options = client.get("/api/options").json()
    material = client.post(
        "/api/materials", headers=HEADERS, files={"files": ("notes.txt", b"Copy text")}
    ).json()
    settings = {
        key: options[key]
        for key in ("builder", "executors", "max_rounds", "repetitions", "minimum_score")
    }
    job = client.post(
        "/api/jobs",
        headers=HEADERS,
        json=settings
        | {
            "material": material["id"],
            "name": "timeout-test",
            "goal": "Copy text",
            "agent_timeout_seconds": 1,
        },
    ).json()["id"]
    state = wait(client, job)
    client.post(
        f"/api/jobs/{job}/accept-materials",
        headers=HEADERS,
        json={"digest": state["parsing_digest"]},
    )
    for _ in range(100):
        state = client.get(f"/api/jobs/{job}").json()
        if state.get("current_call"):
            break
        time.sleep(0.01)
    assert state["current_call"]["stage"] == "prepare"
    assert state["current_call"]["timeout_seconds"] == 1
    assert state["current_call"]["elapsed_seconds"] >= 0
    state = wait(client, job)
    assert not state["busy"] and "timed out" in state["error"]
    client.post(f"/api/jobs/{job}/resume", headers=HEADERS, json={})
    state = wait(client, job)
    assert state["status"] == "awaiting_approval" and "error" not in state
    assert not state.get("approval")
