"""Set the isolated product environment before importing Octop."""

from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path

# Only deliberate product settings may reach upstream configuration.
_SETTINGS = (
    "BIND_HOST",
    "PORT",
    "DEFAULT_TIMEZONE",
    "LOG_LEVEL",
    "ENABLE_API_DOCS",
    "ENABLE_DASHBOARD",
    "DATABASE_DRIVER",
    "DATABASE_SQLITE_PATH",
    "DATABASE_URL",
    "DATABASE_HOST",
    "DATABASE_PORT",
    "DATABASE_NAME",
    "DATABASE_USER",
    "DATABASE_PASSWORD",
)


def _reject_legacy(path: Path, setting: str) -> Path:
    resolved = path.expanduser().resolve()
    legacy = (Path.home() / ".octop").resolve()
    if resolved == legacy or resolved in legacy.parents or legacy in resolved.parents:
        raise ValueError(
            f"{setting} overlaps the legacy Octop store; choose an independent FineRove path"
        )
    if resolved.exists():
        metadata = resolved.stat()
        if stat.S_ISREG(metadata.st_mode) and metadata.st_nlink > 1:
            raise ValueError(
                f"{setting} uses a hard-linked file; replace it with an independent FineRove file"
            )
    return resolved


def runtime_root() -> Path:
    """Resolve the product root without creating or reading configuration."""
    raw = os.environ.get("FINEROVE_HOME", "").strip()
    return _reject_legacy(Path(raw) if raw else Path.home() / ".finerove", "FINEROVE_HOME")


def _validate_config(root: Path) -> None:
    # Check aliases before reading any product file, including config.json itself.
    if root.exists():
        for child in root.iterdir():
            _reject_legacy(child, "FINEROVE_HOME child")
    for tree in (root / "agents", root / "plugins"):
        for directory, dirs, files in os.walk(tree, followlinks=False):
            for name in dirs + files:
                child = Path(directory) / name
                if child.is_symlink() or child.is_file():
                    _reject_legacy(child, "FineRove workspace/plugin symlink")
    env_file = root / "env"
    if env_file.exists() and re.search(
        r"^\s*(?:export\s+)?OCTOP_[A-Za-z0-9_]+\s*=",
        env_file.read_text(encoding="utf-8"),
        re.MULTILINE,
    ):
        raise ValueError(
            "FineRove env contains OCTOP_* overrides; remove them and use FINEROVE_* process settings"
        )
    config = root / "config.json"
    if not config.exists():
        return
    try:
        raw = json.loads(config.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise ValueError("FineRove config.json cannot be read; fix its JSON and retry") from exc
    if not isinstance(raw, dict):
        raise ValueError("FineRove config.json must contain a JSON object")

    def validate(value: object, key: str = "", parent: str = "") -> None:
        if isinstance(value, dict):
            for name, item in value.items():
                validate(item, str(name), key)
        elif isinstance(value, list):
            for item in value:
                validate(item, key, parent)
        elif (
            isinstance(value, str)
            and (
                key
                in {
                    "sqlite_path",
                    "workspace_dir",
                    "workspace_path",
                    "user_data_dir",
                    "profile_dir",
                }
                or (key == "root" and parent == "workspace")
            )
            and value
        ):
            path = Path(value).expanduser()
            _reject_legacy(path if path.is_absolute() else root / path, "FineRove config.json")

    validate(raw)


def configure_runtime() -> Path:
    """Discard inherited Octop configuration and prepare the private root."""
    root = runtime_root()
    _validate_config(root)
    sqlite_path = os.environ.get("FINEROVE_DATABASE_SQLITE_PATH")
    if sqlite_path:
        path = Path(sqlite_path).expanduser()
        _reject_legacy(path if path.is_absolute() else root / path, "FINEROVE_DATABASE_SQLITE_PATH")
    for name in list(os.environ):
        if name.startswith("OCTOP_"):
            del os.environ[name]
    os.environ["OCTOP_HOME"] = str(root)
    os.environ["OCTOP_BIND_HOST"] = "127.0.0.1"
    os.environ["OCTOP_PORT"] = "8098"
    for setting in _SETTINGS:
        if value := os.environ.get("FINEROVE_" + setting):
            os.environ["OCTOP_" + setting] = value
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root
