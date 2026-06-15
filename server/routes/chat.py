import json
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from server import db
from server.opencode_client import OpenCodeClient

router = APIRouter()


class ChatRequest(BaseModel):
    message: str


def _sse(type_: str, **data) -> str:
    return f"data: {json.dumps({'type': type_, **data})}\n\n"


@router.post("/sessions/{session_id}/chat")
async def chat(session_id: str, req: ChatRequest):
    session = await db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["status"] != "ready":
        raise HTTPException(status_code=409, detail=f"Session is not ready (status: {session['status']})")

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            oc = OpenCodeClient(session_id)

            oc_session_id = session.get("oc_session")
            if not oc_session_id:
                oc_session_id = await oc.create_oc_session()
                await db.update_session(session_id, oc_session=oc_session_id)

            async for delta in oc.chat_stream(oc_session_id, req.message):
                yield _sse("token", content=delta)

            yield _sse("done")

        except Exception as exc:
            yield _sse("error", msg=str(exc))

    return StreamingResponse(event_stream(), media_type="text/event-stream")
