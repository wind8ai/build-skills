"""Run documents, guarded paths and atomic writes."""

import fcntl
import json
import re
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml

from build_skills.config import canonical
from build_skills.models import Skill


class WorkflowError(Exception):
    def __init__(self, message: str, code: int = 5):
        super().__init__(message)
        self.code = code


def safe_path(root: Path, name: str) -> Path:
    part = Path(name)
    if (
        not name
        or str(part) != name
        or name == "."
        or part.is_absolute()
        or ".." in part.parts
        or "\\" in name
    ):
        raise ValueError(f"Unsafe relative path: {name}")
    target = root / part
    if not target.resolve().is_relative_to(root.resolve()) or target.is_symlink():
        raise ValueError(f"Path escapes workspace: {name}")
    return target


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    if temporary.is_symlink() or path.is_symlink():
        raise ValueError("Symlink document refused")
    temporary.write_text(canonical(value))
    temporary.replace(path)


def read_json(path: Path) -> Any:
    if path.is_symlink():
        raise ValueError("Symlink document refused")
    return json.loads(path.read_text())


@contextmanager
def locked(path: Path) -> Iterator[None]:
    path.mkdir(parents=True, exist_ok=True)
    lock = path / ".lock"
    if lock.is_symlink():
        raise ValueError("Symlink lock refused")
    with lock.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise WorkflowError("Run is already active", 5) from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def snapshot(paths: list[str]) -> dict[str, str]:
    files: dict[str, str] = {}
    for index, item in enumerate(paths):
        source = Path(item)
        if source.is_symlink():
            raise ValueError("Symlink materials are unsupported")
        for path in sorted(source.rglob("*")) if source.is_dir() else [source]:
            if path.is_symlink():
                raise ValueError("Symlink materials are unsupported")
            if not path.is_file():
                continue
            if path.stat().st_size > 1_000_000:
                raise ValueError("Material exceeds 1 MB; split it before importing")
            name = str(path.relative_to(source)) if source.is_dir() else path.name
            files[f"{index}/{name}"] = path.read_text()
    if not files or sum(len(v.encode()) for v in files.values()) > 5_000_000:
        raise ValueError("Materials must be nonempty and at most 5 MB")
    return files


def validate_skill(value: Any) -> Skill:
    skill = Skill.model_validate(value)
    if not skill.files or "SKILL.md" not in skill.files:
        raise ValueError("Skill must contain SKILL.md")
    normalized = [unicodedata.normalize("NFC", name).casefold() for name in skill.files]
    if len(set(normalized)) != len(normalized):
        raise ValueError("Skill paths conflict on case-insensitive filesystems")
    for name in skill.files:
        safe_path(Path("/skill"), name)
        if name.split("/")[0] in {".git", ".agents", ".env"}:
            raise ValueError("Reserved skill resource path")
    text = skill.files["SKILL.md"]
    parts = text.split("---", 2)
    if len(parts) != 3 or parts[0].strip():
        raise ValueError("SKILL.md requires YAML frontmatter")
    try:
        front = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        raise ValueError("Invalid Skill frontmatter") from exc
    if not isinstance(front, dict) or not all(
        isinstance(front.get(key), str) and front[key].strip() for key in ("name", "description")
    ):
        raise ValueError("Skill name and description must be nonempty strings")
    references: dict[str, set[str]] = {}
    for filename, body in skill.files.items():
        references[filename] = set()
        if not filename.endswith(".md"):
            continue
        for link in re.findall(r"\]\(([^)\s]+)\)", body):
            if "://" in link or link.startswith("#"):
                continue
            target = str(Path(filename).parent / link.split("#")[0])
            safe_path(Path("/skill"), target)
            references[filename].add(target)
            if target not in skill.files:
                raise ValueError(f"Missing referenced resource: {target}")
    reached = set()
    pending = ["SKILL.md"]
    while pending:
        current = pending.pop()
        if current not in reached:
            reached.add(current)
            pending.extend(references.get(current, set()))
    if reached != set(skill.files):
        raise ValueError("Every resource must be linked from SKILL.md or a linked Markdown file")
    return skill
