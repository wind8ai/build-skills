"""External process ownership and provider response parsing."""

import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from build_skills.config import canonical
from build_skills.models import BatchJudgment, Brief, Provider
from build_skills.providers import codex, qoder
from build_skills.workspace import WorkflowError, read_json, validate_skill, write_json


def invoke(
    provider: Provider,
    stage: str,
    prompt: str,
    context: dict[str, Any],
    schema: dict[str, Any] | None,
    cwd: Path,
    evidence: Path,
    timeout: float | None,
) -> Any:
    evidence.mkdir(parents=True, exist_ok=False)
    output = evidence / "result.txt"
    schema_path = evidence / "schema.json" if schema else None
    if schema_path:
        write_json(schema_path, schema)
    if provider.kind == "codex":
        args = codex.arguments(provider, cwd, output)
        input_text = prompt
    elif provider.kind == "qoder":
        args = qoder.arguments(provider, cwd, prompt)
        input_text = ""
    else:
        args = provider.command
        input_text = canonical(
            {"stage": stage, "prompt": prompt, "context": context, "schema": schema}
        )
    receipt = {
        "stage": stage,
        "model": provider.model,
        "permission": provider.permission,
        "cwd": str(cwd),
        "timeout_seconds": timeout,
        "status": "running",
    }
    write_json(evidence / "attempt.json", receipt)
    (evidence / "prompt.txt").write_text(prompt)
    started = time.monotonic()
    try:
        with (
            (evidence / "stdout.txt").open("w") as stdout,
            (evidence / "stderr.txt").open("w") as stderr,
        ):
            process = subprocess.Popen(
                args,
                cwd=cwd,
                stdin=subprocess.PIPE,
                stdout=stdout,
                stderr=stderr,
                text=True,
                start_new_session=True,
            )
            try:
                receipt["pid"] = process.pid
                write_json(evidence / "attempt.json", receipt)
                process.communicate(input_text, timeout=timeout)
                receipt["exit_code"] = process.returncode
                if process.returncode:
                    raise WorkflowError(f"Agent exited {process.returncode}; see {evidence}")
                receipt["status"] = "process_exited"
            except subprocess.TimeoutExpired as exc:
                receipt["status"] = "timed_out"
                raise WorkflowError(f"Agent timed out; see {evidence}") from exc
            except KeyboardInterrupt:
                receipt["status"] = "interrupted"
                raise
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
    except (OSError, WorkflowError):
        if receipt["status"] == "running":
            receipt["status"] = "failed"
        raise
    finally:
        receipt["elapsed_seconds"] = time.monotonic() - started
        write_json(evidence / "attempt.json", receipt)
    try:
        result = _collect_result(provider, stage, schema, cwd, evidence, output)
    except (OSError, ValueError, WorkflowError):
        receipt["status"] = "invalid_output"
        write_json(evidence / "attempt.json", receipt)
        raise
    receipt["status"] = "completed"
    write_json(evidence / "attempt.json", receipt)
    return result


def _collect_result(
    provider: Provider,
    stage: str,
    schema: dict[str, Any] | None,
    cwd: Path,
    evidence: Path,
    output: Path,
) -> Any:
    if stage in {"build", "improve"}:
        skill_root = cwd / "skill"
        if skill_root.is_symlink() or not skill_root.is_dir():
            raise WorkflowError("Agent did not create skill/; see its call evidence")
        package = {}
        for path in sorted(skill_root.rglob("*")):
            if path.is_symlink():
                raise WorkflowError("Skill output contains a symlink")
            if path.is_file():
                package[str(path.relative_to(skill_root))] = path.read_text()
        return validate_skill({"files": package}).model_dump()
    if schema is not None:
        response = cwd / "response.json"
        if not response.is_file():
            raise WorkflowError("Agent did not create response.json; raw output retained")
        try:
            model = Brief if stage == "prepare" else BatchJudgment
            return model.model_validate(read_json(response)).model_dump()
        except (ValueError, OSError) as exc:
            raise WorkflowError("Invalid response.json; raw output retained") from exc
    result_path = output if provider.kind == "codex" else evidence / "stdout.txt"
    if not result_path.is_file() or result_path.stat().st_size > 2_000_000:
        raise WorkflowError("Missing or oversized agent response")
    text = result_path.read_text().strip()
    return {"text": text}
