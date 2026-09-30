from __future__ import annotations

from typing import cast

from flask import Flask, current_app
from presto_pay import PrestoPay

from flask_store.config import Settings
from flask_store.store import ActivityStore

_SETTINGS = "flask_store.settings"
_PRESTO = "flask_store.presto"
_STORE = "flask_store.activity"


def init_app(app: Flask, settings: Settings, presto: PrestoPay) -> None:
    app.extensions[_SETTINGS] = settings
    app.extensions[_PRESTO] = presto
    app.extensions[_STORE] = ActivityStore()


def settings() -> Settings:
    return cast(Settings, current_app.extensions[_SETTINGS])


def presto() -> PrestoPay:
    return cast(PrestoPay, current_app.extensions[_PRESTO])


def activity() -> ActivityStore:
    return cast(ActivityStore, current_app.extensions[_STORE])
