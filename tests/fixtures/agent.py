"""Deterministic external-process fixture. This is not a model."""

import json
import sys
import time
from pathlib import Path

request = json.loads(sys.stdin.read())
stage = request["stage"]
mode = sys.argv[1] if len(sys.argv) > 1 else "normal"
if mode == "timeout":
    time.sleep(5)
if mode == "error":
    sys.exit(7)
if mode == "fail-once" and stage == "execute":
    marker = Path(sys.argv[2])
    if not marker.exists():
        marker.write_text("attempted")
        sys.exit(7)
if mode == "execute-error" and stage == "execute":
    sys.exit(7)
if stage == "prepare":

    def scenario(name, content):
        return {
            "id": name,
            "task": "Copy input.txt to output.txt.",
            "files": {"input.txt": content},
            "checks": [{"path": "output.txt", "equals": content}],
        }

    result = {
        "scope": "Copy local text files",
        "criteria": ["Exact output"],
        "questions": [],
        "sources": [
            {
                "reference": "input",
                "finding": "Copy text",
                "status": "provided",
                "evidence": "User material",
            }
        ],
        "development": [scenario("copy", "hello")],
        "holdout": [scenario("new", "new content")],
    }
elif stage in ("build", "improve"):
    result = {
        "files": {
            "SKILL.md": (
                "---\nname: copy\ndescription: Copy text files when requested.\n---\n"
                + ("broken" if mode == "improve" and stage == "build" else "Copy exactly.")
            )
        }
    }
elif stage == "execute":
    if mode == "repo-root":
        import subprocess

        assert (
            Path(
                subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
            )
            == Path.cwd()
        )
    Path("output.txt").write_text(
        "wrong"
        if "broken" in Path(".skill/SKILL.md").read_text()
        else Path("input.txt").read_text()
    )
    result = {"text": "Copied input.txt to output.txt."}
else:
    result = {
        "results": [
            {
                "label": item["label"],
                "score": 1.0,
                "passed": True,
                "reason": "Exact copy",
                "evidence": ["output.txt"],
            }
            for item in request["context"]["executions"]
        ]
    }
if stage == "build" and mode == "alias":
    result["files"]["./SKILL.md"] = "not a skill"
if stage == "build" and mode == "casealias":
    result["files"]["SKILL.md"] += "\n[resource](skill.md)"
    result["files"]["skill.md"] = "not a skill"
if stage == "build" and mode == "garbage":
    result["files"]["scratch.log"] = "unused"
if stage in {"build", "improve"}:
    for name, content in result["files"].items():
        if name.startswith("./") or name == "skill.md":
            # A filesystem cannot retain path aliases; write the conflicting bytes.
            name = "SKILL.md"
        target = Path("skill") / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
elif stage != "execute" and mode != "missing-response":
    Path("response.json").write_text(json.dumps(result))
print("Completed fixture operation.")
