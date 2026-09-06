import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def task_config(tmp_path):
    material = tmp_path / "material.md"
    material.write_text("Copy text files exactly.")
    agent = Path(__file__).parent / "fixtures/agent.py"
    path = tmp_path / "config.toml"
    path.write_text(f"""name = "copy"
goal = "Make a reliable copy skill"
materials = ["material.md"]
workspace = "work"
[providers.one]
kind = "command"
command = {json.dumps([sys.executable, str(agent.resolve())])}
[providers.two]
kind = "command"
command = {json.dumps([sys.executable, str(agent.resolve())])}
[roles]
prepare = "one"
build = "one"
evaluate = "one"
improve = "one"
[execution]
models = ["one", "two"]
""")
    return path


@pytest.fixture
def cli():
    def invoke(config, command, *args):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "build_skills",
                command,
                "--config",
                str(config),
                "--json",
                *args,
            ],
            capture_output=True,
            text=True,
        )
        return result.returncode, json.loads(result.stdout) if result.stdout else result.stderr

    return invoke
