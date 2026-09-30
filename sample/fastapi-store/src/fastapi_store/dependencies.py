from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Request
from presto_pay import AsyncPrestoPay

from fastapi_store.config import Settings
from fastapi_store.store import ActivityStore


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_presto(request: Request) -> AsyncPrestoPay:
    return cast(AsyncPrestoPay, request.app.state.presto)


def get_activity(request: Request) -> ActivityStore:
    return cast(ActivityStore, request.app.state.activity)


SettingsDep = Annotated[Settings, Depends(get_settings)]
PrestoDep = Annotated[AsyncPrestoPay, Depends(get_presto)]
ActivityDep = Annotated[ActivityStore, Depends(get_activity)]
