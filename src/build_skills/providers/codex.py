"""Codex noninteractive invocation."""

from pathlib import Path

from build_skills.models import Provider


def arguments(provider: Provider, cwd: Path, output: Path, schema: Path | None) -> list[str]:
    args = [
        *provider.command,
        "exec",
        "--model",
        provider.model,
        "--cd",
        str(cwd),
        "--ephemeral",
        "--skip-git-repo-check",
        "--output-last-message",
        str(output),
        "--sandbox",
        "danger-full-access" if provider.permission == "full" else "workspace-write",
    ]
    if schema is not None:
        args += ["--output-schema", str(schema)]
    return [*args, "-"]
