"""Loopback-only API adapting the existing CLI and its approval contract."""

import json
import shutil
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

import tomli_w
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from build_skills.config import canonical, digest, load_config
from build_skills.models import Brief, Document
from build_skills.web.artifacts import delivery_archive
from build_skills.web.jobs import JobRunner, lock_busy
from build_skills.web.materials import (
    SUPPORTED,
    record_upload,
)
from build_skills.web.node_state import allowed_actions, node_states
from build_skills.web.settings import (
    ModelDefaults,
    Settings,
    catalog,
    defaults,
    task_config,
    validate_defaults,
    web_base,
)
from build_skills.web.sources import import_url, relative_name, select_files, supported
from build_skills.web.workflow_schema import builtin_workflow, validate_description
from build_skills.workspace import locked, read_json, safe_path, write_json


class URLSource(Document):
    kind: Literal["git", "url"]
    url: str = Field(min_length=1, max_length=2000)
    ref: str = Field(default="", max_length=200)


class SourceSelection(Document):
    files: list[str] = Field(min_length=1, max_length=20)


class MaterialApproval(Document):
    digest: str


class Approval(Document):
    digest: str


class ReviewAnswers(Document):
    digest: str
    answers: list[str] = Field(default_factory=list, max_length=100)
    feedback: str = Field(default="", max_length=20000)


def create_app(
    config_path: Path | None, data_root: Path, *, allow_local_sources: bool = False
) -> FastAPI:
    root = data_root.resolve()
    base = web_base(config_path, root)
    key = digest(str(config_path.resolve()) if config_path else "builtin")[:16]
    defaults_path = root / "defaults" / f"{key}.json"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    workflow_description = builtin_workflow()
    runner = JobRunner()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        runner.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @app.middleware("http")
    async def local_only(request: Request, call_next: Any) -> Any:
        host = request.headers.get("host", "").split(":")[0]
        if host not in {"127.0.0.1", "localhost", "testserver"}:
            return JSONResponse({"detail": "Local host required"}, status_code=403)
        if request.method != "GET":
            if request.headers.get("x-build-skills") != "local":
                return JSONResponse({"detail": "Local request required"}, status_code=403)
            origin = request.headers.get("origin")
            if origin and origin != f"http://{request.headers.get('host')}":
                return JSONResponse({"detail": "Cross-origin request refused"}, status_code=403)
            length = request.headers.get("content-length", "")
            if not length.isdigit():
                return JSONResponse({"detail": "Content-Length required"}, status_code=411)
            if int(length) > 55_000_000:
                return JSONResponse({"detail": "上传总大小最多 50 MB"}, status_code=413)
        return await call_next(request)

    @app.exception_handler(ValueError)
    async def invalid(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    def directory(identifier: str, category: str = "jobs") -> Path:
        if len(identifier) != 32 or not all(c in "0123456789abcdef" for c in identifier):
            raise HTTPException(404, "Unknown ID")
        path = safe_path(root / category, identifier)
        if not path.is_dir():
            raise HTTPException(404, "Unknown ID")
        return path

    @app.get("/api/workflow")
    def workflow_graph() -> Any:
        return workflow_description

    @app.get("/api/options")
    def options() -> Any:
        selected = defaults(base, defaults_path)
        return selected.model_dump() | {
            "catalog": catalog(base, selected),
            "connections": {name: {"kind": p.kind} for name, p in base.providers.items()},
            "goal": base.goal,
            "name": base.name,
            "storage": str(root),
            "defaults_path": str(defaults_path),
            "source_file_types": sorted(SUPPORTED),
            "private_git": False,
        }

    @app.put("/api/defaults")
    def save_defaults(selected: ModelDefaults) -> Any:
        validate_defaults(base, selected)
        with locked(defaults_path.parent):
            write_json(defaults_path, selected.model_dump())
        return options()

    @app.post("/api/materials")
    def upload(
        files: Annotated[list[UploadFile], File()], paths: Annotated[str, Form()] = ""
    ) -> Any:
        if not 1 <= len(files) <= 20:
            raise ValueError("请选择 1 到 20 个文件")
        relative_paths = json.loads(paths) if paths else [file.filename or "" for file in files]
        if (
            not isinstance(relative_paths, list)
            or len(relative_paths) != len(files)
            or not all(isinstance(name, str) for name in relative_paths)
        ):
            raise ValueError("文件路径清单与上传文件不匹配")
        if len(set(relative_paths)) != len(relative_paths):
            raise ValueError("材料路径重复")
        relative_paths = [relative_name(name) for name in relative_paths]
        identifier = uuid.uuid4().hex
        folder = root / "materials" / identifier
        folder.mkdir(parents=True, mode=0o700)
        entries: list[dict[str, Any]] = []
        total = 0
        try:
            for index, file in enumerate(files):
                name = file.filename or ""
                if Path(name).name != name or "\\" in name or not supported(relative_paths[index]):
                    raise ValueError(f"文件名或类型不支持：{name}")
                content = file.file.read(10_000_001)
                if not content:
                    raise ValueError(f"文件为空：{name}")
                total += len(content)
                if len(content) > 10_000_000 or total > 50_000_000:
                    raise ValueError("单文件最多 10 MB，总大小最多 50 MB")
                original = folder / f"{index}{Path(name).suffix.lower()}"
                original.write_bytes(content)
                entries.append(record_upload(original, relative_paths[index]))
            if sum(len(item["text"].encode()) for item in entries if item["text"]) > 5_000_000:
                raise ValueError("文本总量最多 5 MB")
            write_json(folder / "manifest.json", entries)
        except Exception:
            shutil.rmtree(folder)
            raise
        return {"id": identifier, "files": entries}

    @app.post("/api/sources/url")
    def remote_source(request: URLSource) -> Any:
        return import_url(
            root, request.kind, request.url, request.ref, allow_local=allow_local_sources
        )

    @app.post("/api/sources/{identifier}/select")
    def select_source(identifier: str, request: SourceSelection) -> Any:
        directory(identifier, "sources")
        return select_files(root, identifier, request.files)

    @app.post("/api/jobs")
    def create(settings: Settings) -> Any:
        material = directory(settings.material, "materials")
        config = task_config(base, settings)
        identifier = uuid.uuid4().hex
        job = root / "jobs" / identifier
        config.workspace = str(job / "runs")
        config.materials = [str(job / "text")]
        job.mkdir(parents=True, mode=0o700)
        (job / "text").mkdir()
        try:
            sources = read_json(material / "manifest.json")
            (job / "inputs").mkdir()
            for source in sources:
                shutil.copyfile(
                    safe_path(material, source["source"]),
                    safe_path(job / "inputs", source["source"]),
                )
            write_json(job / "sources.json", sources)
            write_json(
                job / "source-metadata.json",
                [{k: v for k, v in source.items() if k != "text"} for source in sources],
            )
            (job / "config.toml").write_text(tomli_w.dumps(config.model_dump(exclude_none=True)))
            load_config(job / "config.toml")
        except Exception:
            shutil.rmtree(job)
            raise
        write_json(job / "workflow.json", workflow_description)
        write_json(job / "settings.json", settings.model_dump())
        write_json(job / "result.json", {"status": "parsing"})
        runner.start(job, "parse", {"timeout": settings.parsing_timeout_seconds})
        return {"id": identifier}

    @app.get("/api/jobs")
    def jobs() -> Any:
        return [
            {"id": p.parent.name, "name": read_json(p)["name"]}
            for p in sorted(
                (root / "jobs").glob("*/settings.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        ]

    @app.get("/api/jobs/{identifier}")
    def status(identifier: str) -> Any:
        job = directory(identifier)
        run = job / "runs" / identifier
        was_active = runner.busy(job)
        result = read_json(job / "result.json") if (job / "result.json").exists() else {}
        if (job / "parsing/state.json").exists() and not result.get("error"):
            result.update(read_json(job / "parsing/state.json"))
        if (job / "parsing/result.json").exists():
            result["parsing"] = read_json(job / "parsing/result.json")
            result["parsing_digest"] = digest(result["parsing"])
        if (job / "parsing/call/attempt.json").exists():
            result["parsing_attempt"] = read_json(job / "parsing/call/attempt.json")
        result["materials_approved"] = (job / "parsing/approval.json").exists()
        state_path = run / "state.json"
        if state_path.exists():
            result.update(read_json(state_path))
            if (
                result.get("error")
                and state_path.stat().st_mtime_ns > (job / "result.json").stat().st_mtime_ns
            ):
                result["previous_error"] = result.pop("error")
        result.update(id=identifier, busy=was_active or runner.busy(job), path=str(run))
        result["settings"] = read_json(job / "settings.json")
        result["source_files"] = (
            read_json(job / "source-metadata.json")
            if (job / "source-metadata.json").exists()
            else []
        )
        if (run / "brief.json").exists():
            result["brief"] = read_json(run / "brief.json")
            result["brief_digest"] = digest(result["brief"])
        if result.get("status") == "awaiting_approval" and result.get("error") == (
            "Review and approve the brief first"
        ):
            result.pop("error", None)
        result["review_history"] = (
            read_json(run / "review-history.json") if (run / "review-history.json").exists() else []
        )
        last_path = run / "calls" / f"{result.get('calls', 0):04d}" / "attempt.json"
        if last_path.exists():
            last = read_json(last_path)
            result["last_call"] = {
                key: last.get(key) for key in ("stage", "status", "elapsed_seconds")
            }
        pending = result.get("pending_call")
        if pending:
            attempt_path = run / "calls" / f"{pending['number']:04d}" / "attempt.json"
            attempt = read_json(attempt_path) if attempt_path.exists() else {}
            result["current_call"] = {
                "stage": attempt.get("stage", pending["key"].split(":")[0]),
                "elapsed_seconds": max(0, int(time.time() - pending["started"])),
                "timeout_seconds": attempt.get("timeout_seconds"),
            }
        result["matrices"] = {
            prefix: read_json(path) if path.exists() else []
            for prefix in ("development", "holdout")
            for path in [run / f"{prefix}-executions-{result.get('round', 0)}.json"]
        }
        result["reports"] = {p.stem: read_json(p) for p in run.glob("*-report-*.json")}
        result["operation"] = (
            read_json(job / "operation.json") if (job / "operation.json").exists() else {}
        )
        if result["busy"] and not result.get("current_call"):
            result["current_call"] = {
                "stage": {
                    "parse": "parse",
                    "retry_parse": "parse",
                    "approve": "build",
                    "retry_development": "execute",
                    "retry_holdout": "execute",
                    "review": "prepare",
                    "accept_materials": "prepare",
                }.get(
                    result["operation"].get("action"),
                    result.get("last_call", {}).get("stage", "prepare"),
                ),
                "elapsed_seconds": max(
                    0, int(time.time() - result["operation"].get("started", time.time()))
                ),
                "timeout_seconds": result["settings"].get("parsing_timeout_seconds", 600)
                if result["operation"].get("action") in {"parse", "retry_parse"}
                else result["settings"].get("agent_timeout_seconds", 600),
            }
        if result["busy"] and result.get("error"):
            result["previous_error"] = result.pop("error")
        if result.get("error") and not result["busy"]:
            receipt_path = (
                job / "parsing/call/attempt.json"
                if result["operation"].get("action") in {"parse", "retry_parse"}
                else last_path
            )
            if receipt_path.exists():
                receipt = read_json(receipt_path)
                stderr = receipt_path.with_name("stderr.txt")
                result["failure"] = {
                    "stage": receipt.get("stage"),
                    "exit_code": receipt.get("exit_code"),
                    "path": str(receipt_path.parent),
                    "stderr_excerpt": stderr.read_text(errors="replace")[-8000:]
                    if stderr.exists()
                    else "",
                }
        result["allowed_actions"] = allowed_actions(job, result, owned=runner.owned(job))
        result["nodes"] = node_states(result)
        result["workflow"] = (
            validate_description(read_json(job / "workflow.json"))
            if (job / "workflow.json").exists()
            else workflow_description
        )
        return result

    @app.post("/api/jobs/{identifier}/accept-materials")
    def confirm_materials(identifier: str, approval: MaterialApproval) -> Any:
        job = directory(identifier)
        if runner.busy(job):
            raise HTTPException(409, "任务正在执行")
        if not (job / "parsing/result.json").exists():
            raise HTTPException(409, "材料尚未完成解析")
        if digest(read_json(job / "parsing/result.json")) != approval.digest:
            raise HTTPException(409, "材料解析结果已变化，请刷新")
        if (job / "parsing/approval.json").exists():
            raise HTTPException(409, "材料已经确认")

        runner.start(job, "accept_materials", approval.model_dump())
        return {"id": identifier}

    def reviewable(job: Path, accepted: str) -> Brief:
        run = job / "runs" / job.name
        if runner.busy(job):
            raise HTTPException(409, "任务正在执行，请等待当前操作完成")
        if not (run / "brief.json").exists():
            raise HTTPException(409, "请先核对材料并生成草案")
        state = read_json(run / "state.json")
        if state["round"] or state.get("approval"):
            raise HTTPException(409, "草案已经确认或开始构建，请新建任务")
        brief = Brief.model_validate(read_json(run / "brief.json"))
        if digest(brief.model_dump()) != accepted:
            raise HTTPException(409, "草案已更新，请刷新后审阅当前版本")
        return brief

    @app.post("/api/jobs/{identifier}/review")
    def answer_questions(identifier: str, request: ReviewAnswers) -> Any:
        job = directory(identifier)
        brief = reviewable(job, request.digest)
        if len(request.answers) != len(brief.questions) or any(
            not answer.strip() for answer in request.answers
        ):
            raise ValueError("请逐条填写问题的回答，再提交更新草案")
        if not request.answers and not request.feedback.strip():
            raise ValueError("请填写希望调整的内容")

        runner.start(job, "review", request.model_dump())
        return {"id": identifier}

    @app.post("/api/jobs/{identifier}/approve")
    def approve(identifier: str, approval: Approval) -> Any:
        job = directory(identifier)
        brief = reviewable(job, approval.digest)
        if brief.questions:
            raise ValueError("请先回答草案中的问题并更新草案，再确认开始构建")

        runner.start(job, "approve", approval.model_dump())
        return {"id": identifier}

    @app.post("/api/jobs/{identifier}/resume")
    def resume(identifier: str) -> Any:
        job = directory(identifier)
        if (
            not (job / "runs" / identifier / "state.json").exists()
            and not (job / "parsing/approval.json").exists()
        ):
            raise HTTPException(409, "请先核对材料；解析失败需要新建任务")
        current = status(identifier)
        if "resume" not in current["allowed_actions"]:
            raise HTTPException(409, "请使用重试失败项操作；保留质量失败需要新建运行")
        runner.start(job, "resume")
        return {"id": identifier}

    @app.post("/api/jobs/{identifier}/actions/{action}")
    def action(identifier: str, action: str) -> Any:
        job = directory(identifier)
        current = status(identifier)
        if (
            action not in {"resume", "retry_parse", "retry_development", "retry_holdout", "cancel"}
            or action not in current["allowed_actions"]
        ):
            raise HTTPException(409, "当前状态不允许此操作")
        if action == "cancel":
            runner.cancel(job)
        else:
            runner.start(
                job,
                action,
                {"timeout": current["settings"].get("parsing_timeout_seconds", 600)}
                if action == "retry_parse"
                else None,
            )
        return {"id": identifier}

    @app.get("/api/jobs/{identifier}/download")
    def download(identifier: str) -> FileResponse:
        job = directory(identifier)
        if runner.owned(job) or lock_busy(job / ".job-lock"):
            raise HTTPException(409, "任务正在执行")
        run = job / "runs" / identifier
        if not (run / "state.json").exists():
            raise HTTPException(409, "任务尚未开始构建")
        state = read_json(run / "state.json")
        if state.get("status") != "delivered":
            raise HTTPException(409, "只有通过验证的 Skill 才能下载交付包")
        from build_skills.workflow import Workflow
        from build_skills.workspace import locked

        workflow = Workflow(load_config(job / "config.toml"), identifier)
        with locked(run, wait=True):
            workflow.load()
            manifest = workflow.deliver()
            skill = workflow.artifact(f"skill-{workflow.state['round']}")
            contents = {
                "skill/" + name: content.encode("utf-8") for name, content in skill["files"].items()
            }
            contents["report.json"] = canonical(manifest).encode("utf-8")
            archive = delivery_archive(job, contents)
        return FileResponse(archive, filename=f"skill-{identifier[:8]}.zip")

    @app.get("/api/jobs/{identifier}/report")
    def report(identifier: str) -> Any:
        return JSONResponse(
            status(identifier)["reports"],
            headers={"Content-Disposition": 'attachment; filename="evaluation.json"'},
        )

    app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True))
    return app
