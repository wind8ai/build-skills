"""One owned process per Web action; the core Workflow remains authoritative."""

import json
import sys
import uuid
from pathlib import Path
from typing import Any

from build_skills.config import digest, load_config
from build_skills.web.materials import accept_materials, parse_materials
from build_skills.workflow import Workflow
from build_skills.workspace import WorkflowError, locked, read_json, snapshot


def perform(job: Path, action: str, payload: dict[str, Any]) -> dict[str, Any]:
    config = load_config(job / "config.toml")
    workflow: Workflow | None = None
    with locked(job):
        if action in {"parse", "retry_parse"}:
            if (job / "parsing/approval.json").exists():
                raise ValueError("材料已经确认，不能再次解析")
            if action == "retry_parse" and (job / "parsing").exists():
                history = job / "parsing-history" / uuid.uuid4().hex
                history.parent.mkdir(parents=True, exist_ok=True)
                (job / "parsing").rename(history)
            parse_materials(job, config, payload["timeout"])
            return {"status": "awaiting_material_approval"}
        if action == "accept_materials":
            if (job / "parsing/approval.json").exists():
                raise ValueError("材料已经确认")
            accept_materials(job, payload["digest"])
        workflow = Workflow(config, job.name)
        with locked(workflow.root):
            try:
                initialize = action == "accept_materials"
                if action == "resume" and not workflow.state_path.exists():
                    approval = read_json(job / "parsing/approval.json")
                    if approval.get("materials_digest") != digest(snapshot(config.materials)):
                        raise ValueError("冻结材料与确认记录不匹配，请新建运行")
                    initialize = True
                workflow.load(create=initialize)
                if action == "review":
                    workflow.revise_brief(
                        payload["digest"], payload["answers"], payload["feedback"]
                    )
                elif action == "approve":
                    workflow.approve(payload["digest"])
                    workflow.loop()
                elif action in {"resume", "accept_materials"}:
                    workflow.loop()
                elif action == "retry_development":
                    workflow.execute(retry_failed=True)
                    workflow.loop()
                elif action == "retry_holdout":
                    workflow.verify(retry_failed=True)
                    workflow.deliver()
                else:
                    raise ValueError("Unknown workflow action")
                return workflow.status()
            except (OSError, ValueError, WorkflowError, KeyboardInterrupt) as exc:
                code = (
                    exc.code
                    if isinstance(exc, WorkflowError)
                    else 130
                    if isinstance(exc, KeyboardInterrupt)
                    else 5
                )
                status = {3: "awaiting_approval", 4: "unmet", 130: "interrupted"}.get(
                    code, "failed"
                )
                if workflow and workflow.state:
                    workflow.state["status"] = status
                    workflow.save()
                    result = workflow.status()
                else:
                    result = {"status": status}
                if code != 3:
                    result["error"] = "当前调用已取消" if code == 130 else str(exc)
                return result


if __name__ == "__main__":
    job = Path(sys.argv[1]).resolve()
    request_path = Path(sys.argv[2]).resolve()
    if not request_path.is_relative_to(job / "requests"):
        raise ValueError("Request outside job")
    request = read_json(request_path)
    try:
        result = perform(job, request["action"], request["payload"])
    except Exception as exc:
        result = {"status": "failed", "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False))
