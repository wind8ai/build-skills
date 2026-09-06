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
