"""Local launcher ownership and lifecycle safety."""

import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from finerove import local_server as local

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX local launcher")


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # configure_runtime intentionally rewrites the whole process environment.
    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.setenv("FINEROVE_HOME", str(tmp_path))
    monkeypatch.delenv("FINEROVE_BIND_HOST", raising=False)
    # Never probe the user's running default instance from mock-start tests.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    monkeypatch.setenv("FINEROVE_PORT", str(port))
    return tmp_path


@pytest.mark.parametrize(
    "command",
    [
        "S python -m other serve token",
        "S python -m finerove.local_server serve wrong",
        "Z python -m finerove.local_server serve token",
        "",
    ],
)
def test_stop_never_signals_unowned_pid(
    root: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    (root / "local-server.json").write_text(json.dumps({"pid": 42, "nonce": "token", "port": 8098}))
    monkeypatch.setattr(
        local.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess([], 0, command)
    )
    kill = Mock()
    monkeypatch.setattr(local.os, "kill", kill)
    assert local.main(["stop"]) == 0
    kill.assert_not_called()


def test_actual_process_is_not_owned() -> None:
    assert not local.owns_process(os.getpid(), "token")
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        assert not local.owns_process(child.pid, "token")
    finally:
        child.terminate()
        child.wait()


def test_occupied_port_does_not_spawn(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        monkeypatch.setenv("FINEROVE_PORT", str(listener.getsockname()[1]))
        spawn = Mock()
        monkeypatch.setattr(local.subprocess, "Popen", spawn)
        assert local.main(["start"]) == 1
        spawn.assert_not_called()


def test_start_twice_and_stop(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    alive = False

    def spawn(*args: object, **kwargs: object) -> Mock:
        nonlocal alive
        alive = True
        assert kwargs["start_new_session"] is True
        return Mock(pid=42, poll=lambda: None)

    popen = Mock(side_effect=spawn)
    monkeypatch.setattr(local.subprocess, "Popen", popen)
    monkeypatch.setattr(local, "owns_process", lambda *a: alive)
    monkeypatch.setattr(local, "healthy", lambda *a: True)

    def kill(*args: object) -> None:
        nonlocal alive
        alive = False

    monkeypatch.setattr(local.os, "kill", kill)
    assert local.main(["start"]) == 0
    assert local.main(["start"]) == 0
    assert popen.call_count == 1
    assert local.main(["stop"]) == 0
    assert not (root / "local-server.json").exists()
    assert root.stat().st_mode & 0o777 == 0o700
    assert (root / "local-server.log").stat().st_mode & 0o777 == 0o600


def test_nonlocal_binding_is_rejected(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINEROVE_BIND_HOST", "0.0.0.0")
    assert local.main(["start"]) == 1


@pytest.mark.parametrize("exited", [True, False])
def test_failed_start_reports_log_without_exposing_it(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], exited: bool
) -> None:
    monkeypatch.setattr(
        local.subprocess, "Popen", lambda *a, **k: Mock(pid=42, poll=lambda: 1 if exited else None)
    )
    monkeypatch.setattr(local, "healthy", lambda *a: False)
    monkeypatch.setattr(local, "START_TIMEOUT", 0)
    assert local.main(["start"]) == 1
    assert str(root / "local-server.log") in capsys.readouterr().out
    assert (root / "local-server.json").exists() is not exited


def test_invalid_state_is_replaced(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (root / "local-server.json").write_text("invalid")
    monkeypatch.setattr(local.subprocess, "Popen", lambda *a, **k: Mock(pid=42, poll=lambda: None))
    monkeypatch.setattr(local, "healthy", lambda *a: True)
    assert local.main(["start"]) == 0
    assert json.loads((root / "local-server.json").read_text())["pid"] == 42


def test_stop_does_not_require_valid_application_configuration(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (root / "config.json").write_text("{broken configuration")
    (root / "local-server.json").write_text(json.dumps({"pid": 42, "nonce": "token", "port": 8098}))
    alive = True
    monkeypatch.setattr(local, "owns_process", lambda *a: alive)

    def kill(pid: int, sig: int) -> None:
        nonlocal alive
        assert pid == 42
        alive = False

    monkeypatch.setattr(local.os, "kill", kill)
    assert local.main(["stop"]) == 0
    assert not alive
    assert (root / "config.json").read_text() == "{broken configuration"
