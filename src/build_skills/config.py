"""Load reusable templates and task-specific configuration."""

import hashlib
import json
import shutil
import tomllib
from pathlib import Path
from typing import Any

from pydantic import Field

from build_skills.models import Document, Execution, Limits, Provider, Quality


class Config(Document):
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    goal: str = Field(min_length=1)
    materials: list[str] = Field(min_length=1)
    workspace: str
    providers: dict[str, Provider]
    roles: dict[str, str]
    execution: Execution
    limits: Limits = Field(default_factory=Limits)
    quality: Quality = Field(default_factory=Quality)
    prompts: dict[str, str] = Field(default_factory=dict)

    def digest(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


def load_config(path: Path) -> Config:
    path = path.resolve()
    data = tomllib.loads(path.read_text())
    template = data.pop("template", None)
    template_dir = path.parent
    if template:
        template_dir = (path.parent / template).resolve().parent
        base = tomllib.loads((path.parent / template).read_text())
        if "template" in base:
            raise ValueError("Nested templates are not supported")
        data = base | data
    config = Config.model_validate(data)
    root = Path(config.workspace)
    root = (path.parent / root).resolve()
    # Only a dedicated development directory may be used inside any framework checkout.
    for parent in [path.parent, *path.parents, Path.cwd(), *Path.cwd().parents]:
        if (parent / "src/build_skills").is_dir():
            if root.is_relative_to(parent) and not root.is_relative_to(parent / ".build-skills"):
                raise ValueError("Use .build-skills/ or an external workspace")
            if parent.is_relative_to(root):
                raise ValueError("Workspace cannot contain the framework checkout")
    config.workspace = str(root)
    config.materials = [str((path.parent / item).resolve()) for item in config.materials]
    for item in config.materials:
        source = Path(item)
        if not source.exists():
            raise ValueError(f"Material does not exist: {source}")
        if source.is_relative_to(root) or root.is_relative_to(source):
            raise ValueError("Materials and workspace must not overlap")
    required = {"prepare", "build", "evaluate", "improve"}
    if set(config.roles) != required:
        raise ValueError(f"roles must contain exactly {sorted(required)}")
    if set(config.prompts) - (required | {"execute"}):
        raise ValueError("Unknown prompt stage")
    if config.execution.git_repository and not shutil.which("git"):
        raise ValueError("execution.git_repository requires Git")
    references = [*config.roles.values(), *config.execution.models]
    if any(ref not in config.providers for ref in references):
        raise ValueError("Unknown provider reference")
    if len(set(config.execution.models)) != len(config.execution.models):
        raise ValueError("Duplicate execution model references")
    for provider in config.providers.values():
        provider.command = [
            arg.replace("{config_dir}", str(path.parent)).replace(
                "{template_dir}", str(template_dir)
            )
            for arg in provider.command
        ]
        executable = provider.command[0]
        if "/" in executable:
            provider.command[0] = str((path.parent / executable).resolve())
        if not shutil.which(provider.command[0]):
            raise ValueError(f"Executable unavailable: {provider.command[0]}")
        if provider.kind != "command" and not provider.model:
            raise ValueError("Real providers require an explicit model")
    return config


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()
