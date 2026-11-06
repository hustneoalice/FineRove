"""Small POSIX launcher for FineRove's isolated local server."""

from __future__ import annotations

import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import suppress
from pathlib import Path

from finerove.runtime import _reject_legacy, configure_runtime, runtime_root

START_TIMEOUT = 60
STOP_TIMEOUT = 20


def owns_process(pid: int, nonce: str) -> bool:
    """Require a live process with our exact module/serve/nonce command suffix."""
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "stat=", "-o", "args="],
        capture_output=True,
        text=True,
        check=False,
    )
    fields = result.stdout.strip().split()
    return (
        result.returncode == 0
        and len(fields) >= 6
        and not fields[0].startswith("Z")
        and fields[-4:] == ["-m", "finerove.local_server", "serve", nonce]
    )


def healthy(port: int) -> bool:
    """Check readiness without inheriting HTTP proxy settings."""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
            return bool(response.status == 200)
    except (OSError, urllib.error.URLError):
        return False


def read_state(path: Path) -> tuple[int, str, int] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        pid, nonce, port = data["pid"], data["nonce"], data["port"]
        if type(pid) is int and pid > 0 and isinstance(nonce, str) and nonce and type(port) is int:
            return pid, nonce, port
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def private_file(path: Path) -> int:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.fchmod(fd, 0o600)
    return fd


def operate(action: str, root: Path) -> int:
    state_path, log = root / "local-server.json", root / "local-server.log"
    state = read_state(state_path)
    running = state is not None and owns_process(state[0], state[1])
    if action == "status" or (action == "start" and running):
        if running and state:
            print(f"FineRove 已运行，PID {state[0]}，地址 http://127.0.0.1:{state[2]}")
        else:
            print("FineRove 未运行（没有可验证的本地服务进程）。")
        print(f"日志：{log}")
        return 0
    if action == "stop":
        if not running or state is None:
            print("FineRove 未运行；过期或不匹配的 PID 不会被终止。")
            state_path.unlink(missing_ok=True)
            return 0
        pid, nonce, _ = state
        # Re-check immediately before signalling; never kill by port or process group.
        if owns_process(pid, nonce):
            with suppress(ProcessLookupError):
                os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + STOP_TIMEOUT
        while owns_process(pid, nonce):
            if time.monotonic() >= deadline:
                print(f"停止超时，未强制终止。PID {pid}；日志：{log}")
                return 1
            time.sleep(0.1)
        state_path.unlink(missing_ok=True)
        print("FineRove 已停止，用户数据已保留。")
        return 0
    state_path.unlink(missing_ok=True)
    port = int(os.environ["OCTOP_PORT"])
    if not 1 <= port <= 65535:
        raise ValueError("FINEROVE_PORT 必须在 1 到 65535 之间")
    with socket.socket() as probe:
        # Match uvicorn's restart behavior: recently closed loopback connections
        # must not make a clean stop/start report a false port collision.
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            print(f"端口 {port} 已被占用，未启动或终止任何服务。")
            return 1
    nonce = secrets.token_hex(16)
    with os.fdopen(private_file(log), "ab") as output:
        child = subprocess.Popen(
            [sys.executable, "-m", "finerove.local_server", "serve", nonce],
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    with os.fdopen(private_file(state_path), "w", encoding="utf-8") as output:
        json.dump({"pid": child.pid, "nonce": nonce, "port": port}, output)
    deadline = time.monotonic() + START_TIMEOUT
    while child.poll() is None:
        if healthy(port) and child.poll() is None:
            print(f"FineRove 已启动，PID {child.pid}，地址 http://127.0.0.1:{port}")
            print(f"日志：{log}")
            return 0
        if time.monotonic() >= deadline:
            print(f"启动等待超时，PID {child.pid}；请用 status.sh 检查或 stop.sh 停止。日志：{log}")
            return 1
        time.sleep(0.2)
    state_path.unlink(missing_ok=True)
    print(f"启动失败，服务已退出。日志：{log}")
    return 1


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if os.name != "posix":
        print("本地启停脚本仅支持 macOS / Linux。", file=sys.stderr)
        return 1
    if args[:1] == ["serve"] and len(args) == 2:
        from finerove.cli import main as run

        sys.argv = ["finerove", "run"]
        run()
        return 0
    if len(args) != 1 or args[0] not in {"start", "stop", "status"}:
        print("用法：python -m finerove.local_server start|stop|status", file=sys.stderr)
        return 1
    import fcntl

    try:
        if args[0] == "start":
            root = configure_runtime()
            if os.environ["OCTOP_BIND_HOST"] != "127.0.0.1":
                raise ValueError("本地启停仅允许 FINEROVE_BIND_HOST=127.0.0.1")
            root.chmod(0o700)
            os.environ["FINEROVE_BIND_HOST"] = "127.0.0.1"
        else:
            # Stop/status must work even if the app config is broken or a workspace is large.
            root = runtime_root()
            if not root.exists():
                return operate(args[0], root)
        for name in ("local-server.json", "local-server.lock", "local-server.log"):
            path = root / name
            _reject_legacy(path, "FineRove local control file")
            if path.is_symlink():
                raise ValueError("本地进程状态、锁和日志文件不能使用符号链接")
        with os.fdopen(private_file(root / "local-server.lock"), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return operate(args[0], root)
    except (OSError, ValueError) as exc:
        print(f"FineRove 本地服务操作失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
