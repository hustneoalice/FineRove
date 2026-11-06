"""User data and optimistic concurrency against the real control-plane store."""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from finerove.finance.watchlist import WatchlistManager, WatchlistUpdate
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle


@pytest.fixture
def services(tmp_path):
    pool = SqlitePool(tmp_path / "control.db")
    run_migrations(pool)
    return RepoBundle.from_pool(pool)


def update(revision="0", items=None, groups=None):
    return WatchlistUpdate(
        revision=revision,
        groups=["默认"] if groups is None else groups,
        items=[] if items is None else items,
    )


def test_user_isolation_empty_clear_and_reopen(services):
    manager = WatchlistManager(services)
    first = manager.save(
        1, update(items=[{"symbol": "600519.SH", "name": "贵州茅台", "groups": ["默认"]}])
    )
    assert first.revision != "0"
    assert manager.load(2).items == []
    assert WatchlistManager(services).load(1) == first
    cleared = manager.save(1, update(first.revision, groups=[]))
    assert WatchlistManager(services).load(1) == cleared
    assert cleared.items == []
    assert cleared.groups == []


def test_stale_revision_cannot_overwrite_or_resurrect(services):
    manager = WatchlistManager(services)
    original = manager.save(1, update())
    with pytest.raises(HTTPException) as error:
        manager.save(1, update())
    assert error.value.status_code == 409
    assert manager.load(1) == original


@pytest.mark.parametrize(
    "body",
    [
        {"items": [{"symbol": "600519.SH", "groups": ["不存在"]}]},
        {"items": [{"symbol": "../auth", "groups": ["默认"]}]},
        {"items": [{"symbol": "600519.SH", "groups": ["默认"]}] * 2},
        {"groups": ["默认", "默认"]},
        {"user_id": 2},
    ],
)
def test_invalid_and_identity_override_rejected(body):
    values = {"revision": "0", "groups": ["默认"], "items": []} | body
    with pytest.raises(ValidationError):
        WatchlistUpdate(**values)


def test_actual_concurrent_writers_only_one_succeeds(services):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    manager = WatchlistManager(services)
    initial = manager.save(1, update())
    barrier = Barrier(2)

    def write(group):
        barrier.wait(timeout=5)
        try:
            return manager.save(1, update(initial.revision, groups=[group]))
        except HTTPException as error:
            return error.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(write, ["A", "B"]))
    assert outcomes.count(409) == 1
    winner = next(result for result in outcomes if result != 409)
    assert manager.load(1) == winner
