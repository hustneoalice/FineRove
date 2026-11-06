"""FineRove must never inherit the installed Octop runtime."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(os, "environ", os.environ.copy())
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    for name in list(os.environ):
        if name.startswith(("OCTOP_", "FINEROVE_")):
            monkeypatch.delenv(name)
    return home


def test_isolation_discards_all_inherited_octop_settings(isolated, monkeypatch):
    from finerove.runtime import configure_runtime

    for name in ("HOME", "DATABASE_URL", "DATABASE_SQLITE_PATH", "JWT_SECRET", "USER", "PORT"):
        monkeypatch.setenv("OCTOP_" + name, "legacy-secret")
    root = configure_runtime()
    assert root == isolated / ".finerove"
    assert {k: v for k, v in os.environ.items() if k.startswith("OCTOP_")} == {
        "OCTOP_HOME": str(root),
        "OCTOP_BIND_HOST": "127.0.0.1",
        "OCTOP_PORT": "8098",
    }
    assert not (isolated / ".octop").exists()
    if os.name == "posix":
        assert root.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("suffix", [".octop", ".octop/child", ".", ".."])
def test_rejects_legacy_overlap(isolated, monkeypatch, suffix):
    from finerove.runtime import configure_runtime

    monkeypatch.setenv("FINEROVE_HOME", str(isolated / suffix))
    with pytest.raises(ValueError, match="FINEROVE_HOME"):
        configure_runtime()


@pytest.mark.skipif(os.name != "posix", reason="symlink creation requires privileges on Windows")
def test_rejects_symlink_alias(isolated, monkeypatch):
    from finerove.runtime import configure_runtime

    (isolated / "alias").symlink_to(isolated / ".octop", target_is_directory=True)
    monkeypatch.setenv("FINEROVE_HOME", str(isolated / "alias"))
    with pytest.raises(ValueError, match="FINEROVE_HOME"):
        configure_runtime()


def test_explicit_product_environment_and_relative_root(isolated, monkeypatch):
    from finerove.runtime import configure_runtime

    monkeypatch.chdir(isolated)
    monkeypatch.setenv("FINEROVE_HOME", "independent")
    monkeypatch.setenv("FINEROVE_PORT", "8101")
    monkeypatch.setenv("FINEROVE_DEFAULT_TIMEZONE", "UTC")
    root = configure_runtime()
    assert root == isolated / "independent"
    assert os.environ["OCTOP_PORT"] == "8101"
    assert os.environ["OCTOP_DEFAULT_TIMEZONE"] == "UTC"


@pytest.mark.parametrize("section", ["database", "workspace"])
def test_config_cannot_redirect_into_legacy(isolated, section):
    from finerove.runtime import configure_runtime

    root = isolated / ".finerove"
    root.mkdir()
    raw = {
        section: {
            "sqlite_path" if section == "database" else "root": str(isolated / ".octop" / "data")
        }
    }
    (root / "config.json").write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="config.json"):
        configure_runtime()


@pytest.mark.parametrize("entry", ["finerove", "octop"])
def test_paths_subprocess_has_no_octop_import_or_side_effects(tmp_path, entry):
    root = tmp_path / "new-product"
    env = {**os.environ, "FINEROVE_HOME": str(root), "OCTOP_HOME": str(tmp_path / "legacy")}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"from finerove.cli import main; import sys; sys.argv = ['{entry}', 'paths']; main(); assert not any(n == 'octop' or n.startswith('octop.') for n in sys.modules)",
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["root"] == str(root)
    assert not root.exists()
    assert not (tmp_path / "legacy").exists()


def test_rejects_persisted_octop_environment_override(isolated):
    from finerove.runtime import configure_runtime

    root = isolated / ".finerove"
    root.mkdir()
    (root / "env").write_text('OCTOP_DATABASE_URL="postgresql://secret@old/db"\n')
    with pytest.raises(ValueError, match="env") as error:
        configure_runtime()
    assert "secret" not in str(error.value)


def test_explicit_database_path_cannot_overlap_legacy(isolated, monkeypatch):
    from finerove.runtime import configure_runtime

    monkeypatch.setenv("FINEROVE_DATABASE_SQLITE_PATH", str(isolated / ".octop" / "old.db"))
    with pytest.raises(ValueError, match="FINEROVE_DATABASE_SQLITE_PATH"):
        configure_runtime()


def test_packaged_entrypoints_both_use_isolation():
    import importlib.metadata

    entries = importlib.metadata.distribution("octop").entry_points
    for name in ("finerove", "octop"):
        assert next(e.value for e in entries if e.name == name) == "finerove.cli:main"


def test_octop_import_occurs_only_after_isolation(tmp_path):
    root = tmp_path / "runtime"
    source = """
import builtins, os, sys
original = builtins.__import__
def checked(name, *args, **kwargs):
    if name == 'octop' or name.startswith('octop.'):
        assert os.environ['OCTOP_HOME'] == os.environ['FINEROVE_HOME']
        assert 'OCTOP_DATABASE_URL' not in os.environ
    return original(name, *args, **kwargs)
builtins.__import__ = checked
from finerove.cli import main
sys.argv = ['finerove', '--help']
main()
"""
    env = {**os.environ, "FINEROVE_HOME": str(root), "OCTOP_DATABASE_URL": "legacy-secret"}
    result = subprocess.run([sys.executable, "-c", source], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "Usage: finerove" in result.stdout
    assert not (root / "config.json").exists()


def test_execution_root_is_not_a_persistent_storage_target(isolated):
    from finerove.runtime import configure_runtime

    root = isolated / ".finerove"
    root.mkdir()
    (root / "config.json").write_text(
        json.dumps({"backend": {"root_dir": Path(isolated.anchor).as_posix()}})
    )
    assert configure_runtime() == root


@pytest.mark.skipif(os.name != "posix", reason="symlink creation requires privileges on Windows")
def test_rejects_nested_workspace_symlink_to_legacy(isolated):
    from finerove.runtime import configure_runtime

    workspace = isolated / ".finerove" / "agents" / "agent1"
    workspace.mkdir(parents=True)
    (workspace / "alias").symlink_to(isolated / ".octop", target_is_directory=True)
    with pytest.raises(ValueError, match="workspace"):
        configure_runtime()


@pytest.mark.parametrize("filename", ["config.json", "env", "octop.db"])
def test_rejects_hardlinked_runtime_files_before_reading(isolated, filename):
    from finerove.runtime import configure_runtime

    legacy = isolated / ".octop"
    legacy.mkdir()
    original = legacy / filename
    original.write_text("legacy-secret-invalid-json")
    root = isolated / ".finerove"
    root.mkdir()
    try:
        os.link(original, root / filename)
    except OSError:
        pytest.skip("hard links unavailable on this filesystem")
    with pytest.raises(ValueError, match="hard.link") as error:
        configure_runtime()
    assert "legacy-secret" not in str(error.value)


def test_rejects_configured_database_hardlink(isolated, monkeypatch):
    from finerove.runtime import configure_runtime

    legacy = isolated / ".octop"
    legacy.mkdir()
    original = legacy / "octop.db"
    original.write_bytes(b"legacy-database")
    alias = isolated / "database-alias.db"
    try:
        os.link(original, alias)
    except OSError:
        pytest.skip("hard links unavailable on this filesystem")
    monkeypatch.setenv("FINEROVE_DATABASE_SQLITE_PATH", str(alias))
    with pytest.raises(ValueError, match="hard.link"):
        configure_runtime()


def test_setup_password_is_generated_independently_of_legacy_home(isolated):
    from finerove.runtime import configure_runtime

    legacy = isolated / "octop-login.txt"
    legacy.write_text("old-installation-secret")
    root = configure_runtime()
    password_file = root / "octop-login.txt"
    assert password_file.is_file()
    password = password_file.read_text().strip()
    assert len(password) >= 20
    assert password != legacy.read_text()
    assert legacy.read_text() == "old-installation-secret"
    configure_runtime()
    assert password_file.read_text().strip() == password
    if os.name == "posix":
        assert password_file.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.name != "posix", reason="symlinks require privileges on Windows")
def test_setup_password_cannot_alias_legacy_home(isolated):
    from finerove.runtime import configure_runtime

    legacy = isolated / "octop-login.txt"
    legacy.write_text("old-installation-secret")
    root = isolated / ".finerove"
    root.mkdir()
    (root / "octop-login.txt").symlink_to(legacy)
    with pytest.raises(ValueError):
        configure_runtime()
    assert legacy.read_text() == "old-installation-secret"


@pytest.mark.skipif(os.name != "posix", reason="symlinks require privileges on Windows")
@pytest.mark.parametrize("kind", ["dangling_symlink", "directory"])
def test_setup_password_must_be_an_independent_regular_file(isolated, kind):
    from finerove.runtime import configure_runtime

    legacy = isolated / "octop-login.txt"
    legacy.write_text("old-installation-secret")
    root = isolated / ".finerove"
    root.mkdir()
    path = root / "octop-login.txt"
    if kind == "dangling_symlink":
        path.symlink_to(isolated / "missing-password")
    else:
        path.mkdir()
    with pytest.raises(ValueError, match="credential"):
        configure_runtime()
    assert legacy.read_text() == "old-installation-secret"
    assert not (isolated / "missing-password").exists()


def test_deleted_product_credential_does_not_read_legacy_password(isolated):
    from finerove.runtime import configure_runtime
    from octop.infra.setup.password_file import ensure_password, read_password

    legacy = isolated / "octop-login.txt"
    legacy.write_text("old-installation-secret")
    root = configure_runtime()
    product = root / "octop-login.txt"
    product.unlink()
    assert read_password(root, legacy_home=isolated) is None
    ensure_password(root, legacy_home=isolated)
    assert product.read_text().strip() != "old-installation-secret"
    assert legacy.read_text() == "old-installation-secret"
