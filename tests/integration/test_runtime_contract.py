def test_invalid_template_does_not_consume_call_budget(task_config, cli):
    with task_config.open("a") as handle:
        handle.write('\n[prompts]\nprepare = "{% broken"\n')
    code, state = cli(task_config, "prepare")
    assert code == 2
    assert state["calls"] == 0


def test_file_candidate_does_not_require_json_final_message(task_config, cli):
    task_config.write_text(task_config.read_text().replace('agent.py"]', 'agent.py", "file-only"]'))
    _, state = cli(task_config, "prepare")
    run = state["run"]
    cli(task_config, "approve", "--run", run, "--accept", state["brief_digest"])
    code, state = cli(task_config, "build", "--run", run)
    assert code == 0, state
    assert state["round"] == 1


def test_build_limits_can_be_disabled_independently(task_config, cli):
    with task_config.open("a") as handle:
        handle.write(
            "\n[limits.build]\ntimeout_seconds = 0\nmax_calls = 0\ntotal_seconds = 0\n"
            "\n[limits.execute]\ntimeout_seconds = 0.01\n"
        )
    code, state = cli(task_config, "prepare")
    assert code == 0, state
    run = state["run"]
    cli(task_config, "approve", "--run", run, "--accept", state["brief_digest"])
    code, state = cli(task_config, "build", "--run", run)
    assert code == 0, state
    assert state["usage"]["build"]["calls"] == 1


def test_failed_model_does_not_prevent_other_model_execution(task_config, cli):
    task_config.write_text(
        task_config.read_text().replace('agent.py"]', 'agent.py", "execute-error"]', 1)
    )
    _, state = cli(task_config, "prepare")
    run = state["run"]
    cli(task_config, "approve", "--run", run, "--accept", state["brief_digest"])
    cli(task_config, "build", "--run", run)
    code, state = cli(task_config, "execute", "--run", run)
    assert code == 5, state
    assert {r["model"]: r["status"] for r in state["execution_results"]} == {
        "one": "failed",
        "two": "completed",
    }
    code, state = cli(task_config, "evaluate", "--run", run)
    assert code == 0, state
    assert state["development_passed"] is False


def test_retry_only_failed_cells_and_rejudge_updated_matrix(task_config, cli):
    marker = str(task_config.parent / "first-failure")
    task_config.write_text(
        task_config.read_text().replace('agent.py"]', f'agent.py", "fail-once", "{marker}"]', 1)
    )
    _, state = cli(task_config, "prepare")
    run = state["run"]
    cli(task_config, "approve", "--run", run, "--accept", state["brief_digest"])
    cli(task_config, "build", "--run", run)
    code, state = cli(task_config, "execute", "--run", run)
    assert code == 5, state
    calls = state["calls"]
    code, cached = cli(task_config, "execute", "--run", run)
    assert code == 5 and cached["calls"] == calls
    _, state = cli(task_config, "evaluate", "--run", run)
    assert state["development_passed"] is False
    calls = state["calls"]
    code, state = cli(task_config, "execute", "--run", run, "--retry-failed")
    assert code == 0, state
    assert state["calls"] == calls + 1
    code, state = cli(task_config, "evaluate", "--run", run)
    assert code == 0 and state["development_passed"] is True
    assert state["usage"]["evaluate"]["calls"] == 2


def test_each_model_has_its_own_execution_budget(task_config, cli):
    task_config.write_text(
        task_config.read_text().replace(
            'models = ["one", "two"]', 'models = ["one", "two"]\nrepetitions = 2'
        )
        + "\n[limits.execute]\nmax_calls = 1\n"
    )
    _, state = cli(task_config, "prepare")
    run = state["run"]
    cli(task_config, "approve", "--run", run, "--accept", state["brief_digest"])
    cli(task_config, "build", "--run", run)
    code, state = cli(task_config, "execute", "--run", run)
    assert code == 4, state
    completed = [r["model"] for r in state["execution_results"] if r["status"] == "completed"]
    assert completed == ["one", "two"]
    assert state["usage"]["execute:one"]["calls"] == 1
    assert state["usage"]["execute:two"]["calls"] == 1


def test_one_batch_evaluation_for_complete_model_matrix(task_config, cli):
    _, state = cli(task_config, "prepare")
    run = state["run"]
    cli(task_config, "approve", "--run", run, "--accept", state["brief_digest"])
    cli(task_config, "build", "--run", run)
    cli(task_config, "execute", "--run", run)
    code, state = cli(task_config, "evaluate", "--run", run)
    assert code == 0, state
    assert state["usage"]["evaluate"]["calls"] == 1
    _, cached = cli(task_config, "evaluate", "--run", run)
    assert cached["calls"] == state["calls"]


def test_task_git_commands_stay_in_task_repository(task_config, cli):
    task_config.write_text(
        task_config.read_text()
        .replace('agent.py"]', 'agent.py", "repo-root"]')
        .replace("[execution]", "[execution]\ngit_repository = true")
    )
    _, state = cli(task_config, "prepare")
    run = state["run"]
    cli(task_config, "approve", "--run", run, "--accept", state["brief_digest"])
    cli(task_config, "build", "--run", run)
    code, state = cli(task_config, "execute", "--run", run)
    assert code == 0, state
    assert all(r["status"] == "completed" for r in state["execution_results"])


def test_missing_response_is_not_a_completed_artifact(task_config, cli):
    import json

    task_config.write_text(
        task_config.read_text().replace('agent.py"]', 'agent.py", "missing-response"]')
    )
    code, state = cli(task_config, "prepare")
    assert code == 5, state
    receipt = task_config.parent / "work" / state["run"] / "calls/0001/attempt.json"
    assert json.loads(receipt.read_text())["status"] == "invalid_output"
