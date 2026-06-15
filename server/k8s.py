import asyncio
import time
from typing import AsyncGenerator

import httpx
from kubernetes import client as k8s_client, config as k8s_config

from server.config import SANDBOX_NAMESPACE, SANDBOX_WARM_POOL, SANDBOX_READY_TIMEOUT

_k8s_loaded = False

SANDBOX_GROUP = "agents.x-k8s.io"
SANDBOX_VERSION = "v1alpha1"
SANDBOX_PLURAL = "sandboxes"

CLAIM_GROUP = "extensions.agents.x-k8s.io"
CLAIM_VERSION = "v1alpha1"
CLAIM_PLURAL = "sandboxclaims"


def _load_k8s():
    global _k8s_loaded
    if not _k8s_loaded:
        try:
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException:
            k8s_config.load_kube_config(context="kind-gateway-lab")
        _k8s_loaded = True


def _custom() -> k8s_client.CustomObjectsApi:
    _load_k8s()
    return k8s_client.CustomObjectsApi()


def _core() -> k8s_client.CoreV1Api:
    _load_k8s()
    return k8s_client.CoreV1Api()


def _sandbox_name(session_id: str) -> str:
    return f"session-{session_id}"


async def create_session_resources(session_id: str) -> AsyncGenerator[str, None]:
    name = _sandbox_name(session_id)
    custom = _custom()

    # 1. Create SandboxClaim — controller fulfils it instantly from the WarmPool
    yield "Claiming sandbox from warm pool..."
    await asyncio.to_thread(
        custom.create_namespaced_custom_object,
        CLAIM_GROUP, CLAIM_VERSION, SANDBOX_NAMESPACE, CLAIM_PLURAL,
        {
            "apiVersion": f"{CLAIM_GROUP}/{CLAIM_VERSION}",
            "kind": "SandboxClaim",
            "metadata": {"name": name, "namespace": SANDBOX_NAMESPACE},
            "spec": {
                "sandboxTemplateRef": {"name": "opencode-template"},
                "warmpool": SANDBOX_WARM_POOL,
            },
        },
    )

    # 2. Wait for the SandboxClaim to be fulfilled (Sandbox name populated)
    yield "Waiting for sandbox to be adopted..."
    deadline = time.time() + SANDBOX_READY_TIMEOUT
    sandbox_name = None

    while time.time() < deadline:
        claim = await asyncio.to_thread(
            custom.get_namespaced_custom_object,
            CLAIM_GROUP, CLAIM_VERSION, SANDBOX_NAMESPACE, CLAIM_PLURAL, name,
        )
        sandbox_ref = claim.get("status", {}).get("sandbox", {})
        if sandbox_ref.get("name"):
            sandbox_name = sandbox_ref["name"]
            break
        await asyncio.sleep(1)
    else:
        raise TimeoutError("SandboxClaim was not fulfilled within timeout")

    # 3. Wait for Sandbox Ready condition
    while time.time() < deadline:
        sandbox = await asyncio.to_thread(
            custom.get_namespaced_custom_object,
            SANDBOX_GROUP, SANDBOX_VERSION, SANDBOX_NAMESPACE, SANDBOX_PLURAL, sandbox_name,
        )
        conditions = sandbox.get("status", {}).get("conditions", [])
        ready = next((c for c in conditions if c.get("type") == "Ready"), None)
        if ready and ready.get("status") == "True":
            # Label the sandbox so it's identifiable as belonging to this session
            await asyncio.to_thread(
                custom.patch_namespaced_custom_object,
                SANDBOX_GROUP, SANDBOX_VERSION, SANDBOX_NAMESPACE, SANDBOX_PLURAL, sandbox_name,
                {"metadata": {"labels": {"agent-sandbox-poc/session": session_id}}},
            )
            yield f"Sandbox {sandbox_name} is ready."
            return
        await asyncio.sleep(2)

    raise TimeoutError(f"Sandbox did not reach Ready within {SANDBOX_READY_TIMEOUT}s")


async def get_sandbox_name_for_claim(session_id: str) -> str | None:
    """Return the Sandbox name adopted by the SandboxClaim for this session."""
    name = _sandbox_name(session_id)
    custom = _custom()
    try:
        claim = await asyncio.to_thread(
            custom.get_namespaced_custom_object,
            CLAIM_GROUP, CLAIM_VERSION, SANDBOX_NAMESPACE, CLAIM_PLURAL, name,
        )
        return claim.get("status", {}).get("sandbox", {}).get("name")
    except k8s_client.exceptions.ApiException:
        return None


async def get_sandbox_pod_name(sandbox_name: str) -> str | None:
    """Return the pod name from the Sandbox annotation (needed for exec/VFS)."""
    custom = _custom()
    try:
        sandbox = await asyncio.to_thread(
            custom.get_namespaced_custom_object,
            SANDBOX_GROUP, SANDBOX_VERSION, SANDBOX_NAMESPACE, SANDBOX_PLURAL, sandbox_name,
        )
        return sandbox.get("metadata", {}).get("annotations", {}).get("agents.x-k8s.io/pod-name")
    except k8s_client.exceptions.ApiException:
        return None


async def delete_session_claim(session_id: str) -> None:
    name = _sandbox_name(session_id)
    custom = _custom()
    try:
        await asyncio.to_thread(
            custom.delete_namespaced_custom_object,
            CLAIM_GROUP, CLAIM_VERSION, SANDBOX_NAMESPACE, CLAIM_PLURAL, name,
        )
    except k8s_client.exceptions.ApiException as e:
        if e.status != 404:
            raise


async def get_sandbox_phase(sandbox_name: str | None) -> str:
    """Return human-readable status for a Sandbox by its actual name."""
    if not sandbox_name:
        return "NotFound"
    custom = _custom()
    try:
        sandbox = await asyncio.to_thread(
            custom.get_namespaced_custom_object,
            SANDBOX_GROUP, SANDBOX_VERSION, SANDBOX_NAMESPACE, SANDBOX_PLURAL, sandbox_name,
        )
        conditions = sandbox.get("status", {}).get("conditions", [])
        ready = next((c for c in conditions if c.get("type") == "Ready"), None)
        if ready:
            return "Ready" if ready.get("status") == "True" else "NotReady"
        return "Pending"
    except k8s_client.exceptions.ApiException:
        return "NotFound"
