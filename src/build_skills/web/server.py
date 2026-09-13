"""Loopback-only API adapting the existing CLI and its approval contract."""

import json
import shutil
import subprocess
import sys
import threading
import uuid
import zipfile
from pathlib import Path
from typing import Annotated, Any

import tomli_w
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from build_skills.config import digest, load_config
from build_skills.models import Brief, Document
from build_skills.web.materials import (
    SUPPORTED,
    accept_materials,
    parse_materials,
    record_upload,
)
from build_skills.web.settings import (
    ModelDefaults,
    Settings,
    catalog,
    defaults,
    task_config,
    validate_defaults,
    web_base,
)
from build_skills.workspace import locked, read_json, safe_path, write_json


class MaterialApproval(Document):
    digest: str


class Approval(Document):
    digest: str


class ReviewAnswers(Document):
    digest: str
    answers: list[str] = Field(default_factory=list, max_length=100)
    feedback: str = Field(default="", max_length=20000)


def create_app(config_path: Path | None, data_root: Path) -> FastAPI:
    root = data_root.resolve()
    base = web_base(config_path, root)
    key = digest(str(config_path.resolve()) if config_path else "builtin")[:16]
    defaults_path = root / "defaults" / f"{key}.json"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    active: set[str] = set()
    guard = threading.Lock()

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

    def invoke(job: Path, stage: str, *args: str) -> dict[str, Any]:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "build_skills",
                stage,
                "--config",
                str(job / "config.toml"),
                "--run",
                job.name,
                "--json",
                *args,
            ],
            capture_output=True,
            text=True,
        )
        try:
            value: dict[str, Any] = json.loads(result.stdout)
        except ValueError:
            value = {"status": "failed", "error": result.stderr or "CLI returned no result"}
        write_json(job / "result.json", value)
        return value

    def start(job: Path, action: Any) -> None:
        with guard:
            if job.name in active:
                raise HTTPException(409, "任务正在执行")
            active.add(job.name)

        def work() -> None:
            try:
                action()
            except Exception as exc:
                write_json(job / "result.json", {"status": "failed", "error": str(exc)})
            finally:
                with guard:
                    active.discard(job.name)

        threading.Thread(target=work, daemon=True).start()

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
        }

    @app.put("/api/defaults")
    def save_defaults(selected: ModelDefaults) -> Any:
        validate_defaults(base, selected)
        with locked(defaults_path.parent):
            write_json(defaults_path, selected.model_dump())
        return options()

    @app.post("/api/materials")
    def upload(files: Annotated[list[UploadFile], File()]) -> Any:
        if not 1 <= len(files) <= 20:
            raise ValueError("请选择 1 到 20 个文件")
        identifier = uuid.uuid4().hex
        folder = root / "materials" / identifier
        folder.mkdir(parents=True, mode=0o700)
        entries: list[dict[str, Any]] = []
        total = 0
        try:
            for index, file in enumerate(files):
                name = file.filename or ""
                if (
                    Path(name).name != name
                    or "\\" in name
                    or Path(name).suffix.lower() not in SUPPORTED
                ):
                    raise ValueError(f"文件名或类型不支持：{name}")
                content = file.file.read(10_000_001)
                if not content:
                    raise ValueError(f"文件为空：{name}")
                total += len(content)
                if len(content) > 10_000_000 or total > 50_000_000:
                    raise ValueError("单文件最多 10 MB，总大小最多 50 MB")
                original = folder / f"{index}{Path(name).suffix.lower()}"
                original.write_bytes(content)
                entries.append(record_upload(original, name))
            if sum(len(item["text"].encode()) for item in entries if item["text"]) > 5_000_000:
                raise ValueError("文本总量最多 5 MB")
            write_json(folder / "manifest.json", entries)
        except Exception:
            shutil.rmtree(folder)
            raise
        return {"id": identifier, "files": entries}

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
            (job / "config.toml").write_text(tomli_w.dumps(config.model_dump(exclude_none=True)))
            load_config(job / "config.toml")
        except Exception:
            shutil.rmtree(job)
            raise
        write_json(job / "settings.json", settings.model_dump())
        write_json(job / "result.json", {"status": "parsing"})
        start(job, lambda: parse_materials(job, config, settings.parsing_timeout_seconds))
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
        was_active = identifier in active
        result = read_json(job / "result.json") if (job / "result.json").exists() else {}
        if (job / "parsing/state.json").exists() and not result.get("error"):
            result.update(read_json(job / "parsing/state.json"))
        if (job / "parsing/result.json").exists():
            result["parsing"] = read_json(job / "parsing/result.json")
            result["parsing_digest"] = digest(result["parsing"])
        if (job / "parsing/call/attempt.json").exists():
            result["parsing_attempt"] = read_json(job / "parsing/call/attempt.json")
        result["materials_approved"] = (job / "parsing/approval.json").exists()
        if (run / "state.json").exists():
            result.update(read_json(run / "state.json"))
        result.update(id=identifier, busy=was_active or identifier in active, path=str(run))
        result["settings"] = read_json(job / "settings.json")
        if (run / "brief.json").exists():
            result["brief"] = read_json(run / "brief.json")
            result["brief_digest"] = digest(result["brief"])
        result["reports"] = {p.stem: read_json(p) for p in run.glob("*-report-*.json")}
        return result

    @app.post("/api/jobs/{identifier}/accept-materials")
    def confirm_materials(identifier: str, approval: MaterialApproval) -> Any:
        job = directory(identifier)
        if identifier in active:
            raise HTTPException(409, "任务正在执行")
        if not (job / "parsing/result.json").exists():
            raise HTTPException(409, "材料尚未完成解析")
        if digest(read_json(job / "parsing/result.json")) != approval.digest:
            raise HTTPException(409, "材料解析结果已变化，请刷新")
        if (job / "parsing/approval.json").exists():
            raise HTTPException(409, "材料已经确认")

        def proceed() -> None:
            from build_skills.workflow import Workflow

            with locked(job):
                if (job / "parsing/approval.json").exists():
                    raise ValueError("材料已经确认")
                accept_materials(job, approval.digest)
                config = load_config(job / "config.toml")
                Workflow(config, identifier).load(create=True)
            invoke(job, "loop")

        start(job, proceed)
        return {"id": identifier}

    def reviewable(job: Path, accepted: str) -> Brief:
        run = job / "runs" / job.name
        if job.name in active:
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

        def revise() -> None:
            from build_skills.workflow import Workflow

            workflow = Workflow(load_config(job / "config.toml"), identifier)
            with locked(workflow.root):
                workflow.load()
                workflow.revise_brief(request.digest, request.answers, request.feedback)
                write_json(job / "result.json", workflow.status())

        start(job, revise)
        return {"id": identifier}

    @app.post("/api/jobs/{identifier}/approve")
    def approve(identifier: str, approval: Approval) -> Any:
        job = directory(identifier)
        brief = reviewable(job, approval.digest)
        if brief.questions:
            raise ValueError("请先回答草案中的问题并更新草案，再确认开始构建")

        def proceed() -> None:
            from build_skills.workflow import Workflow

            workflow = Workflow(load_config(job / "config.toml"), identifier)
            with locked(workflow.root):
                workflow.load()
                workflow.approve(approval.digest)
            invoke(job, "loop")

        start(job, proceed)
        return {"id": identifier}

    @app.post("/api/jobs/{identifier}/resume")
    def resume(identifier: str) -> Any:
        job = directory(identifier)
        if not (job / "runs" / identifier / "state.json").exists():
            raise HTTPException(409, "请先核对材料；解析失败需要新建任务")
        start(job, lambda: invoke(job, "loop"))
        return {"id": identifier}

    @app.get("/api/jobs/{identifier}/download")
    def download(identifier: str) -> FileResponse:
        job = directory(identifier)
        if identifier in active:
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
        with locked(run):
            workflow.load()
            workflow.deliver()
            archive = job / "delivery.zip"
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
                for path in sorted((run / "delivery").rglob("*")):
                    if path.is_file():
                        safe_path(run / "delivery", str(path.relative_to(run / "delivery")))
                        bundle.write(path, str(path.relative_to(run / "delivery")))
        return FileResponse(archive, filename=f"skill-{identifier[:8]}.zip")

    @app.get("/api/jobs/{identifier}/report")
    def report(identifier: str) -> Any:
        return JSONResponse(
            status(identifier)["reports"],
            headers={"Content-Disposition": 'attachment; filename="evaluation.json"'},
        )

    app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True))
    return app
