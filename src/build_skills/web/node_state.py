"""Project persistent core state into allowed actions and workflow nodes."""

from pathlib import Path
from typing import Any

from build_skills.workspace import read_json


def failed_records(job: Path, state: dict[str, Any], prefix: str) -> list[dict[str, Any]]:
    path = job / "runs" / job.name / f"{prefix}-executions-{state.get('round', 0)}.json"
    return (
        [record for record in read_json(path) if record["status"] != "completed"]
        if path.exists()
        else []
    )


def allowed_actions(job: Path, state: dict[str, Any], *, owned: bool = False) -> list[str]:
    if state.get("busy"):
        return ["cancel"] if owned else []
    if state.get("delivery"):
        return ["download", "report"]
    if not state.get("materials_approved"):
        return (
            ["accept_materials"]
            if state.get("parsing")
            else ["retry_parse"]
            if state.get("status") in {"failed", "interrupted"}
            else []
        )
    if not state.get("approval"):
        if state.get("brief"):
            return ["review"] + ([] if state["brief"].get("questions") else ["approve"])
        return ["resume"]
    if failed_records(job, state, "holdout"):
        return ["retry_holdout", "report"]
    if failed_records(job, state, "development"):
        return ["retry_development", "report"]
    holdout = job / "runs" / job.name / f"holdout-report-{state.get('round', 0)}.json"
    if holdout.exists() and not read_json(holdout)["passed"]:
        return ["report"]
    development = job / "runs" / job.name / f"development-report-{state.get('round', 0)}.json"
    maximum = state.get("settings", {}).get("max_rounds", 3)
    if (
        development.exists()
        and not read_json(development)["passed"]
        and state.get("round", 0) >= maximum
    ):
        return ["report"]
    return ["resume", "report"]


def node_states(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    ids = (
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
    )
    nodes: dict[str, dict[str, Any]] = {key: {"status": "blocked", "actions": []} for key in ids}
    nodes["source"]["status"] = nodes["configure"]["status"] = "success"
    nodes["parse"]["status"] = (
        "success"
        if state.get("materials_approved")
        else "waiting"
        if state.get("parsing")
        else "ready"
    )
    if state.get("brief"):
        nodes["review"]["status"] = "success" if state.get("approval") else "waiting"
        nodes["approve"]["status"] = (
            "success"
            if state.get("approval")
            else "blocked"
            if state["brief"]["questions"]
            else "ready"
        )
    if state.get("approval"):
        nodes["build"]["status"] = "success" if state.get("round") else "ready"
    if state.get("round"):
        records = state.get("matrices", {}).get("development", [])
        nodes["execute"]["status"] = (
            "success"
            if records and all(r["status"] == "completed" for r in records)
            else "failed"
            if records
            else "ready"
        )
        nodes["evaluate"]["status"] = (
            "success"
            if state.get("development_passed")
            else "failed"
            if any(k.startswith("development-report-") for k in state.get("reports", {}))
            else "ready"
        )
    if state.get("development_passed"):
        nodes["verify"]["status"] = (
            "success"
            if state.get("holdout_passed")
            else "failed"
            if any(k.startswith("holdout-report-") for k in state.get("reports", {}))
            else "ready"
        )
    if state.get("round", 0) > 1:
        nodes["improve"]["status"] = "success"
    if state.get("delivery"):
        nodes["deliver"]["status"] = "success"
        if state.get("round") == 1:
            nodes["improve"]["status"] = "skipped"
    call = state.get("current_call", {})
    stage = call.get("stage")
    current = {
        "prepare": "review",
        "parse": "parse",
        "build": "build",
        "improve": "improve",
        "execute": "verify" if state.get("holdout_started") else "execute",
        "evaluate": "verify" if state.get("holdout_started") else "evaluate",
    }.get(stage)
    if not current and state.get("busy"):
        current = {
            "parse": "parse",
            "retry_parse": "parse",
            "review": "review",
            "accept_materials": "review",
            "approve": "build",
            "retry_development": "execute",
            "retry_holdout": "verify",
        }.get(state.get("operation", {}).get("action"), "build")
    if current and state.get("busy"):
        nodes[current]["status"] = "running"
        nodes[current]["progress"] = call
    for action in state.get("allowed_actions", []):
        key = {
            "accept_materials": "parse",
            "retry_parse": "parse",
            "review": "review",
            "approve": "approve",
            "retry_development": "execute",
            "retry_holdout": "verify",
            "download": "deliver",
            "report": "deliver",
            "resume": current or ("review" if not state.get("brief") else "build"),
            "cancel": current or "build",
        }.get(action)
        if key:
            nodes[key]["actions"].append(action)
    if state.get("error") and not state.get("busy"):
        last_stage = state.get("last_call", {}).get("stage")
        key = {
            "prepare": "review",
            "build": "build",
            "improve": "improve",
            "execute": "verify" if state.get("holdout_started") else "execute",
            "evaluate": "verify" if state.get("holdout_started") else "evaluate",
        }.get(last_stage)
        if not key and state.get("operation", {}).get("action") in {"parse", "retry_parse"}:
            key = "parse"
        if key:
            nodes[key]["status"] = "cancelled" if state.get("status") == "interrupted" else "failed"
        for key, action in (("execute", "retry_development"), ("verify", "retry_holdout")):
            if action in state.get("allowed_actions", []):
                nodes[key]["status"] = "failed"
    return nodes
