#!/bin/sh
set -eu
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if ! command -v uv >/dev/null 2>&1; then
    echo '未找到 uv，请先安装 uv 后重试。' >&2
    exit 1
fi
cd "$repo_dir"
exec uv run python -m finerove.local_server status
