"""Persistent stages shared by individual commands and the loop."""

import os
import subprocess
import time
import uuid
from importlib.resources import files
from pathlib import Path
from typing import Any

from jinja2 import StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment

from build_skills.config import Config, canonical, digest
from build_skills.models import Brief
from build_skills.providers.process import invoke, recover_result
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
            pending = self.state.get("pending_call")
            if pending:
                receipt_path = self.root / "calls" / f"{pending['number']:04d}" / "attempt.json"
                receipt = read_json(receipt_path) if receipt_path.exists() else {}
                if receipt.get("status") == "running" and receipt.get("pid"):
                    try:
                        os.kill(receipt["pid"], 0)
                    except ProcessLookupError:
                        pass
                    else:
                        raise WorkflowError(
                            "Prior Agent process may still be active; inspect its evidence"
                        )
                elapsed = receipt.get("elapsed_seconds", max(0, time.time() - pending["started"]))
                delta = elapsed - pending["reserved"]
                self.state["usage"][pending["key"]]["elapsed"] += delta
                self.state["elapsed"] += delta
                self.state.pop("pending_call")
                self.state["status"] = "interrupted"
                self.save()
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
                "usage": {},
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
        target = safe_path(self.root, name + ".json")
        if target.exists():
            previous = read_json(target)
            if digest(previous) != digest(value):
                write_json(self.root / "history" / f"{name}-{digest(previous)}.json", previous)
        write_json(target, value)
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
        recover_call: int | None = None,
    ) -> Any:
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
        selected_name = provider or self.config.roles[stage]
        if recover_call is not None:
            if recover_call < 1 or recover_call > self.state["calls"]:
                raise ValueError("Recovery call is not part of this run")
            result = recover_result(
                self.config.providers[selected_name],
                stage,
                prompt,
                context,
                schema,
                self.root / "calls" / f"{recover_call:04d}",
                self.root / "sessions",
            )
            self.state.setdefault("recoveries", []).append({"call": recover_call, "stage": stage})
            self.save()
            return result
        policy = getattr(self.config.limits, stage)
        key = f"execute:{selected_name}" if stage == "execute" else stage
        usage = self.state["usage"].setdefault(key, {"calls": 0, "elapsed": 0.0})
        if policy.max_calls and usage["calls"] >= policy.max_calls:
            raise WorkflowError(f"Call budget exhausted for {key}", 4)
        remaining = policy.total_seconds - usage["elapsed"] if policy.total_seconds else None
        if remaining is not None and remaining <= 0:
            raise WorkflowError(f"Time budget exhausted for {key}", 4)
        timeout = policy.timeout_seconds or None
        if remaining is not None:
            timeout = min(timeout, remaining) if timeout is not None else remaining
        reserved = timeout or 0.0
        self.state["calls"] += 1
        usage["calls"] += 1
        usage["elapsed"] += reserved
        self.state["elapsed"] += reserved
        self.state["pending_call"] = {
            "key": key,
            "reserved": reserved,
            "started": time.time(),
            "number": self.state["calls"],
        }
        self.save()
        start = time.monotonic()
        try:
            evidence = self.root / "calls" / f"{self.state['calls']:04d}"
            cwd = cwd or self.root / "sessions" / uuid.uuid4().hex
            cwd.mkdir(parents=True, exist_ok=True)
            selected = self.config.providers[selected_name]
            return invoke(selected, stage, prompt, context, schema, cwd, evidence, timeout)
        finally:
            elapsed = time.monotonic() - start
            usage["elapsed"] += elapsed - reserved
            self.state["elapsed"] += elapsed - reserved
            self.state.pop("pending_call", None)
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
            try:
                self.execute()
            except WorkflowError:
                self.evaluate()
                raise
            self.evaluate()
            if self.state["development_passed"]:
                self.verify()
                self.deliver()
                return
            self.improve()

    def build(self, recover_call: int | None = None, from_skill: Path | None = None) -> None:
        from build_skills.workspace import read_skill_directory, validate_skill

        brief = self.approved()
        if self.state["round"]:
            if recover_call is not None or from_skill is not None:
                raise ValueError("Initial build is already accepted")
            self.artifact(f"skill-{self.state['round']}")
            return
        if from_skill is not None:
            if recover_call is not None:
                raise ValueError("Choose --from-skill or --recover-call")
            source = from_skill.absolute()
            skill = read_skill_directory(source)
            self.store("skill-1", skill.model_dump())
            self.state["round"] = 1
            self.state["status"] = "built"
            self.state["candidate_source"] = {
                "kind": "imported",
                "path": str(source),
                "digest": digest(skill.model_dump()),
            }
            self.save()
            return
        context = {
            "scope": brief.scope,
            "materials": read_json(self.root / "materials.json"),
            "criteria": brief.criteria,
            "development": [s.model_dump() for s in brief.development],
            "sources": [s.model_dump() for s in brief.sources],
        }
        from build_skills.models import Skill

        skill = validate_skill(
            self.call("build", context, Skill.model_json_schema(), recover_call=recover_call)
        )
        self.store("skill-1", skill.model_dump())
        self.state["round"] = 1
        self.state["status"] = "built"
        self.save()

    def execute(self, holdout: bool = False, retry_failed: bool = False) -> None:
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
                        previous = self.artifact(key)
                        if previous["status"] == "completed" or not retry_failed:
                            records.append(previous)
                            continue
                    self.state["artifacts"].pop(f"{prefix}-report-{number}", None)
                    self.state[f"{prefix}_passed"] = False
                    self.save()
                    cwd = self.root / "sessions" / uuid.uuid4().hex
                    before = self.state["calls"]
                    record = {
                        "model": model,
                        "scenario": scenario.id,
                        "repetition": repetition,
                        "task": scenario.task,
                        "skill_digest": digest(skill.model_dump()),
                        "cwd": str(cwd),
                        "status": "completed",
                    }
                    try:
                        stage_task(cwd, scenario, skill)
                        if self.config.execution.git_repository:
                            subprocess.run(
                                ["git", "init", "--quiet", "--template="],
                                cwd=cwd,
                                check=True,
                                capture_output=True,
                                timeout=10,
                            )
                        record["output"] = self.call(
                            "execute", {"task": scenario.task}, None, model, cwd
                        )
                        record["observation"] = observe(cwd, scenario)
                    except (WorkflowError, OSError, ValueError, subprocess.SubprocessError) as exc:
                        record.update(
                            status="failed",
                            error=str(exc),
                            error_code=exc.code if isinstance(exc, WorkflowError) else 5,
                            output={"text": "Execution did not complete."},
                            observation={"checks": [], "files": {}},
                        )
                        # Preserve safe partial observations when a process fails.
                        try:
                            record["observation"] = observe(cwd, scenario)
                        except (OSError, ValueError):
                            pass
                    record["call"] = self.state["calls"] if self.state["calls"] > before else None
                    records.append(self.store(key, record))
        self.store(f"{prefix}-executions-{number}", records)
        self.state["execution_count"] = len(records)
        self.state["execution_results"] = [
            {k: r[k] for k in ("model", "scenario", "status")} for r in records
        ]
        failures = [r for r in records if r["status"] != "completed"]
        self.state["status"] = "execution_incomplete" if failures else "executed"
        self.save()
        if failures:
            code = 4 if all(r.get("error_code") == 4 for r in failures) else 5
            raise WorkflowError(
                f"{len(failures)} execution(s) incomplete; all model results retained", code
            )

    def evaluate(self, holdout: bool = False) -> None:
        from build_skills.models import BatchJudgment

        brief = self.approved()
        number = self.state["round"]
        prefix = "holdout" if holdout else "development"
        name = f"{prefix}-report-{number}"
        if name in self.state["artifacts"]:
            report = self.artifact(name)
            self.state[f"{prefix}_passed"] = report["passed"]
            self.save()
            return
        records = self.artifact(f"{prefix}-executions-{number}")
        scenarios = brief.holdout if holdout else brief.development
        expected = {
            (m, s.id, n)
            for m in self.config.execution.models
            for s in scenarios
            for n in range(self.config.execution.repetitions)
        }
        identities = {(r["model"], r["scenario"], r["repetition"]) for r in records}
        if identities != expected or len(records) != len(expected):
            raise ValueError("Execution matrix is incomplete or duplicated")
        candidates = {f"case-{i}": r for i, r in enumerate(records) if r["status"] == "completed"}
        scored = {}
        if candidates:
            context = {
                "criteria": brief.criteria,
                "executions": [
                    {
                        "label": label,
                        "task": r["task"],
                        "output": r["output"],
                        "observation": r["observation"],
                    }
                    for label, r in candidates.items()
                ],
            }
            batch = BatchJudgment.model_validate(
                self.call("evaluate", context, BatchJudgment.model_json_schema())
            )
            scored = {item.label: item for item in batch.results}
            if len(scored) != len(batch.results) or set(scored) != set(candidates):
                raise WorkflowError("Judge returned missing, duplicate or unknown labels")
        judgments = []
        for i, r in enumerate(records):
            if r["status"] != "completed":
                judgments.append(
                    {
                        "model": r["model"],
                        "scenario": r["scenario"],
                        "passed": False,
                        "error": r.get("error"),
                        "judgment": None,
                    }
                )
                continue
            judgment = scored[f"case-{i}"]
            direct = all(check["passed"] for check in r["observation"]["checks"])
            passed = (
                direct and judgment.passed and judgment.score >= self.config.quality.minimum_score
            )
            judgments.append(
                {
                    "model": r["model"],
                    "scenario": r["scenario"],
                    "passed": passed,
                    "judgment": judgment.model_dump(exclude={"label"}),
                }
            )
        report = {
            "passed": bool(judgments) and all(j["passed"] for j in judgments),
            "judgments": judgments,
            "execution_errors": len(records) - len(candidates),
            "skill_digest": digest(self.artifact(f"skill-{number}")),
            "isolation": "separate inputs and sessions; not an operating-system sandbox",
        }
        self.store(name, report)
        self.state[f"{prefix}_passed"] = report["passed"]
        self.state["status"] = "evaluated"
        self.save()

    def improve(self, recover_call: int | None = None) -> None:
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
            "materials": read_json(self.root / "materials.json"),
            "criteria": brief.criteria,
            "skill": self.artifact(f"skill-{number}"),
            "report": report,
            "executions": self.artifact(f"development-executions-{number}"),
        }
        skill = validate_skill(
            self.call("improve", context, Skill.model_json_schema(), recover_call=recover_call)
        )
        self.store(f"skill-{number + 1}", skill.model_dump())
        self.state["round"] = number + 1
        self.state["development_passed"] = False
        self.state["status"] = "built"
        self.save()

    def verify(self, retry_failed: bool = False) -> None:
        self.approved()
        number = self.state["round"]
        if not self.artifact(f"development-report-{number}")["passed"]:
            raise WorkflowError("Development criteria not met", 4)
        self.state["holdout_started"] = True
        self.save()
        try:
            self.execute(holdout=True, retry_failed=retry_failed)
        except WorkflowError:
            self.evaluate(holdout=True)
            raise
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
