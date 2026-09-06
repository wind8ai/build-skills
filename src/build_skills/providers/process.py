"""External process ownership and provider response parsing."""

import json
import os
import signal
import subprocess
from pathlib import Path
from typing import Any

from build_skills.config import canonical
from build_skills.models import Provider
from build_skills.providers import codex, qoder
from build_skills.workspace import WorkflowError, write_json


def invoke(
    provider: Provider,
    stage: str,
    prompt: str,
    context: dict[str, Any],
    schema: dict[str, Any] | None,
    cwd: Path,
    evidence: Path,
    timeout: float,
) -> Any:
    evidence.mkdir(parents=True, exist_ok=False)
    output = evidence / "result.txt"
    schema_path = evidence / "schema.json" if schema else None
    if schema_path:
        write_json(schema_path, schema)
    if provider.kind == "codex":
        args = codex.arguments(provider, cwd, output, schema_path)
        input_text = prompt
    elif provider.kind == "qoder":
        args = qoder.arguments(provider, cwd, prompt)
        input_text = ""
    else:
        args = provider.command
        input_text = canonical(
            {"stage": stage, "prompt": prompt, "context": context, "schema": schema}
        )
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
            process.communicate(input_text, timeout=timeout)
            if process.returncode:
                raise WorkflowError(f"Agent exited {process.returncode}; see {evidence}")
        except subprocess.TimeoutExpired as exc:
            raise WorkflowError(f"Agent timed out; see {evidence}") from exc
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
    result_path = output if provider.kind == "codex" else evidence / "stdout.txt"
    if not result_path.is_file() or result_path.stat().st_size > 2_000_000:
        raise WorkflowError("Missing or oversized agent response")
    text = result_path.read_text().strip()
    if schema is None:
        return {"text": text}
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise WorkflowError("Agent did not return a JSON document; raw output retained") from exc
