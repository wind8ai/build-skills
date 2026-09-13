"""Exercise the actual local API, CLI subprocesses and delivery archive."""

import io
import time
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from build_skills.web.server import create_app

HEADERS = {"X-Build-Skills": "local"}
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(ROOT / "examples/local-files/config.toml", tmp_path))


def wait(client: TestClient, identifier: str) -> dict:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        result = client.get(f"/api/jobs/{identifier}").json()
        if not result["busy"]:
            return result
        time.sleep(0.05)
    pytest.fail("Workflow did not settle")


def test_upload_approve_deliver(client: TestClient) -> None:
    response = client.post(
        "/api/materials", headers=HEADERS, files=[("files", ("notes.md", b"Copy text exactly."))]
    )
    assert response.status_code == 200, response.text
    material = response.json()
    options = client.get("/api/options").json()
    settings = {
        key: options[key]
        for key in (
            "name",
            "goal",
            "builder",
            "executors",
            "max_rounds",
            "repetitions",
            "minimum_score",
        )
    }
    settings["material"] = material["id"]
    response = client.post("/api/jobs", headers=HEADERS, json=settings)
    assert response.status_code == 200, response.text
    identifier = response.json()["id"]
    state = wait(client, identifier)
    assert state["status"] == "awaiting_material_approval", state
    assert state["parsing"]["calls"] == 0
    assert (
        client.post(f"/api/jobs/{identifier}/resume", headers=HEADERS, json={}).status_code == 409
    )
    response = client.post(
        f"/api/jobs/{identifier}/accept-materials",
        headers=HEADERS,
        json={"digest": state["parsing_digest"]},
    )
    assert response.status_code == 200, response.text
    state = wait(client, identifier)
    assert state["status"] == "awaiting_approval", state
    assert client.get(f"/api/jobs/{identifier}/download").status_code == 409
    bad = client.post(
        f"/api/jobs/{identifier}/approve",
        headers=HEADERS,
        json={"digest": "outdated"},
    )
    assert bad.status_code == 409
    response = client.post(
        f"/api/jobs/{identifier}/approve",
        headers=HEADERS,
        json={"digest": state["brief_digest"]},
    )
    assert response.status_code == 200, response.text
    state = wait(client, identifier)
    assert state["status"] == "delivered", state
    archive = client.get(f"/api/jobs/{identifier}/download")
    assert archive.status_code == 200, archive.text
    with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
        assert set(bundle.namelist()) == {"skill/SKILL.md", "report.json"}
    assert client.get(f"/api/jobs/{identifier}/report").json()
    assert client.get("/api/jobs").json()[0]["id"] == identifier


def test_local_boundary_and_bad_upload(client: TestClient) -> None:
    assert client.post("/api/materials").status_code == 403
    assert client.get("/api/options", headers={"host": "evil.example"}).status_code == 403
    assert (
        client.post(
            "/api/materials",
            headers=HEADERS | {"origin": "https://evil.example"},
            files={"files": ("a.txt", b"hello")},
        ).status_code
        == 403
    )
    for name, content in [
        ("../notes.md", b"hello"),
        ("empty.txt", b""),
        ("data.bin", b"binary"),
    ]:
        response = client.post("/api/materials", headers=HEADERS, files={"files": (name, content)})
        assert response.status_code == 400, response.text
    assert client.get("/api/jobs/not-an-id").status_code == 404


def create_job(client: TestClient, files: list, timeout: float = 600) -> str:
    response = client.post("/api/materials", headers=HEADERS, files=files)
    assert response.status_code == 200, response.text
    material = response.json()
    options = client.get("/api/options").json()
    settings = {
        key: options[key]
        for key in (
            "name",
            "goal",
            "builder",
            "executors",
            "max_rounds",
            "repetitions",
            "minimum_score",
        )
    }
    settings["material"] = material["id"]
    settings["parsing_timeout_seconds"] = timeout
    response = client.post("/api/jobs", headers=HEADERS, json=settings)
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_complex_files_are_parsed_once_and_reviewed(client: TestClient, tmp_path: Path) -> None:
    identifier = create_job(
        client,
        [
            ("files", ("notes.txt", b"Original text")),
            ("files", ("reference.pdf", b"synthetic PDF fixture")),
            ("files", ("reference.docx", b"synthetic Word fixture")),
            ("files", ("reference.png", b"synthetic image fixture")),
        ],
    )
    state = wait(client, identifier)
    assert state["status"] == "awaiting_material_approval", state
    assert state["parsing"]["calls"] == 1
    assert len(state["parsing"]["files"]) == 4
    assert state["parsing"]["files"][0]["text"] == "Original text"
    assert state["parsing"]["files"][1]["status"] == "partial"
    assert state["parsing"]["files"][1]["warnings"]
    assert not (Path(state["path"]) / "state.json").exists()
    response = client.post(
        f"/api/jobs/{identifier}/accept-materials", headers=HEADERS, json={"digest": "stale"}
    )
    assert response.status_code == 409
    # A new app instance can recover the review without calling the parser again.
    client = TestClient(create_app(ROOT / "examples/local-files/config.toml", tmp_path))
    response = client.post(
        f"/api/jobs/{identifier}/accept-materials",
        headers=HEADERS,
        json={"digest": state["parsing_digest"]},
    )
    assert response.status_code == 200
    state = wait(client, identifier)
    assert state["status"] == "awaiting_approval", state
    response = client.post(
        f"/api/jobs/{identifier}/approve",
        headers=HEADERS,
        json={"digest": state["brief_digest"]},
    )
    assert response.status_code == 200
    state = wait(client, identifier)
    assert state["status"] == "delivered", state
    assert state["parsing"]["calls"] == 1
    job = tmp_path / "jobs" / identifier
    assert len(list((job / "parsing").glob("call/attempt.json"))) == 1
    assert (job / "text/1.pdf.md").read_text() == "Synthetic parsed text. Copy exactly."
    assert (
        client.post(
            f"/api/jobs/{identifier}/accept-materials",
            headers=HEADERS,
            json={"digest": state["parsing_digest"]},
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "mode", ["parse-unsupported", "parse-missing", "parse-duplicate", "parse-mutate", "timeout"]
)
def test_failed_parsing_never_starts_workflow(tmp_path: Path, mode: str) -> None:
    import tomli_w

    from build_skills.config import load_config

    config = load_config(ROOT / "examples/local-files/config.toml")
    config.providers[config.roles["prepare"]].command.append(mode)
    path = tmp_path / "config.toml"
    path.write_text(tomli_w.dumps(config.model_dump(exclude_none=True)))
    client = TestClient(create_app(path, tmp_path / "data"))
    identifier = create_job(
        client,
        [("files", ("test.jpg", b"synthetic image fixture"))],
        timeout=0.1 if mode == "timeout" else 600,
    )
    state = wait(client, identifier)
    assert state["status"] == "failed", state
    assert state["error"]
    assert not (Path(state["path"]) / "state.json").exists()
    assert (
        client.post(
            f"/api/jobs/{identifier}/accept-materials", headers=HEADERS, json={"digest": "anything"}
        ).status_code
        == 409
    )
    assert client.get(f"/api/jobs/{identifier}/download").status_code == 409
    assert (
        client.post(f"/api/jobs/{identifier}/resume", headers=HEADERS, json={}).status_code == 409
    )
