import asyncio
import json
from typing import AsyncGenerator

import httpx


class OpenCodeClient:
    def __init__(self, sandbox_name: str):
        from server.config import SANDBOX_NAMESPACE
        # Use the Sandbox's own service FQDN (headless service resolves to pod IP)
        self.base = f"http://{sandbox_name}.{SANDBOX_NAMESPACE}.svc.cluster.local:4096"

    async def health(self) -> bool:
        async with httpx.AsyncClient(timeout=5) as http:
            try:
                r = await http.get(f"{self.base}/global/health")
                return r.status_code == 200
            except Exception:
                return False

    async def create_oc_session(self) -> str:
        async with httpx.AsyncClient(timeout=10) as http:
            r = await http.post(f"{self.base}/session")
            r.raise_for_status()
            return r.json()["id"]

    async def chat_stream(
        self, oc_session_id: str, text: str, agent: str = "storyteller"
    ) -> AsyncGenerator[str, None]:
        """
        Subscribe to /event BEFORE posting the message so no token deltas are missed.
        Yields text delta strings; raises StopAsyncIteration when session.idle arrives.
        """
        token_queue: asyncio.Queue[str | None] = asyncio.Queue()

        async def _event_reader():
            async with httpx.AsyncClient(timeout=None) as http:
                async with http.stream("GET", f"{self.base}/event") as resp:
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[len("data:"):].strip()
                        if not raw:
                            continue
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        props = event.get("properties", {})
                        if props.get("sessionID") != oc_session_id:
                            continue
                        etype = event.get("type", "")
                        if etype == "message.part.delta" and props.get("field") == "text":
                            delta = props.get("delta", "")
                            if delta:
                                await token_queue.put(delta)
                        elif etype == "session.idle":
                            await token_queue.put(None)
                            return

        async def _send_message():
            async with httpx.AsyncClient(timeout=120) as http:
                await http.post(
                    f"{self.base}/session/{oc_session_id}/message",
                    json={"parts": [{"type": "text", "text": text}], "agent": agent},
                )

        reader_task = asyncio.create_task(_event_reader())

        # Let the SSE subscription establish before firing the message
        await asyncio.sleep(0.15)

        # Fire message in background so we can consume the queue concurrently
        asyncio.create_task(_send_message())

        try:
            in_think = False
            buf = ""
            while True:
                token = await asyncio.wait_for(token_queue.get(), timeout=120)
                if token is None:
                    # Flush any remaining buffer outside a think block
                    if buf and not in_think:
                        yield buf
                    break
                buf += token
                # Strip <think>...</think> blocks (used by DeepSeek-R1, Qwen3, etc.)
                # Process until no more complete tags remain in buf
                while True:
                    if not in_think:
                        idx = buf.find("<think>")
                        if idx == -1:
                            # No opening tag — safe to yield everything except a partial tag tail
                            safe = buf if "<" not in buf else buf[:buf.rfind("<")]
                            if safe:
                                yield safe
                                buf = buf[len(safe):]
                            break
                        else:
                            if idx > 0:
                                yield buf[:idx]
                            buf = buf[idx + len("<think>"):]
                            in_think = True
                    else:
                        idx = buf.find("</think>")
                        if idx == -1:
                            buf = ""  # discard while inside think block
                            break
                        buf = buf[idx + len("</think>"):]
                        in_think = False
        finally:
            reader_task.cancel()
            try:
                await reader_task
            except asyncio.CancelledError:
                pass
