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


def test_script_referenced_in_command_block_is_a_package_resource(task_config, cli):
    task_config.write_text(
        task_config.read_text().replace('agent.py"]', 'agent.py", "command-resource"]')
    )
    _, state = cli(task_config, "prepare")
    run = state["run"]
    cli(task_config, "approve", "--run", run, "--accept", state["brief_digest"])
    code, result = cli(task_config, "build", "--run", run)
    assert code == 0, result


def test_recover_validated_files_without_another_model_call(task_config, cli):
    import json
    from pathlib import Path

    task_config.write_text(
        task_config.read_text().replace('agent.py"]', 'agent.py", "repair-output"]')
    )
    _, state = cli(task_config, "prepare")
    run = state["run"]
    cli(task_config, "approve", "--run", run, "--accept", state["brief_digest"])
    code, state = cli(task_config, "build", "--run", run)
    assert code == 2 and state["calls"] == 2
    receipt = task_config.parent / "work" / run / "calls/0002/attempt.json"
    data = json.loads(receipt.read_text())
    path = Path(data["cwd"]) / "skill/SKILL.md"
    path.write_text("---\nname: copy\ndescription: Copy files.\n---\nCopy exactly.\n")
    code, state = cli(task_config, "build", "--run", run, "--recover-call", "2")
    assert code == 0, state
    assert state["round"] == 1 and state["calls"] == 2
    assert json.loads(receipt.read_text())["recovered"] is True


def test_failed_process_cannot_be_promoted_by_recovery(task_config, cli):
    task_config.write_text(
        task_config.read_text().replace('agent.py"]', 'agent.py", "partial-build"]')
    )
    _, state = cli(task_config, "prepare")
    run = state["run"]
    cli(task_config, "approve", "--run", run, "--accept", state["brief_digest"])
    assert cli(task_config, "build", "--run", run)[0] == 5
    code, state = cli(task_config, "build", "--run", run, "--recover-call", "2")
    assert code == 2
    assert state["round"] == 0


def test_improve_recovery_rejects_changed_context_with_fixed_prompt(task_config, cli):
    task_config.write_text(
        task_config.read_text().replace('agent.py"]', 'agent.py", "improve"]')
        + '\n[prompts]\nimprove = "Fixed instruction"\n'
    )
    _, state = cli(task_config, "prepare")
    run = state["run"]
    cli(task_config, "approve", "--run", run, "--accept", state["brief_digest"])
    for stage in ("build", "execute", "evaluate", "improve"):
        code, state = cli(task_config, stage, "--run", run)
        assert code == 0, state
    previous = state["calls"]
    for stage in ("execute", "evaluate"):
        assert cli(task_config, stage, "--run", run)[0] == 0
    code, state = cli(task_config, "improve", "--run", run, "--recover-call", str(previous))
    assert code == 2
    assert "context does not match" in state["error"]
    assert state["round"] == 2


def test_configured_python_keeps_its_virtual_environment(task_config, cli):
    import sys

    assert sys.prefix != sys.base_prefix
    task_config.write_text(
        task_config.read_text().replace('agent.py"]', f'agent.py", "venv-prefix", "{sys.prefix}"]')
    )
    code, result = cli(task_config, "prepare")
    assert code == 0, result


def test_revalidate_existing_skill_without_regeneration(task_config, cli):
    source = task_config.parent / "existing-skill"
    source.mkdir()
    content = "---\nname: copy\ndescription: Copy files.\n---\nCopy input.txt to output.txt.\n"
    (source / "SKILL.md").write_text(content)
    _, state = cli(task_config, "prepare")
    run = state["run"]
    cli(task_config, "approve", "--run", run, "--accept", state["brief_digest"])
    calls = state["calls"]
    code, state = cli(task_config, "build", "--run", run, "--from-skill", str(source))
    assert code == 0, state
    assert state["calls"] == calls
    assert state["candidate_source"]["kind"] == "imported"
    assert (source / "SKILL.md").read_text() == content
    code, state = cli(task_config, "loop", "--run", run)
    assert code == 0 and state["status"] == "delivered"
