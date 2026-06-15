from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response

from server import db, vfs

router = APIRouter()


async def _guard(session_id: str) -> dict:
    session = await db.get_session(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if session["status"] != "ready":
        raise HTTPException(409, f"Session not ready ({session['status']})")
    if not session.get("sandbox_name"):
        raise HTTPException(409, "Session has no sandbox assigned")
    return session


@router.get("/sessions/{session_id}/files")
@router.get("/sessions/{session_id}/files/{path:path}")
async def list_or_download(session_id: str, path: str = "", download: bool = False):
    session = await _guard(session_id)
    sandbox_name = session["sandbox_name"]
    entries = await vfs.list_files(sandbox_name, path)
    if entries is None or download:
        data = await vfs.read_file(sandbox_name, path)
        fname = path.split("/")[-1] if path else "file"
        return Response(
            data,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )
    return entries


@router.post("/sessions/{session_id}/files/{path:path}", status_code=201)
async def upload(session_id: str, path: str, file: UploadFile = File(...)):
    session = await _guard(session_id)
    content = await file.read()
    # If path ends with /, treat it as a directory and append the filename
    # Otherwise use path directly as the target file path
    if path.endswith("/"):
        dest = f"{path.rstrip('/')}/{file.filename}".lstrip("/")
    else:
        dest = path
    await vfs.write_file(session["sandbox_name"], dest, content)
    return {"ok": True, "path": dest}


@router.delete("/sessions/{session_id}/files/{path:path}", status_code=204)
async def delete(session_id: str, path: str):
    session = await _guard(session_id)
    await vfs.delete_path(session["sandbox_name"], path)
