"""Account-scoped watchlists in the isolated control-plane store."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Self

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from octop.infra.db.services import RepoBundle

Symbol = Annotated[str, StringConstraints(pattern=r"^[0-9]{6}\.(SH|SZ|BJ)$")]
Group = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


class WatchNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    date: date
    text: str = Field(min_length=1, max_length=2000)


class WatchItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: Symbol
    name: str = Field(default="", max_length=80)
    groups: list[Group] = Field(min_length=1, max_length=50)
    ts: str | None = Field(default=None, max_length=40)
    notes: list[WatchNote] = Field(default_factory=list, max_length=100)


class WatchlistUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: str = Field(pattern=r"^(0|[a-f0-9]{32})$", description="Revision returned by GET")
    groups: list[Group] = Field(max_length=50)
    items: list[WatchItem] = Field(max_length=1000)

    @model_validator(mode="after")
    def validate_membership(self) -> Self:
        if len(set(self.groups)) != len(self.groups):
            raise ValueError("duplicate group")
        if len({item.symbol for item in self.items}) != len(self.items):
            raise ValueError("duplicate symbol")
        for item in self.items:
            if len(set(item.groups)) != len(item.groups) or not set(item.groups) <= set(
                self.groups
            ):
                raise ValueError("invalid group membership")
        return self


class Watchlist(WatchlistUpdate):
    """Persisted snapshot; empty collections represent an intentional clear."""


class WatchlistManager:
    def __init__(self, repos: RepoBundle) -> None:
        self.settings = repos.settings_repo

    def load(self, user_id: int) -> Watchlist:
        raw = self.settings.get(f"finerove.finance.watchlist.{user_id}")
        return (
            Watchlist.model_validate_json(raw)
            if raw is not None
            else Watchlist(revision="0", groups=[], items=[])
        )

    def save(self, user_id: int, update: WatchlistUpdate) -> Watchlist:
        key = f"finerove.finance.watchlist.{user_id}"
        raw = self.settings.get(key)
        revision = Watchlist.model_validate_json(raw).revision if raw is not None else "0"
        if update.revision != revision:
            raise HTTPException(409, "finance.market.errors.conflict")
        result = Watchlist(**(update.model_dump() | {"revision": uuid.uuid4().hex}))
        if not self.settings.compare_and_set(key, raw, result.model_dump_json()):
            raise HTTPException(409, "finance.market.errors.conflict")
        return result
