"""Translate the two Web model responsibilities to immutable CLI configuration."""

import tomllib
from pathlib import Path
from typing import Any

from pydantic import Field

from build_skills.config import Config, load_config
from build_skills.models import Document, Provider
from build_skills.workspace import read_json


class ModelChoice(Document):
    provider: str
    model: str = ""
    reasoning_effort: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]*$")


class ModelDefaults(Document):
    builder: ModelChoice
    executors: list[ModelChoice] = Field(min_length=1, max_length=20)
    max_rounds: int = Field(ge=1, le=100)
    repetitions: int = Field(ge=1, le=20)
    minimum_score: float = Field(ge=0, le=1)
    agent_timeout_seconds: float = Field(default=600, gt=0, le=7200, allow_inf_nan=False)
    parsing_timeout_seconds: float = Field(default=600, gt=0, le=7200, allow_inf_nan=False)


class Settings(ModelDefaults):
    material: str
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    goal: str = Field(min_length=1)


def web_base(path: Path | None, root: Path) -> Config:
    if path is not None:
        return load_config(path)
    data = tomllib.loads(Path(__file__).with_name("defaults.toml").read_text())
    # Uploaded inputs replace materials before any workflow or filesystem validation.
    return Config.model_validate(
        data
        | {
            "name": "new-skill",
            "goal": "根据上传材料构建可验证的 Skill。",
            "materials": [str(root / "uploads")],
            "workspace": str(root / "runs"),
        }
    )


def choice(base: Config, name: str) -> ModelChoice:
    provider = base.providers[name]
    return ModelChoice(
        provider=name, model=provider.model, reasoning_effort=provider.reasoning_effort
    )


def resolve(base: Config, selected: ModelChoice) -> Provider:
    if selected.provider not in base.providers:
        raise ValueError("未知的 Agent 连接，请从本地配置中选择")
    provider = base.providers[selected.provider].model_copy(deep=True)
    provider.model = selected.model.strip()
    provider.reasoning_effort = selected.reasoning_effort
    provider = Provider.model_validate(provider.model_dump())
    if provider.kind != "command" and not provider.model:
        raise ValueError("真实 Agent 必须填写模型名称")
    return provider


def validate_defaults(base: Config, selected: ModelDefaults) -> None:
    for item in [selected.builder, *selected.executors]:
        resolve(base, item)


def defaults(base: Config, path: Path) -> ModelDefaults:
    if path.exists():
        result = ModelDefaults.model_validate(read_json(path))
        validate_defaults(base, result)
        return result
    return ModelDefaults(
        builder=choice(base, base.roles["build"]),
        executors=[choice(base, name) for name in base.execution.models],
        max_rounds=base.limits.max_rounds,
        repetitions=base.execution.repetitions,
        minimum_score=base.quality.minimum_score,
    )


def catalog(base: Config, selected: ModelDefaults) -> list[dict[str, Any]]:
    presets = [{"label": name, **choice(base, name).model_dump()} for name in base.providers]
    for item in [selected.builder, *selected.executors]:
        if any(all(p[key] == value for key, value in item.model_dump().items()) for p in presets):
            continue
        provider = base.providers[item.provider]
        label = " / ".join(filter(None, [provider.kind, item.model, item.reasoning_effort]))
        presets.append({"label": label, **item.model_dump()})
    return presets


def task_config(base: Config, settings: Settings) -> Config:
    validate_defaults(base, settings)
    config = base.model_copy(deep=True)
    config.name, config.goal = settings.name, settings.goal
    config.providers = {"builder": resolve(base, settings.builder)}
    config.roles = dict.fromkeys(("prepare", "build", "evaluate", "improve"), "builder")
    config.execution.models = []
    for index, selected in enumerate(settings.executors, 1):
        key = f"executor_{index}"
        config.providers[key] = resolve(base, selected)
        config.execution.models.append(key)
    config.execution.repetitions = settings.repetitions
    config.limits.max_rounds = settings.max_rounds
    for stage in ("prepare", "build", "improve", "evaluate", "execute"):
        getattr(config.limits, stage).timeout_seconds = settings.agent_timeout_seconds
    config.quality.minimum_score = settings.minimum_score
    return Config.model_validate(config.model_dump())
