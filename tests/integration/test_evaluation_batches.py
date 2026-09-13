"""Large matrices must fit the transport without discarding evidence."""

import json
from pathlib import Path

import pytest

from build_skills.config import load_config
from build_skills.workflow import Workflow
from build_skills.workspace import WorkflowError


def test_large_evaluation_uses_complete_batches_and_reuses_judgments(task_config, cli):
    task_config.write_text(
        task_config.read_text().replace('agent.py"]', 'agent.py", "large-evidence"]')
    )
    _, state = cli(task_config, "prepare")
    run = state["run"]
    cli(task_config, "approve", "--run", run, "--accept", state["brief_digest"])
    for stage in ("build", "execute", "evaluate"):
        code, state = cli(task_config, stage, "--run", run)
        assert code == 0, state
    assert state["usage"]["evaluate"]["calls"] == 2
    workflow = Workflow(load_config(task_config), run)
    workflow.load()
    report = workflow.artifact("development-report-1")
    assert report["passed"]
    requests = []
    for path in workflow.root.glob("calls/*/attempt.json"):
        if json.loads(path.read_text())["stage"] == "evaluate":
            prompt = (path.parent / "prompt.txt").read_text()
            assert len(prompt.encode()) <= 900_000
            assert "x" * 480_000 in prompt
            requests.append(prompt)
    assert len(requests) == 2
    # Simulate interruption after batches were saved, before a report was persisted.
    workflow.state["artifacts"].pop("development-report-1")
    workflow.save()
    (workflow.root / "development-report-1.json").unlink()
    calls = workflow.state["calls"]
    workflow.evaluate()
    assert workflow.state["calls"] == calls


def test_single_oversized_case_uses_complete_local_evidence(task_config):
    workflow = Workflow(load_config(task_config), None)
    execution = {"label": "case-0", "output": "x" * 900_001}
    contexts = workflow.evaluation_contexts(["Check output"], [execution])
    item = contexts[0]["executions"][0]
    assert json.loads(Path(item["evidence_path"]).read_text()) == execution
    assert len(json.dumps(contexts)) < 1000
    Path(item["evidence_path"]).write_text("{}")
    with pytest.raises(WorkflowError, match="证据文件已被修改"):
        workflow.evaluation_contexts(["Check output"], [execution])


def test_agent_reads_large_single_case_from_file(task_config, cli):
    task_config.write_text(
        task_config.read_text().replace('agent.py"]', 'agent.py", "large-single-evidence"]')
    )
    _, state = cli(task_config, "prepare")
    run = state["run"]
    cli(task_config, "approve", "--run", run, "--accept", state["brief_digest"])
    for stage in ("build", "execute", "evaluate"):
        code, state = cli(task_config, stage, "--run", run)
        assert code == 0, state
    assert state["development_passed"]
    assert state["usage"]["evaluate"]["calls"] == 1
    workflow = Workflow(load_config(task_config), run)
    assert len(list((workflow.root / "evaluation-inputs").glob("*.json"))) == 2
