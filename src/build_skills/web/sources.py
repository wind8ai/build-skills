"""Freeze remote sources and materialize only explicitly selected files."""

import ipaddress
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from build_skills.web.materials import SUPPORTED, content_hash, record_upload
from build_skills.workspace import read_json, safe_path, write_json

MAX_FILE = 10_000_000
MAX_TOTAL = 50_000_000
MAX_FILES = 20
MAX_TREE = 5000
EXCLUDED = {".git", ".venv", "node_modules", "__pycache__", ".build-skills"}


def relative_name(name: str) -> str:
    path = Path(name)
    if (
        not name
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in name
        or "\x00" in name
        or str(path) != name
    ):
        raise ValueError(f"非法材料相对路径：{name}")
    return name


def supported(name: str) -> bool:
    return Path(name).suffix.lower() in SUPPORTED or Path(name).name in {"LICENSE", "NOTICE"}


def entry(name: str, size: int, mode: str = "100644") -> dict[str, Any]:
    ignored = any(
        part in EXCLUDED or part == ".env" or part.startswith(".env.") for part in Path(name).parts
    )
    reason = (
        "已排除本地环境或凭据文件"
        if ignored
        else "符号链接/子模块不作为材料"
        if mode not in {"100644", "100755"}
        else "文件超过 10 MB"
        if size > MAX_FILE
        else "暂不支持此文件类型"
        if not supported(name)
        else ""
    )
    return {"path": name, "bytes": size, "supported": not reason, "reason": reason}


def validate_url(url: str, *, allow_local: bool = False) -> str:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError("请提供不含用户名/密码的 HTTP(S) Git 或直接文件链接")
    if parsed.port and parsed.port not in {80, 443} and not allow_local:
        raise ValueError("此来源端口不受支持")
    addresses = socket.getaddrinfo(
        parsed.hostname,
        parsed.port or (443 if parsed.scheme == "https" else 80),
        type=socket.SOCK_STREAM,
    )
    if not allow_local and any(
        not ipaddress.ip_address(addr[4][0]).is_global for addr in addresses
    ):
        raise ValueError("当前仅支持公开网络来源；不能访问本地或内部地址")
    return url


def public_label(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


def fetch_file(folder: Path, url: str, *, allow_local: bool = False) -> dict[str, Any]:
    opener = urllib.request.build_opener(NoRedirect)
    for _ in range(6):
        validate_url(url, allow_local=allow_local)
        try:
            response = opener.open(
                urllib.request.Request(
                    url, headers={"Accept-Encoding": "identity", "User-Agent": "build-skills/0.1"}
                ),
                timeout=15,
            )
            break
        except urllib.error.HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308} and exc.headers.get("Location"):
                url = urllib.parse.urljoin(url, exc.headers["Location"])
                exc.close()
                continue
            raise ValueError(f"文件下载失败（HTTP {exc.code}）") from exc
    else:
        raise ValueError("链接重定向次数过多")
    name = urllib.parse.unquote(Path(urllib.parse.urlsplit(url).path).name)
    with response:
        mime = response.headers.get_content_type()
        if mime == "text/html" and Path(name).suffix.lower() != ".html":
            raise ValueError("该链接是网页；请提供 Git 仓库或直接文件下载链接")
        if not supported(name):
            name = {
                "text/plain": "material.txt",
                "application/pdf": "material.pdf",
                "application/json": "material.json",
            }.get(mime, "")
        if not name:
            raise ValueError("无法识别链接的文件类型")
        relative_name(name)
        length = response.headers.get("Content-Length", "")
        if length.isdigit() and int(length) > MAX_FILE:
            raise ValueError("远程文件超过 10 MB")
        total = 0
        started = time.monotonic()
        path = folder / "download"
        with path.open("xb") as out:
            while True:
                if time.monotonic() - started > 30:
                    raise ValueError("文件下载超过 30 秒")
                chunk = response.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_FILE:
                    raise ValueError("远程文件超过 10 MB")
                out.write(chunk)
    if not total:
        raise ValueError("远程文件为空")
    return {
        "kind": "url",
        "url": public_label(url),
        "files": [entry(name, total)],
        "sha256": content_hash(path),
    }


def git_output(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(
        ["git", "--git-dir", str(repo), *args], stderr=subprocess.PIPE, timeout=15
    )


def fetch_git(folder: Path, url: str, ref: str, *, allow_local: bool = False) -> dict[str, Any]:
    validate_url(url, allow_local=allow_local)
    if urllib.parse.urlsplit(url).query:
        raise ValueError("Git 地址不能包含认证或查询参数，请单独填写分支/标签")
    if ref and (
        ref.startswith("-")
        or subprocess.run(
            ["git", "check-ref-format", "--allow-onelevel", ref], capture_output=True
        ).returncode
    ):
        raise ValueError("请填写有效的分支或标签名称")
    repo = folder / "repository"
    command = [
        "git",
        "-c",
        "protocol.allow=never",
        "-c",
        "protocol.https.allow=always",
        "-c",
        "protocol.http.allow=always",
        "-c",
        "protocol.file.allow=never",
        "-c",
        "protocol.ext.allow=never",
        "-c",
        "credential.helper=",
        "-c",
        "http.extraHeader=",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "http.followRedirects=false",
        "clone",
        "--quiet",
        "--bare",
        "--depth=1",
        "--single-branch",
        "--no-tags",
    ]
    if ref:
        command += ["--branch", ref]
    command += ["--", url, str(repo)]
    environment = os.environ.copy() | {"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/usr/bin/false"}
    with (folder / "fetch.log").open("wb") as log:
        process = subprocess.Popen(
            command, stdout=log, stderr=log, env=environment, start_new_session=True
        )
        deadline = time.monotonic() + 45
        try:
            while process.poll() is None:
                if time.monotonic() > deadline:
                    raise ValueError("仓库读取超过 45 秒")
                if (
                    repo.exists()
                    and sum(p.stat().st_size for p in repo.rglob("*") if p.is_file()) > MAX_TOTAL
                ):
                    raise ValueError("仓库副本超过 50 MB，请缩小仓库范围")
                time.sleep(0.1)
            if process.returncode:
                raise ValueError("仓库读取失败。请检查公开地址、分支和网络；私有仓库支持尚未启用")
        finally:
            if process.poll() is None:
                import signal

                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
    commit = git_output(repo, "rev-parse", "HEAD").decode().strip()
    files = []
    for record in git_output(repo, "ls-tree", "-r", "-l", "-z", commit).split(b"\0"):
        if not record:
            continue
        header, raw_name = record.split(b"\t", 1)
        mode, _, _, raw_size = header.decode().split()
        name = raw_name.decode("utf-8")
        relative_name(name)
        files.append(entry(name, int(raw_size) if raw_size != "-" else 0, mode))
        if len(files) > MAX_TREE:
            raise ValueError("仓库文件树超过 5,000 项")
    return {"kind": "git", "url": public_label(url), "ref": ref, "commit": commit, "files": files}


def import_url(
    root: Path, kind: str, url: str, ref: str = "", *, allow_local: bool = False
) -> dict[str, Any]:
    identifier = uuid.uuid4().hex
    folder = root / "sources" / identifier
    folder.mkdir(parents=True, mode=0o700)
    try:
        source = (
            fetch_git(folder, url, ref, allow_local=allow_local)
            if kind == "git"
            else fetch_file(folder, url, allow_local=allow_local)
        )
        source["id"] = identifier
        write_json(folder / "source.json", source)
        return source
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        shutil.rmtree(folder)
        if isinstance(exc, ValueError):
            raise
        raise ValueError("来源读取失败，请检查网络与地址") from exc


def select_files(root: Path, identifier: str, paths: list[str]) -> dict[str, Any]:
    folder = safe_path(root / "sources", identifier)
    source = read_json(folder / "source.json")
    if source["kind"] == "url" and content_hash(folder / "download") != source["sha256"]:
        raise ValueError("来源副本已变化，请重新导入")
    choices = {item["path"]: item for item in source["files"]}
    if not 1 <= len(paths) <= MAX_FILES or len(set(paths)) != len(paths):
        raise ValueError("请选择 1 到 20 个不同文件")
    for name in paths:
        relative_name(name)
        if name not in choices or not choices[name]["supported"]:
            raise ValueError(f"该文件不能作为材料：{name}")
    material_id = uuid.uuid4().hex
    target = root / "materials" / material_id
    target.mkdir(parents=True, mode=0o700)
    entries = []
    total = 0
    try:
        for index, name in enumerate(paths):
            data = (
                git_output(folder / "repository", "show", source["commit"] + ":" + name)
                if source["kind"] == "git"
                else (folder / "download").read_bytes()
            )
            if data.startswith(b"version https://git-lfs.github.com/spec/v1"):
                raise ValueError(f"{name} 是 Git LFS 指针，请直接上传原文件")
            total += len(data)
            if len(data) > MAX_FILE or total > MAX_TOTAL:
                raise ValueError("所选文件超过上传大小限制")
            original = target / f"{index}{Path(name).suffix.lower()}"
            original.write_bytes(data)
            item = record_upload(original, name)
            item["origin"] = {
                key: source[key] for key in ("kind", "url", "commit") if key in source
            }
            entries.append(item)
        if sum(len(item["text"].encode()) for item in entries if item["text"]) > 5_000_000:
            raise ValueError("所选文字超过 5 MB")
        write_json(target / "manifest.json", entries)
    except Exception:
        shutil.rmtree(target)
        raise
    return {
        "id": material_id,
        "files": entries,
        "origin": {key: source[key] for key in ("kind", "url", "commit") if key in source},
    }
