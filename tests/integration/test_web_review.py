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
