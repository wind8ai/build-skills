"""Selected files retain identity across folder, HTTP and frozen Git sources."""

import functools
import json
import subprocess
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from build_skills.web.server import create_app
from build_skills.web.sources import fetch_git, select_files, validate_url

HEADERS = {"X-Build-Skills": "local"}
CONFIG = Path(__file__).resolve().parents[2] / "examples/web/config.toml"


def test_folder_paths_and_traversal(tmp_path):
    client = TestClient(create_app(CONFIG, tmp_path / "data"))
    files = [("files", ("notes.md", b"first")), ("files", ("notes.md", b"second"))]
    response = client.post(
        "/api/materials",
        headers=HEADERS,
        files=files,
        data={"paths": json.dumps(["a/notes.md", "b/notes.md"])},
    )
    assert response.status_code == 200, response.text
    assert [f["name"] for f in response.json()["files"]] == ["a/notes.md", "b/notes.md"]
    for paths in [["../a.md", "b.md"], ["same.md", "same.md"], ["/root/a.md", "b.md"]]:
        assert (
            client.post(
                "/api/materials", headers=HEADERS, files=files, data={"paths": json.dumps(paths)}
            ).status_code
            == 400
        )


def test_direct_http_file_freezes_selected_contents(tmp_path):
    (tmp_path / "notes.md").write_text("synthetic source")
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/notes.md"
        with pytest.raises(ValueError):
            validate_url(url)
        client = TestClient(create_app(CONFIG, tmp_path / "data", allow_local_sources=True))
        response = client.post(
            "/api/sources/url", headers=HEADERS, json={"kind": "url", "url": url}
        )
        assert response.status_code == 200, response.text
        source = response.json()
        response = client.post(
            f"/api/sources/{source['id']}/select", headers=HEADERS, json={"files": ["notes.md"]}
        )
        assert response.status_code == 200, response.text
        assert response.json()["files"][0]["text"] == "synthetic source"
        (tmp_path / "data/sources" / source["id"] / "download").write_text("changed")
        assert (
            client.post(
                f"/api/sources/{source['id']}/select", headers=HEADERS, json={"files": ["notes.md"]}
            ).status_code
            == 400
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_git_tree_selection_freezes_commit_without_checkout(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    (repo / "docs").mkdir()
    (repo / "docs/a.md").write_text("selected docs")
    (repo / "b.md").write_text("not selected")
    (repo / ".env").write_text("synthetic secret")
    (repo / "alias.md").symlink_to("b.md")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.test",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    # Keep production URL and protocol checks; replace only the test transport with a local fixture.
    monkeypatch.setattr("build_skills.web.sources.validate_url", lambda url, **kwargs: url)
    actual_popen = subprocess.Popen

    def local_clone(command, **kwargs):
        if "clone" not in command:
            return actual_popen(command, **kwargs)
        assert "core.hooksPath=/dev/null" in command
        assert "http.followRedirects=false" in command
        command = [
            "protocol.file.allow=always" if c == "protocol.file.allow=never" else c for c in command
        ]
        command[-2] = repo.as_uri()
        return actual_popen(command, **kwargs)

    monkeypatch.setattr("build_skills.web.sources.subprocess.Popen", local_clone)
    root = tmp_path / "data"
    folder = root / "sources/fixture"
    folder.mkdir(parents=True)
    source = fetch_git(folder, "https://fixture.example/repo.git", "")
    (folder / "source.json").write_text(json.dumps(source))
    assert len(source["commit"]) == 40
    entries = {f["path"]: f for f in source["files"]}
    assert not entries[".env"]["supported"]
    assert not entries["alias.md"]["supported"]
    result = select_files(root, "fixture", ["docs/a.md"])
    assert len(result["files"]) == 1 and result["files"][0]["text"] == "selected docs"
    assert result["origin"]["commit"] == source["commit"]
    assert not (folder / "repository/docs/a.md").exists()


def test_source_origin_survives_parsing_and_confirmation(tmp_path):
    from build_skills.config import digest, load_config
    from build_skills.web.materials import accept_materials, parse_materials, record_upload
    from build_skills.workspace import read_json, write_json

    job = tmp_path / "job"
    (job / "inputs").mkdir(parents=True)
    (job / "text").mkdir()
    source = job / "inputs/0.md"
    source.write_text("Synthetic public frozen material")
    origin = {"kind": "git", "url": "https://example.test/repo.git", "commit": "a" * 40}
    write_json(job / "sources.json", [record_upload(source, "docs/notes.md") | {"origin": origin}])
    parse_materials(job, load_config(CONFIG), 5)
    parsing = read_json(job / "parsing/result.json")
    assert parsing["files"][0]["origin"] == origin
    accept_materials(job, digest(parsing))
    assert read_json(job / "text/sources.json")[0]["origin"] == origin
