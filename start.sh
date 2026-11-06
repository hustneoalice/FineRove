#!/bin/sh
set -eu
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if ! command -v uv >/dev/null 2>&1; then
    echo '未找到 uv，请先安装 uv 后重试。' >&2
    exit 1
fi
cd "$repo_dir"
dashboard_entry="src/octop/dashboard/index.html"
if [ ! -f "$dashboard_entry" ] || [ ! -f src/octop/dashboard/financial-workbench/index.html ] || find dashboard/src dashboard/financial-workbench dashboard/index.html dashboard/package.json dashboard/package-lock.json -type f -newer "$dashboard_entry" -print -quit | grep -q .; then
    if ! command -v npm >/dev/null 2>&1; then
        echo '前端需要构建，但未找到 npm；请先安装 Node.js/npm。' >&2
        exit 1
    fi
    echo '检测到前端源码比构建产物更新，正在构建 FineRove 前端…'
    (cd dashboard && npm run build)
fi
exec uv run python -m finerove.local_server start
