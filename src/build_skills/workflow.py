"""Persistent stages shared by individual commands and the loop."""

import time
import uuid
from importlib.resources import files
from pathlib import Path
from typing import Any

from jinja2 import StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment

from build_skills.config import Config, canonical, digest
from build_skills.models import Brief
from build_skills.providers.process import invoke
from build_skills.workspace import WorkflowError, read_json, safe_path, snapshot, write_json


class Workflow:
    def __init__(self, config: Config, run: str | None):
        self.config = config
        self.run = run or uuid.uuid4().hex[:12]
        if not self.run.isalnum():
            raise ValueError("Invalid run ID")
        self.root = Path(config.workspace) / self.run
        self.state_path = self.root / "state.json"
        self.state: dict[str, Any] = {}

    def load(self, create: bool = False) -> None:
        if self.state_path.exists():
            self.state = read_json(self.state_path)
            if self.state["config"] != self.config.digest():
                raise ValueError("Configuration changed; start a new run")
            if self.state["materials"] != digest(snapshot(self.config.materials)):
                raise ValueError("Materials changed; start a new run")
        elif create:
            material = snapshot(self.config.materials)
            write_json(self.root / "materials.json", material)
            self.state = {
                "run": self.run,
                "status": "new",
                "config": self.config.digest(),
                "materials": digest(material),
                "calls": 0,
                "elapsed": 0.0,
                "round": 0,
                "artifacts": {},
            }
            self.save()
        else:
            raise ValueError("Unknown run; use prepare or loop without --run")

    def save(self) -> None:
        write_json(self.state_path, self.state)

    def artifact(self, name: str) -> Any:
        value = read_json(safe_path(self.root, name + ".json"))
        if self.state["artifacts"].get(name) != digest(value):
            raise ValueError(f"Artifact changed: {name}")
        return value

    def store(self, name: str, value: Any) -> Any:
        write_json(safe_path(self.root, name + ".json"), value)
        self.state["artifacts"][name] = digest(value)
        self.save()
        return value

    def call(
        self,
        stage: str,
        context: dict[str, Any],
        schema: dict[str, Any] | None,
        provider: str | None = None,
        cwd: Path | None = None,
    ) -> Any:
        limits = self.config.limits
        remaining = limits.total_seconds - self.state["elapsed"]
        if self.state["calls"] >= limits.max_calls or remaining <= 0:
            raise WorkflowError("Run budget exhausted", 4)
        self.state["calls"] += 1
        # Reserve the entire timeout. A crashed parent cannot lose charged time.
        timeout = min(limits.timeout_seconds, remaining)
        self.state["elapsed"] += timeout
        self.save()
        start = time.monotonic()
        try:
            evidence = self.root / "calls" / f"{self.state['calls']:04d}"
            cwd = cwd or self.root / "sessions" / uuid.uuid4().hex
            cwd.mkdir(parents=True, exist_ok=True)
            template = self.config.prompts.get(stage)
            if template is None:
                template = files("build_skills.templates").joinpath(stage + ".j2").read_text()
            try:
                prompt = (
                    SandboxedEnvironment(undefined=StrictUndefined)
                    .from_string(template)
                    .render(
                        data=canonical(context),
                        schema=canonical(schema),
                        goal=self.config.goal,
                        task=context.get("task", ""),
                    )
                )
            except TemplateError as exc:
                raise ValueError(f"Invalid {stage} prompt template: {exc}") from exc
            selected = self.config.providers[provider or self.config.roles[stage]]
            return invoke(selected, stage, prompt, context, schema, cwd, evidence, timeout)
        finally:
            self.state["elapsed"] += min(time.monotonic() - start, timeout) - timeout
            self.save()

    def prepare(self) -> None:
        if "brief" not in self.state["artifacts"]:
            context = {
                "materials": read_json(self.root / "materials.json"),
                "feedback": self.feedback_items(),
            }
            brief = Brief.model_validate(self.call("prepare", context, Brief.model_json_schema()))
            self.store("brief", brief.model_dump())
        if not self.state.get("approval"):
            self.state["status"] = "awaiting_approval"
            self.save()

    def approve(self, accepted: str | None) -> None:
        # The user can edit brief.json before accepting its new digest.
        brief = Brief.model_validate(read_json(self.root / "brief.json"))
        if accepted != digest(brief.model_dump()):
            raise ValueError("Approval digest does not match the reviewed brief")
        if brief.questions:
            raise ValueError("Resolve brief questions before approval")
        if self.state["round"]:
            raise ValueError("Run already built; start a new run to revise its brief")
        self.store("brief", brief.model_dump())
        self.state["approval"] = accepted
        self.state["status"] = "approved"
        self.save()

    def approved(self) -> Brief:
        brief = Brief.model_validate(self.artifact("brief"))
        if self.state.get("approval") != digest(brief.model_dump()):
            raise WorkflowError("Review and approve the brief first", 3)
        return brief

    def feedback_items(self) -> list[Any]:
        directory = Path(self.config.workspace) / "feedback"
        return [read_json(path) for path in sorted(directory.glob("*.json"))]

    def status(self) -> dict[str, Any]:
        result = dict(self.state)
        brief = self.root / "brief.json"
        if brief.exists():
            result["brief_digest"] = digest(Brief.model_validate(read_json(brief)).model_dump())
            result["brief_path"] = str(brief)
            if result.get("approval") and result["approval"] != result["brief_digest"]:
                result["status"] = "approval_invalid"
        return result

    def loop(self) -> None:
        if "brief" not in self.state["artifacts"]:
            self.prepare()
        if not self.state.get("approval"):
            raise WorkflowError("Review and approve the brief first", 3)
        self.approved()
        if self.state.get("delivery"):
            self.deliver()
            return
        self.build()
        while True:
            self.execute()
            self.evaluate()
            if self.state["development_passed"]:
                self.verify()
                self.deliver()
                return
            self.improve()

    def build(self) -> None:
        from build_skills.workspace import validate_skill

        brief = self.approved()
        if self.state["round"]:
            self.artifact(f"skill-{self.state['round']}")
            return
        context = {
            "scope": brief.scope,
            "criteria": brief.criteria,
            "development": [s.model_dump() for s in brief.development],
            "sources": [s.model_dump() for s in brief.sources],
        }
        from build_skills.models import Skill

        skill = validate_skill(self.call("build", context, Skill.model_json_schema()))
        self.store("skill-1", skill.model_dump())
        self.state["round"] = 1
        self.state["status"] = "built"
        self.save()

    def execute(self, holdout: bool = False) -> None:
        from build_skills.evaluation import observe, stage_task
        from build_skills.workspace import validate_skill

        brief = self.approved()
        number = self.state["round"]
        if not number:
            raise ValueError("Build a Skill first")
        skill = validate_skill(self.artifact(f"skill-{number}"))
        prefix = "holdout" if holdout else "development"
        scenarios = brief.holdout if holdout else brief.development
        records = []
        for model in self.config.execution.models:
            for scenario in scenarios:
                for repetition in range(self.config.execution.repetitions):
                    key = "execution-" + digest([prefix, number, model, scenario.id, repetition])
                    if key in self.state["artifacts"]:
                        records.append(self.artifact(key))
                        continue
                    cwd = self.root / "sessions" / uuid.uuid4().hex
                    stage_task(cwd, scenario, skill)
                    output = self.call("execute", {"task": scenario.task}, None, model, cwd)
                    record = {
                        "model": model,
                        "scenario": scenario.id,
                        "repetition": repetition,
                        "task": scenario.task,
                        "skill_digest": digest(skill.model_dump()),
                        "output": output,
                        "observation": observe(cwd, scenario),
                    }
                    records.append(self.store(key, record))
        self.store(f"{prefix}-executions-{number}", records)
        self.state["execution_count"] = len(records)
        self.state["status"] = "executed"
        self.save()

    def evaluate(self, holdout: bool = False) -> None:
        from build_skills.models import Judgment

        brief = self.approved()
        number = self.state["round"]
        prefix = "holdout" if holdout else "development"
        records = self.artifact(f"{prefix}-executions-{number}")
        judgments = []
        for index, record in enumerate(records):
            key = f"{prefix}-judgment-{number}-{index}"
            if key in self.state["artifacts"]:
                judged = self.artifact(key)
            else:
                context = {
                    "criteria": brief.criteria,
                    "task": record["task"],
                    "output": record["output"],
                    "observation": record["observation"],
                }
                judgment = Judgment.model_validate(
                    self.call("evaluate", context, Judgment.model_json_schema())
                )
                direct = all(c["passed"] for c in record["observation"]["checks"])
                passed = (
                    direct
                    and judgment.passed
                    and judgment.score >= self.config.quality.minimum_score
                )
                judged = self.store(
                    key,
                    {
                        "model": record["model"],
                        "scenario": record["scenario"],
                        "passed": passed,
                        "judgment": judgment.model_dump(),
                    },
                )
            judgments.append(judged)
        report = {
            "passed": bool(judgments) and all(j["passed"] for j in judgments),
            "judgments": judgments,
            "skill_digest": digest(self.artifact(f"skill-{number}")),
            "isolation": "separate inputs and sessions; not an operating-system sandbox",
        }
        self.store(f"{prefix}-report-{number}", report)
        self.state[f"{prefix}_passed"] = report["passed"]
        self.state["status"] = "evaluated"
        self.save()

    def improve(self) -> None:
        from build_skills.models import Skill
        from build_skills.workspace import validate_skill

        brief = self.approved()
        number = self.state["round"]
        if self.state.get("holdout_started"):
            raise ValueError("Holdout was exposed; start a new run with new holdout scenarios")
        report = self.artifact(f"development-report-{number}")
        if number >= self.config.limits.max_rounds:
            raise WorkflowError("Maximum rounds reached without meeting the standard", 4)
        context = {
            "scope": brief.scope,
            "criteria": brief.criteria,
            "skill": self.artifact(f"skill-{number}"),
            "report": report,
            "executions": self.artifact(f"development-executions-{number}"),
        }
        skill = validate_skill(self.call("improve", context, Skill.model_json_schema()))
        self.store(f"skill-{number + 1}", skill.model_dump())
        self.state["round"] = number + 1
        self.state["development_passed"] = False
        self.state["status"] = "built"
        self.save()

    def verify(self) -> None:
        self.approved()
        number = self.state["round"]
        if not self.artifact(f"development-report-{number}")["passed"]:
            raise WorkflowError("Development criteria not met", 4)
        self.state["holdout_started"] = True
        self.save()
        self.execute(holdout=True)
        self.evaluate(holdout=True)
        if not self.state["holdout_passed"]:
            raise WorkflowError("Holdout failed; use fresh scenarios in a new run", 4)
        self.state["status"] = "verified"
        self.save()

    def deliver(self) -> None:
        import shutil

        from build_skills.evaluation import materialize
        from build_skills.workspace import validate_skill

        self.approved()
        number = self.state["round"]
        skill = validate_skill(self.artifact(f"skill-{number}"))
        report = self.artifact(f"holdout-report-{number}")
        if not report["passed"] or report["skill_digest"] != digest(skill.model_dump()):
            raise WorkflowError("Exact Skill version has not passed verification", 4)
        destination = self.root / "delivery"
        manifest = {
            "skill_digest": report["skill_digest"],
            "models": {
                key: {"model": value.model, "kind": value.kind, "permission": value.permission}
                for key, value in self.config.providers.items()
            },
            "brief": self.approved().model_dump(),
            "repetitions": self.config.execution.repetitions,
            "quality": self.config.quality.model_dump(),
            "development_executions": self.artifact(f"development-executions-{number}"),
            "holdout_executions": self.artifact(f"holdout-executions-{number}"),
            "scope": self.approved().scope,
            "verification": report,
            "permissions": {k: v.permission for k, v in self.config.providers.items()},
            "provider_kinds": {k: v.kind for k, v in self.config.providers.items()},
            "limitation": "Results cover configured tasks only; command fixtures are not models.",
        }
        if destination.exists():
            if read_json(destination / "report.json") != manifest:
                raise ValueError("Delivery already exists with different contents")
            for name, content in skill.files.items():
                if safe_path(destination / "skill", name).read_text() != content:
                    raise ValueError("Delivered Skill was modified")
        else:
            temporary = self.root / ("delivery-" + uuid.uuid4().hex)
            try:
                materialize(temporary / "skill", skill.files)
                write_json(temporary / "report.json", manifest)
                temporary.rename(destination)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        self.state["delivery"] = str(destination)
        self.state["status"] = "delivered"
        self.save()

    def feedback(self, path: Path) -> None:
        value = {"source_run": self.run, "text": path.read_text()}
        if not value["text"].strip():
            raise ValueError("Feedback is empty")
        write_json(Path(self.config.workspace) / "feedback" / (digest(value) + ".json"), value)
