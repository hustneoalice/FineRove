"""FineRove entry point; upstream imports happen only after isolation."""

from __future__ import annotations

import json
import sys

import click

from finerove.runtime import configure_runtime, runtime_root


def main() -> None:
    """Run Octop commands against FineRove's independent installation."""
    try:
        if sys.argv[1:] == ["paths"]:
            root = runtime_root()
            click.echo(
                json.dumps(
                    {
                        "root": str(root),
                        "config": str(root / "config.json"),
                        "default_database": str(root / "octop.db"),
                        "workspaces": str(root / "agents"),
                        "default_bind": "127.0.0.1",
                        "default_port": 8098,
                    }
                )
            )
            return
        configure_runtime()
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    from octop.cli.main import cli

    cli(prog_name="finerove")


if __name__ == "__main__":
    main()
