"""Task files and deterministic observations for model judgments."""

from pathlib import Path
from typing import Any

from build_skills.models import Scenario, Skill
from build_skills.workspace import safe_path


def materialize(root: Path, values: dict[str, str]) -> None:
    for name, content in values.items():
        target = safe_path(root, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)


def stage_task(root: Path, scenario: Scenario, skill: Skill) -> None:
    root.mkdir(parents=True, exist_ok=False)
    if any(name.split("/")[0].startswith(".") for name in scenario.files):
        raise ValueError("Scenario cannot overwrite hidden control files")
    materialize(root, scenario.files)
    materialize(root / ".skill", skill.files)


def observe(root: Path, scenario: Scenario) -> dict[str, Any]:
    checks = []
    for check in scenario.checks:
        target = safe_path(root, check.path)
        ok = target.is_file() and target.stat().st_size <= 1_000_000
        content = target.read_text() if ok else None
        if check.equals is not None:
            ok = ok and content == check.equals
        if check.contains is not None:
            ok = ok and content is not None and check.contains in content
        checks.append({"path": check.path, "passed": bool(ok)})
    outputs = {}
    size = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Execution produced a symlink; refusing to follow it")
        if not path.is_file() or ".skill" in path.relative_to(root).parts:
            continue
        size += path.stat().st_size
        if size > 5_000_000:
            raise ValueError("Execution evidence exceeds 5 MB")
        try:
            outputs[str(path.relative_to(root))] = path.read_text()
        except UnicodeDecodeError:
            outputs[str(path.relative_to(root))] = "[binary file]"
    return {"checks": checks, "files": outputs}
