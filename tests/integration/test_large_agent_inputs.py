"""Native CLI transports must never receive oversized task payloads."""

import json
import sys
from importlib.resources import files
from pathlib import Path

import pytest
from jinja2 import Template

from build_skills.config import canonical
from build_skills.models import BatchJudgment, Brief, Provider, Skill
from build_skills.providers.process import invoke


@pytest.mark.parametrize("kind", ["codex", "qoder"])
@pytest.mark.parametrize("stage", ["prepare", "build", "improve", "evaluate", "execute"])
def test_large_stage_prompt_uses_file_handoff(tmp_path, kind, stage):
    provider = Provider(
        kind=kind,
        model="fixture-model",
        command=[sys.executable, str(Path(__file__).parents[1] / "fixtures/transport.py")],
    )
    cwd = tmp_path / "session"
    cwd.mkdir()
    evidence = tmp_path / "evidence"
    context = {"executions": [{"label": "case-0", "output": "x" * 2_200_000}]}
    schema = {"prepare": Brief, "evaluate": BatchJudgment, "build": Skill, "improve": Skill}.get(
        stage
    )
    schema = schema.model_json_schema() if schema else None
    prompt = Template(files("build_skills.templates").joinpath(stage + ".j2").read_text()).render(
        goal="Copy text", task="x" * 2_200_000, data=canonical(context), schema=canonical(schema)
    )
    if stage == "execute":
        (cwd / ".skill").mkdir()
        (cwd / ".skill/SKILL.md").write_text("Copy exactly.")
        (cwd / "input.txt").write_text("hello")
    result = invoke(provider, stage, prompt, context, schema, cwd, evidence, 10)
    assert result
    assert (evidence / "prompt.txt").read_text() == prompt
    assert (evidence / "transport-prompt.txt").stat().st_size < 10_000
    receipt = json.loads((evidence / "attempt.json").read_text())
    assert receipt["prompt_transport"] == "file"
    assert receipt["status"] == "completed"
