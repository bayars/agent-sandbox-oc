import json
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from server import db, k8s

router = APIRouter()


def _sse(type_: str, **data) -> str:
    return f"data: {json.dumps({'type': type_, **data})}\n\n"


@router.post("/sessions")
async def create_session():
    session_id = str(uuid.uuid4())[:8]

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            await db.create_session(session_id)
            yield _sse("progress", step="init", msg=f"Session {session_id} initialised.")

            async for msg in k8s.create_session_resources(session_id):
                yield _sse("progress", step=_infer_step(msg), msg=msg)

            sandbox_name = await k8s.get_sandbox_name_for_claim(session_id)
            await db.update_session(session_id, status="ready", sandbox_name=sandbox_name)
            yield _sse("ready", session_id=session_id)
            yield _sse("done")

        except Exception as exc:
            await db.update_session(session_id, status="error")
            yield _sse("error", msg=str(exc))

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _infer_step(msg: str) -> str:
    m = msg.lower()
    if "claim" in m or "warm" in m:
        return "claim"
    if "adopt" in m:
        return "waiting"
    if "ready" in m:
        return "health"
    return "progress"


@router.get("/sessions")
async def list_sessions():
    sessions = await db.list_sessions()
    result = []
    for s in sessions:
        phase = await k8s.get_sandbox_phase(s.get("sandbox_name"))
        result.append({**s, "pod_phase": phase})
    return result


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    s = await db.get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    return {**s, "pod_phase": await k8s.get_sandbox_phase(s.get("sandbox_name"))}


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str):
    s = await db.get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        await k8s.delete_session_claim(session_id)
    except Exception:
        pass
    await db.update_session(session_id, status="deleted")
