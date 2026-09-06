def test_loop_delivers_and_resuming_does_not_repeat_calls(task_config, cli):
    _, state = cli(task_config, "loop")
    run = state["run"]
    cli(task_config, "approve", "--run", run, "--accept", state["brief_digest"])
    code, state = cli(task_config, "loop", "--run", run)
    assert code == 0, state
    assert state["status"] == "delivered"
    calls = state["calls"]
    code, state = cli(task_config, "loop", "--run", run)
    assert code == 0, state
    assert state["calls"] == calls


def test_budget_stops_without_successful_delivery(task_config, cli):
    task_config.write_text(
        task_config.read_text().replace(
            'models = ["one", "two"]', 'models = ["one", "two"]\nrepetitions = 2'
        )
    )
    with task_config.open("a") as handle:
        handle.write("\n[limits.execute]\nmax_calls = 1\n")
    _, state = cli(task_config, "loop")
    cli(task_config, "approve", "--run", state["run"], "--accept", state["brief_digest"])
    code, result = cli(task_config, "loop", "--run", state["run"])
    assert code == 4, result
    assert result["status"] == "unmet"
    assert "delivery" not in result


def test_material_change_cannot_reuse_approval(task_config, cli):
    _, state = cli(task_config, "prepare")
    (task_config.parent / "material.md").write_text("Different instructions")
    code, result = cli(
        task_config, "approve", "--run", state["run"], "--accept", state["brief_digest"]
    )
    assert code == 2
    assert "Materials changed" in result["error"]


def test_loop_improves_failed_candidate_before_verifying(task_config, cli):
    task_config.write_text(task_config.read_text().replace('agent.py"]', 'agent.py", "improve"]'))
    _, state = cli(task_config, "prepare")
    run = state["run"]
    cli(task_config, "approve", "--run", run, "--accept", state["brief_digest"])
    code, result = cli(task_config, "loop", "--run", run)
    assert code == 0, result
    assert result["round"] == 2
    assert result["status"] == "delivered"
