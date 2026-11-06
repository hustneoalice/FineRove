"""Account-specific native workbench appearance and card preferences."""

from __future__ import annotations

import json
import uuid
from typing import Self

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from octop.infra.db.services import RepoBundle


class PreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: str = Field(pattern=r"^(0|[a-f0-9]{32})$")
    preferences: dict[str, JsonValue]

    @model_validator(mode="after")
    def bound_size(self) -> Self:
        if len(json.dumps(self.preferences, ensure_ascii=False).encode("utf-8")) > 65536:
            raise ValueError("preferences exceed 64 KiB")
        return self


class Preferences(PreferencesUpdate):
    pass


class PreferencesManager:
    def __init__(self, repos: RepoBundle) -> None:
        self.settings = repos.settings_repo

    def load(self, user_id: int) -> Preferences:
        raw = self.settings.get(f"finerove.finance.preferences.{user_id}")
        return (
            Preferences.model_validate_json(raw)
            if raw is not None
            else Preferences(revision="0", preferences={})
        )

    def save(self, user_id: int, body: PreferencesUpdate) -> Preferences:
        key = f"finerove.finance.preferences.{user_id}"
        raw = self.settings.get(key)
        revision = Preferences.model_validate_json(raw).revision if raw is not None else "0"
        if body.revision != revision:
            raise HTTPException(409, "finance.market.errors.conflict")
        result = Preferences(revision=uuid.uuid4().hex, preferences=body.preferences)
        if not self.settings.compare_and_set(key, raw, result.model_dump_json()):
            raise HTTPException(409, "finance.market.errors.conflict")
        return result
