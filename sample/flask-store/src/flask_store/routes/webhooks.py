from __future__ import annotations

from flask import Blueprint, Response, request
from presto_pay import NotifyAck

from flask_store import extensions, services

bp = Blueprint("webhooks", __name__)


@bp.post("/presto/notify")
def presto_notify() -> Response:
    status, ack = services.accept_webhook(extensions.presto(), extensions.activity(), request.get_data())
    return Response(ack, status=status, content_type=NotifyAck.CONTENT_TYPE)
