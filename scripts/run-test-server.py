"""Isolated synthetic browser acceptance server; never uses real model commands."""

import os
import tempfile
from pathlib import Path

import tomli_w
import uvicorn
from starlette.responses import PlainTextResponse

from build_skills.config import load_config
from build_skills.web.server import create_app

root = Path(__file__).resolve().parents[1]
folder = root / ".build-skills" / "browser-tests"
folder.mkdir(parents=True, exist_ok=True)
data = Path(tempfile.mkdtemp(prefix="run-", dir=folder))
config = load_config(root / "examples/web/config.toml")
parser = data / "builder.py"
parser.write_text(
    "import io,json,runpy,sys,time\n"
    "raw=sys.stdin.read();req=json.loads(raw)\n"
    "if req['stage']=='parse':time.sleep(5)\n"
    "sys.stdin=io.StringIO(raw)\n"
    f"sys.argv=[{str(root / 'tests/fixtures/agent.py')!r},'questions']\n"
    f"runpy.run_path({str(root / 'tests/fixtures/agent.py')!r},run_name='__main__')\n"
)
config.providers[config.roles["build"]].command[1] = str(parser)
config.providers["demo_b"].command += ["fail-once", str(data / "retry-marker")]
config_path = data / "config.toml"
config_path.write_text(tomli_w.dumps(config.model_dump(exclude_none=True)))
app = create_app(config_path, data / "data", allow_local_sources=True)


@app.middleware("http")
async def public_fixture(request, call_next):
    if request.url.path == "/__fixture/notes.md":
        return PlainTextResponse("Copy text without changes. This is a synthetic test.")
    return await call_next(request)


uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("BUILD_SKILLS_TEST_PORT", "8323")))
