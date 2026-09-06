def test_prepare_requires_approval_and_binds_it_to_brief(task_config, cli):
    code, result = cli(task_config, "loop")
    assert code == 3, result
    run = result["run"]
    assert result["status"] == "awaiting_approval"
    code, status = cli(task_config, "status", "--run", run)
    assert code == 0
    code, result = cli(task_config, "approve", "--run", run, "--accept", status["brief_digest"])
    assert code == 0, result
    assert result["status"] == "approved"
    code, result = cli(task_config, "approve", "--run", run, "--accept", "stale")
    assert code == 2


def test_timeout_retains_failure_and_consumes_call(task_config, cli):
    task_config.write_text(
        task_config.read_text().replace('agent.py"]', 'agent.py", "timeout"]')
        + "\n[limits]\ntimeout_seconds = 0.05\n"
    )
    code, result = cli(task_config, "prepare")
    assert code == 5, result
    assert result["calls"] == 1
    assert result["status"] == "failed"


def test_agent_failure_can_be_retried_without_losing_record(task_config, cli):
    task_config.write_text(task_config.read_text().replace('agent.py"]', 'agent.py", "error"]'))
    code, first = cli(task_config, "prepare")
    assert code == 5
    code, second = cli(task_config, "prepare", "--run", first["run"])
    assert code == 5
    assert second["calls"] == 2
