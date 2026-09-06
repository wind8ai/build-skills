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
    Path("output.txt").write_text(
        "wrong"
        if "broken" in Path(".skill/SKILL.md").read_text()
        else Path("input.txt").read_text()
    )
    result = {"text": "Copied input.txt to output.txt."}
else:
    result = {"score": 1.0, "passed": True, "reason": "Exact copy", "evidence": ["output.txt"]}
if stage == "build" and mode == "alias":
    result["files"]["./SKILL.md"] = "not a skill"
if stage == "build" and mode == "casealias":
    result["files"]["SKILL.md"] += "\n[resource](skill.md)"
    result["files"]["skill.md"] = "not a skill"
if stage == "build" and mode == "garbage":
    result["files"]["scratch.log"] = "unused"
print(json.dumps(result))
