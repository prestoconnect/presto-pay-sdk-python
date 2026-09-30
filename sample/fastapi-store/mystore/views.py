from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from mystore.checkout import default_form
from mystore.store import ActivityStore

PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_JS_DIR = PACKAGE_DIR / "static" / "js"

_templates = Environment(
    loader=FileSystemLoader(PACKAGE_DIR / "templates"),
    autoescape=select_autoescape(["html"]),
)


def render_index(store: ActivityStore) -> str:
    return _templates.get_template("index.html").render(
        checkout=default_form(),
        recent_webhooks=store.recent_webhooks(),
    )


def render_return(context: dict[str, Any]) -> str:
    return _templates.get_template("return.html").render(missing_txn_ref_num=False, **context)


def render_missing_return(store: ActivityStore) -> str:
    return _templates.get_template("return.html").render(
        missing_txn_ref_num=True,
        txn_ref_num=None,
        recent_webhooks=store.recent_webhooks(),
    )
