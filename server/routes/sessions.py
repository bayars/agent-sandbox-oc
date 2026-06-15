import json
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from server import db, k8s

router = APIRouter()


def _sse(type_: str, **data) -> str:
    payload = {"type": type_, **data}
    return f"data: {json.dumps(payload)}\n\n"


@router.post("/sessions")
async def create_session():
    session_id = str(uuid.uuid4())[:8]
    namespace = f"session-{session_id}"

    async def event_stream() -> AsyncGenerator[str, None]:
        try:
            await db.create_session(session_id, namespace)
            yield _sse("progress", step="init", msg=f"Session {session_id} initialised.")

            async for msg in k8s.create_session_resources(session_id):
                step = _infer_step(msg)
                yield _sse("progress", step=step, msg=msg)

            await db.update_session(session_id, status="ready")
            yield _sse("ready", session_id=session_id)
            yield _sse("done")

        except Exception as exc:
            await db.update_session(session_id, status="error")
            yield _sse("error", msg=str(exc))

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _infer_step(msg: str) -> str:
    m = msg.lower()
    if "namespace" in m:
        return "namespace"
    if "config" in m:
        return "configmap"
    if "pod" in m or "launch" in m:
        return "pod"
    if "service" in m:
        return "service"
    if "phase" in m or "waiting" in m or "start" in m:
        return "waiting"
    if "health" in m or "verif" in m or "ready" in m:
        return "health"
    return "progress"


@router.get("/sessions")
async def list_sessions():
    sessions = await db.list_sessions()
    result = []
    for s in sessions:
        pod_phase = await k8s.get_pod_phase(s["id"])
        result.append({**s, "pod_phase": pod_phase})
    return result


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    s = await db.get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    pod_phase = await k8s.get_pod_phase(session_id)
    return {**s, "pod_phase": pod_phase}


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str):
    s = await db.get_session(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        await k8s.delete_session_namespace(session_id)
    except Exception:
        pass
    await db.update_session(session_id, status="deleted")
