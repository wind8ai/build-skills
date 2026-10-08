"""Validate the compiled maintainer workflow; never execute user DSL at runtime."""

import hashlib
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from build_skills.models import Document
from build_skills.workspace import read_json

IDS = {
    "source",
    "configure",
    "parse",
    "review",
    "approve",
    "build",
    "execute",
    "evaluate",
    "improve",
    "verify",
    "deliver",
}
ACTIONS = {
    "import",
    "create",
    "save_defaults",
    "accept_materials",
    "review",
    "approve",
    "resume",
    "retry_parse",
    "retry_development",
    "retry_holdout",
    "cancel",
    "download",
    "report",
}
EDGES = {
    ("source", "configure"),
    ("configure", "parse"),
    ("parse", "review"),
    ("review", "approve"),
    ("approve", "build"),
    ("build", "execute"),
    ("execute", "evaluate"),
    ("evaluate", "verify"),
    ("evaluate", "improve"),
    ("improve", "execute"),
    ("verify", "deliver"),
}


class Position(Document):
    x: int = Field(ge=0)
    y: int = Field(ge=0)


class Node(Document):
    id: str
    title: str
    subtitle: str
    position: Position
    actions: list[str]
    form: Literal["source", "configure", "parse", "review", "approve", "runtime", "deliver"]
    role: Literal["", "builder", "executors"]


class Edge(Document):
    id: str
    source: str
    target: str
    label: str


class Description(Document):
    id: Literal["skill-build"]
    version: Literal[1]
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    nodes: list[Node]
    edges: list[Edge]


def validate_description(value: Any) -> dict[str, Any]:
    description = Description.model_validate(value)
    if len(description.nodes) != len(IDS) or {node.id for node in description.nodes} != IDS:
        raise ValueError("Workflow must retain all confirmation and verification nodes")
    if (
        len(description.edges) != len(EDGES)
        or {(e.source, e.target) for e in description.edges} != EDGES
    ):
        raise ValueError("Workflow edges must preserve the verified execution contract")
    if len({e.id for e in description.edges}) != len(description.edges):
        raise ValueError("Duplicate workflow edge IDs")
    forms = {
        "source": "source",
        "configure": "configure",
        "parse": "parse",
        "review": "review",
        "approve": "approve",
        "deliver": "deliver",
    }
    roles = {
        "parse": "builder",
        "review": "builder",
        "build": "builder",
        "evaluate": "builder",
        "improve": "builder",
        "execute": "executors",
        "verify": "executors",
    }
    if any(
        node.form != forms.get(node.id, "runtime") or node.role != roles.get(node.id, "")
        for node in description.nodes
    ):
        raise ValueError("Workflow forms and roles must match core stage responsibilities")
    if any(set(node.actions) - ACTIONS for node in description.nodes):
        raise ValueError("Unknown workflow action")
    return description.model_dump()


def builtin_workflow() -> dict[str, Any]:
    root = Path(__file__).parent / "workflows"
    description = validate_description(read_json(root / "skill_build.json"))
    if (
        description["source_sha256"]
        != hashlib.sha256((root / "skill_build.star").read_bytes()).hexdigest()
    ):
        raise ValueError(
            "Workflow manifest is stale; compile the maintainer Starlark before building"
        )
    return description


def check_frontend_assets() -> None:
    import re

    root = Path(__file__).parent / "static"
    index = root / "index.html"
    if not index.exists():
        raise ValueError(
            "前端尚未构建，请运行 npm --prefix web-ui ci && node scripts/build-web.mjs"
        )
    references = re.findall(r'(?:src|href)="(/assets/[^"<>]+)"', index.read_text())
    if not references or any(not (root / ref.lstrip("/")).is_file() for ref in references):
        raise ValueError("前端资源不完整，请运行 node scripts/build-web.mjs 后启动")
