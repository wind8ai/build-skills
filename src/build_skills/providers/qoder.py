"""Qoder headless invocation with risk review and structured failure detection."""

import json
from pathlib import Path

from build_skills.models import Provider
from build_skills.workspace import WorkflowError


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
        "bypass_permissions" if provider.permission == "full" else "auto",
        "--output-format",
        "json",
    ]

    if provider.reasoning_effort:
        args += ["--reasoning-effort", provider.reasoning_effort]
    return [*args, prompt]


class PermissionDenied(WorkflowError):
    """A tool authorization failure is infrastructure, not Skill quality."""


def result_text(path: Path) -> str:
    if not path.is_file() or path.stat().st_size > 2_000_000:
        raise WorkflowError("Missing or oversized Qoder response")
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise WorkflowError("Qoder 未返回有效的 JSON 结果；请检查 CLI 版本与调用日志") from exc
    if not isinstance(result, dict) or result.get("type") != "result":
        raise WorkflowError("Qoder 返回了未知的结果格式")
    if result.get("permission_denials"):
        raise PermissionDenied(
            "Qoder 工具授权被拒绝，执行未完成；请检查工作目录信任与权限规则。"
            "这是运行环境问题，不会自动重构 Skill。"
        )
    if result.get("is_error") or result.get("subtype") != "success":
        raise WorkflowError(f"Qoder 未完成请求：{str(result.get('result', 'unknown error'))[:500]}")
    text = result.get("result")
    if not isinstance(text, str):
        raise WorkflowError("Qoder 结果缺少文本内容")
    return text.strip()
