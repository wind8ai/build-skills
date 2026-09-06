"""Validated workflow documents and configuration."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Document(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Provider(Document):
    kind: Literal["codex", "qoder", "command"]
    command: list[str] = Field(min_length=1)
    model: str = ""
    permission: Literal["restricted", "full"] = "restricted"


class Limits(Document):
    max_rounds: int = Field(default=3, ge=1, le=100)
    max_calls: int = Field(default=60, ge=1)
    timeout_seconds: float = Field(default=120, gt=0)
    total_seconds: float = Field(default=1800, gt=0)


class Execution(Document):
    models: list[str] = Field(min_length=1)
    repetitions: int = Field(default=1, ge=1, le=20)


class Quality(Document):
    minimum_score: float = Field(default=0.8, ge=0, le=1)


class Check(Document):
    path: str
    equals: str | None = None
    contains: str | None = None


class Scenario(Document):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    task: str = Field(min_length=1)
    files: dict[str, str] = Field(default_factory=dict)
    checks: list[Check] = Field(default_factory=list)


class Source(Document):
    reference: str
    finding: str
    status: Literal["provided", "supported", "uncertain"]
    evidence: str


class Brief(Document):
    scope: str = Field(min_length=1)
    criteria: list[str] = Field(min_length=1)
    questions: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(min_length=1)
    development: list[Scenario] = Field(min_length=1)
    holdout: list[Scenario] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_scenarios(self) -> Self:
        ids = [scenario.id for scenario in [*self.development, *self.holdout]]
        if len(ids) != len(set(ids)):
            raise ValueError("Scenario IDs must be unique across development and holdout")
        return self


class Skill(Document):
    files: dict[str, str]


class Judgment(Document):
    score: float = Field(ge=0, le=1)
    passed: bool
    reason: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)
