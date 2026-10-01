from __future__ import annotations

from fastapi import APIRouter, Request, Response
from presto_pay import NotifyAck

from fastapi_store import services
from fastapi_store.dependencies import ActivityDep, PrestoDep

router = APIRouter()


@router.post("/presto/notify")
async def presto_notify(request: Request, presto: PrestoDep, activity: ActivityDep) -> Response:
    status, ack = await services.accept_webhook(presto, activity, await request.body())
    return Response(ack, status_code=status, media_type=NotifyAck.CONTENT_TYPE)
