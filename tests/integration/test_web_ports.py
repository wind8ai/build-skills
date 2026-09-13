"""Port reservation must be bounded and retain ownership until server startup."""

import errno
import socket
from contextlib import ExitStack

import pytest

from build_skills.web.listener import bind_listener


def test_port_fallback_and_exhaustion() -> None:
    with ExitStack() as stack:
        occupied = [stack.enter_context(bind_listener([0])) for _ in range(4)]
        for listener in occupied:
            listener.listen()
        ports = [listener.getsockname()[1] for listener in occupied]
        with pytest.raises(OSError, match="端口被占用") as error:
            bind_listener(ports)
        assert error.value.errno == errno.EADDRINUSE
        occupied[2].close()
        with bind_listener(ports) as chosen:
            assert chosen.getsockname()[1] == ports[2]
            chosen.listen()
            with pytest.raises(OSError):
                with socket.socket() as contender:
                    contender.bind(chosen.getsockname())


def test_cli_default_port_range(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("uvicorn")
    from typer.testing import CliRunner

    from build_skills.cli import app

    attempts = []

    def unavailable(ports: list[int]) -> socket.socket:
        attempts.extend(ports)
        raise OSError(errno.EADDRINUSE, "端口被占用")

    monkeypatch.setattr("build_skills.web.listener.bind_listener", unavailable)
    result = CliRunner().invoke(app, ["web"])
    assert result.exit_code == 2
    assert attempts == [8321, 8322, 8323, 8324]
    assert "端口被占用" in result.output
    assert "Web workbench:" not in result.output
    attempts.clear()
    result = CliRunner().invoke(app, ["web", "--port", "9000"])
    assert result.exit_code == 2
    assert attempts == [9000]
