def test_same_skill_runs_on_both_providers_and_has_evidence(task_config, cli):
    _, state = cli(task_config, "prepare")
    run = state["run"]
    assert cli(task_config, "approve", "--run", run, "--accept", state["brief_digest"])[0] == 0
    for stage in ("build", "execute", "evaluate"):
        code, state = cli(task_config, stage, "--run", run)
        assert code == 0, state
    assert state["development_passed"] is True
    assert state["execution_count"] == 2
    assert state["status"] != "delivered"


def test_judge_can_detect_source_mutation_from_input_snapshot(task_config, cli):
    task_config.write_text(
        task_config.read_text().replace('agent.py"]', 'agent.py", "mutate-source"]')
    )
    _, state = cli(task_config, "prepare")
    run = state["run"]
    cli(task_config, "approve", "--run", run, "--accept", state["brief_digest"])
    for stage in ("build", "execute", "evaluate"):
        code, state = cli(task_config, stage, "--run", run)
        assert code == 0, state
    assert state["development_passed"] is False
