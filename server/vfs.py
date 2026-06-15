import asyncio
import base64
import posixpath

from kubernetes.stream import stream as k8s_stream

from server.config import SANDBOX_NAMESPACE
from server.k8s import _core, get_sandbox_pod_name


def _safe(rel: str) -> str:
    """Resolve rel within /workspace; raise ValueError on path traversal."""
    clean = posixpath.normpath("/" + rel.lstrip("/"))
    return "/workspace" + clean


async def _pod(sandbox_name: str) -> str:
    pod = await get_sandbox_pod_name(sandbox_name)
    if not pod:
        raise RuntimeError(f"No pod found for sandbox {sandbox_name}")
    return pod


async def _exec(pod_name: str, cmd: list[str]) -> str:
    def _run():
        return k8s_stream(
            _core().connect_get_namespaced_pod_exec,
            pod_name, SANDBOX_NAMESPACE,
            command=cmd, stdin=False, stdout=True, stderr=True, tty=False,
        )
    return await asyncio.to_thread(_run)


async def list_files(sandbox_name: str, rel: str = "") -> list[dict] | None:
    """Return list of {name, path, type, size} for a directory, or None if rel is a file."""
    pod = await _pod(sandbox_name)
    target = _safe(rel) if rel else "/workspace"
    ftype = (await _exec(pod, [
        "sh", "-c",
        f"[ -f {target!r} ] && echo file || ([ -d {target!r} ] && echo dir || echo missing)",
    ])).strip()
    if ftype in ("file", "missing"):
        return None
    out = await _exec(pod, [
        "find", target, "-maxdepth", "1", "-mindepth", "1",
        "-printf", r"%y\t%s\t%P\n",
    ])
    entries = []
    for line in out.strip().splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        ft, size_str, name = parts
        entry_rel = f"{rel}/{name}".lstrip("/") if rel else name
        entries.append({
            "name": name,
            "path": entry_rel,
            "type": "dir" if ft == "d" else "file",
            "size": int(size_str) if size_str.isdigit() else 0,
        })
    return sorted(entries, key=lambda e: (e["type"] == "file", e["name"]))


async def read_file(sandbox_name: str, rel: str) -> bytes:
    pod = await _pod(sandbox_name)
    out = await _exec(pod, ["base64", _safe(rel)])
    return base64.b64decode(out.strip())


async def write_file(sandbox_name: str, rel: str, content: bytes) -> None:
    pod = await _pod(sandbox_name)
    path = _safe(rel)
    parent = posixpath.dirname(path)
    encoded = base64.b64encode(content).decode()

    def _run():
        ws = k8s_stream(
            _core().connect_get_namespaced_pod_exec,
            pod, SANDBOX_NAMESPACE,
            command=["sh", "-c", f"mkdir -p {parent!r} && base64 -d > {path!r}"],
            stdin=True, stdout=True, stderr=True, tty=False,
            _preload_content=False,
        )
        ws.write_stdin(encoded)
        ws.close()
        ws.run_forever(timeout=30)

    await asyncio.to_thread(_run)


async def delete_path(sandbox_name: str, rel: str) -> None:
    if not rel:
        raise ValueError("Cannot delete workspace root")
    pod = await _pod(sandbox_name)
    await _exec(pod, ["rm", "-rf", _safe(rel)])
