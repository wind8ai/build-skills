def test_codex_and_qoder_transport_contracts(task_config, cli):
    text = task_config.read_text().replace("agent.py", "transport.py")
    text = text.replace('kind = "command"', 'kind = "codex"\nmodel = "fixture-model"', 1)
    text = text.replace('kind = "command"', 'kind = "qoder"\nmodel = "fixture-model"', 1)
    task_config.write_text(text)
    _, state = cli(task_config, "prepare")
    run = state["run"]
    cli(task_config, "approve", "--run", run, "--accept", state["brief_digest"])
    code, result = cli(task_config, "loop", "--run", run)
    assert code == 0, result
    assert result["status"] == "delivered"


def test_qoder_headless_uses_auto_review_and_structured_result(tmp_path):
    from build_skills.models import Provider
    from build_skills.providers.qoder import arguments

    args = arguments(Provider(kind="qoder", command=["qodercli"], model="test"), tmp_path, "task")
    assert args[args.index("--permission-mode") + 1] == "auto"
    assert args[args.index("--output-format") + 1] == "json"


def test_permission_denial_stops_loop_instead_of_improving(task_config, cli):
    import json
    import sys

    script = task_config.parent / "denied.py"
    script.write_text(
        "import json\nprint(json.dumps("
        + repr(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": "Copy was not authorized",
                "permission_denials": [{"tool_name": "Bash"}],
            }
        )
        + "))\n"
    )
    original = task_config.read_text()
    # Keep the builder fixture; use denied Qoder only for execution.
    original += (
        '\n[providers.denied]\nkind="qoder"\nmodel="test"\ncommand='
        + json.dumps([sys.executable, str(script)])
        + "\n"
    )
    task_config.write_text(original.replace('models = ["one", "two"]', 'models = ["denied"]'))
    _, state = cli(task_config, "prepare")
    run = state["run"]
    cli(task_config, "approve", "--run", run, "--accept", state["brief_digest"])
    code, state = cli(task_config, "loop", "--run", run)
    assert code == 5, state
    assert state["round"] == 1
    assert "improve" not in state["usage"]
    assert state["execution_results"][0]["status"] == "failed"
    receipt = json.loads(
        (task_config.parent / "work" / run / "calls/0003/attempt.json").read_text()
    )
    assert receipt["status"] == "permission_denied"
