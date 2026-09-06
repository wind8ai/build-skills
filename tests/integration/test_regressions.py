import json
from pathlib import Path


def test_duplicate_scenario_is_rejected_during_review(task_config, cli):
    _, state = cli(task_config, "prepare")
    path = Path(state["brief_path"])
    brief = json.loads(path.read_text())
    brief["development"].append(brief["development"][0])
    path.write_text(json.dumps(brief))
    code, result = cli(task_config, "status", "--run", state["run"])
    assert code == 2, result


def test_model_and_scenario_names_cannot_collide(task_config, cli):
    task_config.write_text(task_config.read_text().replace("one", "a").replace("two", "a-b"))
    _, state = cli(task_config, "prepare")
    run = state["run"]
    path = Path(state["brief_path"])
    brief = json.loads(path.read_text())
    first = brief["development"][0]
    first["id"] = "b-c"
    second = json.loads(json.dumps(first))
    second["id"] = "c"
    second["checks"][0]["equals"] = "impossible"
    brief["development"].append(second)
    path.write_text(json.dumps(brief))
    _, state = cli(task_config, "status", "--run", run)
    cli(task_config, "approve", "--run", run, "--accept", state["brief_digest"])
    cli(task_config, "build", "--run", run)
    code, state = cli(task_config, "execute", "--run", run)
    assert code == 0, state
    assert state["calls"] == 6  # prepare + build + all four matrix cells


def test_delivery_preserves_model_names_and_evidence(task_config, cli):
    task_config.write_text(
        task_config.read_text().replace('kind = "command"', 'kind = "command"\nmodel = "demo"')
    )
    _, state = cli(task_config, "prepare")
    run = state["run"]
    cli(task_config, "approve", "--run", run, "--accept", state["brief_digest"])
    code, state = cli(task_config, "loop", "--run", run)
    assert code == 0, state
    report = json.loads((Path(state["delivery"]) / "report.json").read_text())
    assert report["models"]["one"]["model"] == "demo"
    assert report["brief"]["sources"]
    assert report["holdout_executions"][0]["observation"]["files"]["output.txt"] == "new content"


def test_skill_alias_and_unreferenced_resources_are_rejected(task_config, cli):
    original = task_config.read_text()
    for mode in ("alias", "casealias", "garbage"):
        task_config.write_text(original.replace('agent.py"]', f'agent.py", "{mode}"]'))
        _, state = cli(task_config, "prepare")
        run = state["run"]
        cli(task_config, "approve", "--run", run, "--accept", state["brief_digest"])
        code, result = cli(task_config, "build", "--run", run)
        assert code == 2, result
        assert result["round"] == 0
