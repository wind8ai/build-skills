"""Generated Python caches and binary task outputs must not crash collection."""

import pytest

from build_skills.evaluation import observe
from build_skills.models import Scenario
from build_skills.workspace import read_skill_directory


def test_skill_collection_excludes_generated_bytecode(tmp_path):
    (tmp_path / "SKILL.md").write_text(
        "---\nname: copy\ndescription: Copy files.\n---\nCopy exactly.\n"
    )
    cache = tmp_path / "scripts/__pycache__"
    cache.mkdir(parents=True)
    (cache / "copy.cpython-314.pyc").write_bytes(b"0123456789\xa6")
    assert set(read_skill_directory(tmp_path).files) == {"SKILL.md"}


@pytest.mark.parametrize("size", [11, 1_000_001])
def test_binary_exists_check_does_not_require_text(tmp_path, size):
    (tmp_path / "result.bin").write_bytes(b"\xa6" * size)
    scenario = Scenario(id="binary", task="Write a binary file", checks=[{"path": "result.bin"}])
    result = observe(tmp_path, scenario)
    assert result["checks"][0]["passed"] is True
    assert result["files"]["result.bin"] == "[binary file]"


def test_binary_cannot_pass_text_check(tmp_path):
    (tmp_path / "result.bin").write_bytes(b"\xa6")
    scenario = Scenario(
        id="binary", task="Write text", checks=[{"path": "result.bin", "contains": "x"}]
    )
    result = observe(tmp_path, scenario)
    assert result["checks"][0]["passed"] is False


def test_non_cache_binary_skill_file_has_actionable_error(tmp_path):
    (tmp_path / "SKILL.md").write_bytes(b"\xa6")
    with pytest.raises(ValueError, match="SKILL.md.*UTF-8"):
        read_skill_directory(tmp_path)


def test_bytecode_does_not_break_cli_build_or_delivery(task_config, cli):
    import json
    from pathlib import Path

    task_config.write_text(task_config.read_text().replace('agent.py"]', 'agent.py", "bytecode"]'))
    _, state = cli(task_config, "prepare")
    run = state["run"]
    assert cli(task_config, "approve", "--run", run, "--accept", state["brief_digest"])[0] == 0
    code, state = cli(task_config, "loop", "--run", run)
    assert code == 0 and state["status"] == "delivered", state
    delivery = Path(state["delivery"])
    assert not list(delivery.rglob("*.pyc"))
    assert (delivery / "skill/scripts/helper.py").is_file()
    root = delivery.parent
    receipt = json.loads((root / "calls/0002/attempt.json").read_text())
    # Raw call evidence is preserved, even though it is excluded from the package.
    assert list(Path(receipt["cwd"]).rglob("*.pyc"))
