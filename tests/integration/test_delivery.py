import json
from pathlib import Path


def test_cannot_deliver_unverified_skill(task_config, cli):
    _, state = cli(task_config, "prepare")
    run = state["run"]
    cli(task_config, "approve", "--run", run, "--accept", state["brief_digest"])
    cli(task_config, "build", "--run", run)
    code, result = cli(task_config, "deliver", "--run", run)
    assert code != 0
    assert "delivery" not in result


def test_heldout_failure_does_not_allow_improvement_on_same_set(task_config, cli):
    _, state = cli(task_config, "prepare")
    brief_path = Path(state["brief_path"])
    brief = json.loads(brief_path.read_text())
    brief["holdout"][0]["checks"][0]["equals"] = "impossible"
    brief_path.write_text(json.dumps(brief))
    _, state = cli(task_config, "status", "--run", state["run"])
    run = state["run"]
    cli(task_config, "approve", "--run", run, "--accept", state["brief_digest"])
    code, result = cli(task_config, "loop", "--run", run)
    assert code == 4, result
    assert result["holdout_passed"] is False
    assert cli(task_config, "improve", "--run", run)[0] == 2


def test_feedback_is_available_to_next_run(task_config, cli):
    _, state = cli(task_config, "prepare")
    feedback = task_config.parent / "feedback.md"
    feedback.write_text("Preserve blank lines.")
    assert cli(task_config, "feedback", "--run", state["run"], "--file", str(feedback))[0] == 0
    _, next_state = cli(task_config, "prepare")
    assert next_state["run"] != state["run"]
