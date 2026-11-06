import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from finerove.finance.preferences import PreferencesManager, PreferencesUpdate
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle


def test_preferences_account_scope_and_revision(tmp_path):
    pool = SqlitePool(tmp_path / "isolated.db")
    run_migrations(pool)
    store = PreferencesManager(RepoBundle.from_pool(pool))
    result = store.save(
        1, PreferencesUpdate(revision="0", preferences={"theme": "dark", "cards": {"watch": True}})
    )
    assert store.load(1) == result
    assert store.load(2).preferences == {}
    with pytest.raises(HTTPException) as error:
        store.save(1, PreferencesUpdate(revision="0", preferences={}))
    assert error.value.status_code == 409
    assert (
        store.save(1, PreferencesUpdate(revision=result.revision, preferences={})).preferences == {}
    )


def test_preferences_bound_and_identity_input():
    with pytest.raises(ValidationError):
        PreferencesUpdate(revision="0", preferences={"value": "x" * 65536})
    with pytest.raises(ValidationError):
        PreferencesUpdate(revision="0", preferences={}, user_id=2)
