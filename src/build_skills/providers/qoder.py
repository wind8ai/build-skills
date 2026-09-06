"""Qoder print-mode invocation; live protocol acceptance is pending."""

from pathlib import Path

from build_skills.models import Provider


def arguments(provider: Provider, cwd: Path, prompt: str) -> list[str]:
    args = [
        *provider.command,
        "--print",
        "--model",
        provider.model,
        "--cwd",
        str(cwd),
        "--no-session-persistence",
        "--permission-mode",
        "bypass_permissions" if provider.permission == "full" else "default",
    ]

    if provider.reasoning_effort:
        args += ["--reasoning-effort", provider.reasoning_effort]
    return [*args, prompt]
