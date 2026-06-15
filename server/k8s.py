import asyncio
import time
from typing import AsyncGenerator

import httpx
from kubernetes import client as k8s_client, config as k8s_config

from server.config import OPENCODE_IMAGE, POD_READY_TIMEOUT, HEALTH_CHECK_TIMEOUT, get_opencode_config

_k8s_loaded = False


def _load_k8s():
    global _k8s_loaded
    if not _k8s_loaded:
        try:
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException:
            # Fallback for local dev
            k8s_config.load_kube_config(context="kind-gateway-lab")
        _k8s_loaded = True


def _core() -> k8s_client.CoreV1Api:
    _load_k8s()
    return k8s_client.CoreV1Api()


def _ns_name(session_id: str) -> str:
    return f"session-{session_id}"


async def create_session_resources(session_id: str) -> AsyncGenerator[str, None]:
    ns = _ns_name(session_id)
    v1 = _core()

    # 1. Namespace
    yield f"Creating namespace {ns}..."
    await asyncio.to_thread(
        v1.create_namespace,
        k8s_client.V1Namespace(
            metadata=k8s_client.V1ObjectMeta(
                name=ns,
                labels={"app": "agent-sandbox", "session": session_id},
            )
        ),
    )

    # 2. ConfigMap
    yield "Uploading storyteller config..."
    await asyncio.to_thread(
        v1.create_namespaced_config_map,
        ns,
        k8s_client.V1ConfigMap(
            metadata=k8s_client.V1ObjectMeta(name="opencode-config", namespace=ns),
            data={"opencode.json": get_opencode_config()},
        ),
    )

    # 3. Pod
    yield "Launching OpenCode pod..."
    pod_spec = k8s_client.V1PodSpec(
        restart_policy="Never",
        containers=[
            k8s_client.V1Container(
                name="opencode",
                image=OPENCODE_IMAGE,
                image_pull_policy="Never",
                ports=[k8s_client.V1ContainerPort(container_port=4096)],
                working_dir="/app",
                volume_mounts=[
                    k8s_client.V1VolumeMount(
                        name="config",
                        mount_path="/app/opencode.json",
                        sub_path="opencode.json",
                    )
                ],
                resources=k8s_client.V1ResourceRequirements(
                    requests={"memory": "128Mi", "cpu": "100m"},
                    limits={"memory": "512Mi", "cpu": "1000m"},
                ),
            )
        ],
        volumes=[
            k8s_client.V1Volume(
                name="config",
                config_map=k8s_client.V1ConfigMapVolumeSource(name="opencode-config"),
            )
        ],
    )
    await asyncio.to_thread(
        v1.create_namespaced_pod,
        ns,
        k8s_client.V1Pod(
            metadata=k8s_client.V1ObjectMeta(
                name="opencode",
                namespace=ns,
                labels={"app": "opencode", "session": session_id},
            ),
            spec=pod_spec,
        ),
    )

    # 4. ClusterIP service (internal only)
    yield "Creating internal service..."
    await asyncio.to_thread(
        v1.create_namespaced_service,
        ns,
        k8s_client.V1Service(
            metadata=k8s_client.V1ObjectMeta(name="opencode-svc", namespace=ns),
            spec=k8s_client.V1ServiceSpec(
                type="ClusterIP",
                selector={"app": "opencode", "session": session_id},
                ports=[k8s_client.V1ServicePort(port=4096, target_port=4096)],
            ),
        ),
    )

    # 5. Wait for pod Running
    yield "Waiting for pod to start..."
    deadline = time.time() + POD_READY_TIMEOUT
    last_phase = ""
    while time.time() < deadline:
        pod = await asyncio.to_thread(v1.read_namespaced_pod, "opencode", ns)
        phase = pod.status.phase or "Unknown"
        if phase != last_phase:
            yield f"Pod phase: {phase}..."
            last_phase = phase
        if phase == "Running":
            break
        if phase in ("Failed", "Succeeded"):
            raise RuntimeError(f"Pod entered terminal phase: {phase}")
        await asyncio.sleep(2)
    else:
        raise TimeoutError(f"Pod did not reach Running within {POD_READY_TIMEOUT}s")

    # 6. Wait for OpenCode /global/health
    yield "Verifying OpenCode API health..."
    svc_url = f"http://opencode-svc.{ns}.svc.cluster.local:4096"
    deadline = time.time() + HEALTH_CHECK_TIMEOUT
    async with httpx.AsyncClient(timeout=5) as http:
        while time.time() < deadline:
            try:
                r = await http.get(f"{svc_url}/global/health")
                if r.status_code == 200:
                    yield "OpenCode is ready."
                    return
            except Exception:
                pass
            await asyncio.sleep(2)
    raise TimeoutError(f"OpenCode did not respond to health check within {HEALTH_CHECK_TIMEOUT}s")


async def delete_session_namespace(session_id: str) -> None:
    ns = _ns_name(session_id)
    v1 = _core()
    await asyncio.to_thread(
        v1.delete_namespace,
        ns,
        body=k8s_client.V1DeleteOptions(propagation_policy="Foreground"),
    )


async def get_pod_phase(session_id: str) -> str:
    ns = _ns_name(session_id)
    v1 = _core()
    try:
        pod = await asyncio.to_thread(v1.read_namespaced_pod, "opencode", ns)
        return pod.status.phase or "Unknown"
    except k8s_client.exceptions.ApiException as e:
        if e.status == 404:
            return "NotFound"
        return "Unknown"
