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

from build_skills.config import Config, digest, load_config
from build_skills.models import Brief, Document
from build_skills.web.materials import SUPPORTED, extract
from build_skills.workspace import read_json, safe_path, write_json


class Selection(Document):
    model: str = ""
    reasoning_effort: str | None = None


class Settings(Document):
    material: str
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    goal: str = Field(min_length=1)
    providers: dict[str, Selection]
    roles: dict[str, str]
    models: list[str] = Field(min_length=1)
    max_rounds: int = Field(ge=1, le=100)
    repetitions: int = Field(ge=1, le=20)
    minimum_score: float = Field(ge=0, le=1)


class Approval(Document):
    brief: Brief
    digest: str


def create_app(config_path: Path, data_root: Path) -> FastAPI:
    base = load_config(config_path)
    root = data_root.resolve()
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
        return {
            "providers": {
                name: {"kind": p.kind, "model": p.model, "reasoning_effort": p.reasoning_effort}
                for name, p in base.providers.items()
            },
            "roles": base.roles,
            "models": base.execution.models,
            "max_rounds": base.limits.max_rounds,
            "repetitions": base.execution.repetitions,
            "minimum_score": base.quality.minimum_score,
            "goal": base.goal,
            "name": base.name,
            "storage": str(root),
            "ocr": bool(shutil.which("tesseract")),
        }

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
                total += len(content)
                if len(content) > 10_000_000 or total > 50_000_000:
                    raise ValueError("单文件最多 10 MB，总大小最多 50 MB")
                original = folder / f"{index}{Path(name).suffix.lower()}"
                original.write_bytes(content)
                try:
                    text = extract(original)
                except Exception as exc:
                    raise ValueError(f"{name}：{exc}") from exc
                target = folder / "text" / f"{index}-{name}.txt"
                target.parent.mkdir(exist_ok=True)
                target.write_text(text)
                entries.append({"name": name, "text": text, "bytes": len(content)})
            if sum(len(item["text"].encode()) for item in entries) > 5_000_000:
                raise ValueError("提取文字总量最多 5 MB")
            write_json(folder / "manifest.json", entries)
        except Exception:
            shutil.rmtree(folder)
            raise
        return {"id": identifier, "files": entries}

    @app.post("/api/jobs")
    def create(settings: Settings) -> Any:
        material = directory(settings.material, "materials")
        if set(settings.providers) != set(base.providers):
            raise ValueError("模型配置必须与本地模板一致")
        config = base.model_copy(deep=True)
        config.name, config.goal = settings.name, settings.goal
        config.roles = settings.roles
        config.execution.models = settings.models
        config.execution.repetitions = settings.repetitions
        config.limits.max_rounds = settings.max_rounds
        config.quality.minimum_score = settings.minimum_score
        for name, selection in settings.providers.items():
            config.providers[name].model = selection.model
            config.providers[name].reasoning_effort = selection.reasoning_effort
        identifier = uuid.uuid4().hex
        job = root / "jobs" / identifier
        config.workspace = str(job / "runs")
        config.materials = [str(material / "text")]
        config = Config.model_validate(config.model_dump())
        job.mkdir(parents=True, mode=0o700)
        try:
            (job / "config.toml").write_text(tomli_w.dumps(config.model_dump(exclude_none=True)))
            load_config(job / "config.toml")
        except Exception:
            shutil.rmtree(job)
            raise
        write_json(job / "settings.json", settings.model_dump())
        from build_skills.workflow import Workflow

        Workflow(config, identifier).load(create=True)
        start(job, lambda: invoke(job, "loop"))
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
        result = read_json(job / "result.json") if (job / "result.json").exists() else {}
        if (run / "state.json").exists():
            result.update(read_json(run / "state.json"))
        result.update(id=identifier, busy=identifier in active, path=str(run))
        if (run / "brief.json").exists():
            result["brief"] = read_json(run / "brief.json")
            result["brief_digest"] = digest(result["brief"])
        result["reports"] = {p.stem: read_json(p) for p in run.glob("*-report-*.json")}
        return result

    @app.post("/api/jobs/{identifier}/approve")
    def approve(identifier: str, approval: Approval) -> Any:
        job = directory(identifier)
        if identifier in active:
            raise HTTPException(409, "任务正在执行")
        run = job / "runs" / identifier
        state = read_json(run / "state.json")
        if state["round"] or state.get("approval"):
            raise ValueError("已经确认或开始构建，请新建任务")
        if digest(read_json(run / "brief.json")) != approval.digest:
            raise HTTPException(409, "审阅内容已变化，请刷新")
        if approval.brief.questions:
            raise ValueError("请解决 questions 中的问题后再确认")

        def proceed() -> None:
            write_json(run / "brief.json", approval.brief.model_dump())
            result = invoke(job, "approve", "--accept", digest(approval.brief.model_dump()))
            if result.get("status") == "approved":
                invoke(job, "loop")

        start(job, proceed)
        return {"id": identifier}

    @app.post("/api/jobs/{identifier}/resume")
    def resume(identifier: str) -> Any:
        job = directory(identifier)
        start(job, lambda: invoke(job, "loop"))
        return {"id": identifier}

    @app.get("/api/jobs/{identifier}/download")
    def download(identifier: str) -> FileResponse:
        job = directory(identifier)
        if identifier in active:
            raise HTTPException(409, "任务正在执行")
        run = job / "runs" / identifier
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
