"""Own asynchronous worker processes, cross-process activity, and cancellation."""

import fcntl
import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, TextIO

from build_skills.workspace import read_json, safe_path, write_json


def lock_busy(path: Path) -> bool:
    if not path.exists():
        return False
    if path.is_symlink():
        raise ValueError("Symlink lock refused")
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle, fcntl.LOCK_UN)
    return False


class JobRunner:
    def __init__(self) -> None:
        self.guard = threading.Lock()
        self.workers: dict[str, tuple[subprocess.Popen[str], threading.Thread, Path]] = {}
        self.reserved: set[str] = set()
        self.cancelled: set[str] = set()

    def busy(self, job: Path) -> bool:
        with self.guard:
            if job.name in self.reserved:
                return True
        return any(
            lock_busy(path)
            for path in (job / ".job-lock", job / ".lock", job / "runs" / job.name / ".lock")
        )

    def owned(self, job: Path) -> bool:
        with self.guard:
            return job.name in self.workers

    def start(self, job: Path, action: str, payload: dict[str, Any] | None = None) -> None:
        if self.busy(job):
            raise ValueError("任务正在执行，请等待当前操作完成")
        handle: TextIO = safe_path(job, ".job-lock").open("a")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise ValueError("任务正在执行") from exc
        with self.guard:
            self.reserved.add(job.name)
            self.cancelled.discard(job.name)
        process: subprocess.Popen[str] | None = None
        try:
            token = uuid.uuid4().hex
            request = job / "requests" / f"{token}.json"
            write_json(request, {"action": action, "payload": payload or {}})
            operation = {
                "action": action,
                "started": time.time(),
                "owner_pid": os.getpid(),
                "id": token,
            }
            # Persist operation metadata before spawning, so storage failure cannot
            # strand an unmanaged worker that has already started a model call.
            write_json(job / "operation.json", operation)
            process = subprocess.Popen(
                [sys.executable, "-m", "build_skills.web.worker", str(job), str(request)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
        except BaseException:
            with self.guard:
                self.reserved.discard(job.name)
            handle.close()
            raise

        def collect() -> None:
            try:
                stdout, stderr = process.communicate()
                try:
                    result = json.loads(stdout)
                except ValueError:
                    result = {
                        "status": "failed",
                        "error": stderr[-2000:] or "Worker returned no result",
                    }
                with self.guard:
                    cancelled = job.name in self.cancelled
                if cancelled and result.get("status") != "delivered":
                    result["status"] = "interrupted"
                    result["error"] = "当前调用已取消，已保留产物与证据"
                write_json(job / "result.json", result)
                write_json(
                    job / "operation.json",
                    operation | {"finished": time.time(), "status": result.get("status")},
                )
            finally:
                handle.close()
                with self.guard:
                    self.reserved.discard(job.name)
                    self.workers.pop(job.name, None)
                    self.cancelled.discard(job.name)

        thread = threading.Thread(target=collect, daemon=True)
        with self.guard:
            self.workers[job.name] = (process, thread, job)
        try:
            thread.start()
        except BaseException:
            try:
                os.kill(process.pid, signal.SIGINT)
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
            finally:
                handle.close()
                with self.guard:
                    self.reserved.discard(job.name)
                    self.workers.pop(job.name, None)
            raise

    def cancel(self, job: Path) -> None:
        with self.guard:
            item = self.workers.get(job.name)
            if not item:
                raise ValueError("本服务没有拥有该任务进程；请检查运行证据，不能取消未知进程")
            self.cancelled.add(job.name)
            process = item[0]
        try:
            os.kill(process.pid, signal.SIGINT)
        except ProcessLookupError:
            pass

    def close(self) -> None:
        with self.guard:
            items = list(self.workers.values())
        for _, _, job in items:
            try:
                self.cancel(job)
            except ValueError:
                pass  # A worker can finish between the snapshot and cancellation.
        deadline = time.monotonic() + 5
        for process, thread, job in items:
            thread.join(max(0, deadline - time.monotonic()))
            if process.poll() is None:
                # Clean up only a recorded direct child of our own worker.
                state_path = job / "runs" / job.name / "state.json"
                if state_path.exists():
                    pending = read_json(state_path).get("pending_call")
                    if pending:
                        receipt = (
                            job
                            / "runs"
                            / job.name
                            / "calls"
                            / f"{pending['number']:04d}"
                            / "attempt.json"
                        )
                        pid = read_json(receipt).get("pid") if receipt.exists() else None
                        if pid:
                            try:
                                parent = int(
                                    subprocess.check_output(
                                        ["ps", "-o", "ppid=", "-p", str(pid)], text=True
                                    ).strip()
                                )
                                if parent == process.pid:
                                    os.killpg(pid, signal.SIGKILL)
                            except (OSError, ValueError, subprocess.SubprocessError):
                                pass
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
