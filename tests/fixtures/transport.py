"""Exercise provider argument and response contracts without a real CLI."""

import json
import subprocess
import sys
from pathlib import Path

args = sys.argv[1:]
if "exec" in args:
    assert "--model" in args and "--ephemeral" in args and "--sandbox" in args
    assert "--output-schema" not in args
    assert Path(args[args.index("--cd") + 1]) == Path.cwd()
    prompt = sys.stdin.read()
else:
    assert "--print" in args and "--no-session-persistence" in args
    assert Path(args[args.index("--cwd") + 1]) == Path.cwd()
    prompt = args[-1]
marker = "The final chat message can be a short completion summary:\n"
schema = json.loads(prompt.rsplit(marker, 1)[1]) if marker in prompt else None
stage = {"Brief": "prepare", "BatchJudgment": "evaluate"}.get(
    schema["title"] if schema else "",
    "build" if "skill/SKILL.md" in prompt and "Create" in prompt else "execute",
)
result = subprocess.run(
    [sys.executable, str(Path(__file__).with_name("agent.py"))],
    input=json.dumps(
        {
            "stage": stage,
            "context": json.loads(prompt.split("\nWrite response.json")[0].rsplit("\n", 1)[1])
            if stage == "evaluate"
            else {},
        }
    ),
    text=True,
    capture_output=True,
    check=True,
)
if "exec" in args:
    Path(args[args.index("--output-last-message") + 1]).write_text(result.stdout)
    print('{"type":"fixture.event"}')
else:
    print(result.stdout, end="")
