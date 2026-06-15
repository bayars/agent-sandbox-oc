# Agent Sandbox POC

A proof-of-concept that deploys isolated [OpenCode](https://opencode.ai) harness instances on a Kind Kubernetes cluster — one sandbox per user session. Users interact with a storytelling AI through a web UI; OpenCode pods are never exposed externally.

## Demo

https://github.com/user-attachments/assets/agent-sandbox-with-oc.mp4

> To embed: drag `agent-sandbox-demo.mp4` into any GitHub issue or PR comment box → copy the generated URL and replace the placeholder above.

---

## Architecture

```
Browser
  │
  ▼ HTTP (172.18.255.203)
Traefik (LoadBalancer, MetalLB)
  │ HTTPRoute → /
  ▼
API Server Pod (FastAPI, ClusterIP :8080)
  ├── PostgreSQL 16              → sessions table
  ├── Kubernetes in-cluster API  → manage session namespaces
  └── httpx proxy ──────────────→ OpenCode pods (ClusterIP, internal only)
                                        ▼
                              namespace: session-{uuid}
                              ├── ConfigMap: opencode-config
                              ├── Pod: opencode (serve :4096)
                              └── Service: opencode-svc (ClusterIP)
                                        ▼
                              Ollama (10.0.0.224:11434)
                              └── qwen2.5:1.5b
```

**Key constraint:** OpenCode pods use `ClusterIP` services only — never accessible outside the cluster. All user traffic goes through the API server proxy.

---

## Features

- **Session isolation** — each session gets its own Kubernetes namespace (`session-{uuid}`) with a dedicated OpenCode pod and ConfigMap
- **SSE progress stream** — `POST /api/sessions` streams live deployment events (namespace → configmap → pod → service → health check → ready)
- **Token streaming** — chat responses stream word-by-word via Server-Sent Events
- **Storytelling agent** — OpenCode configured with a `storyteller` agent persona
- **PostgreSQL persistence** — all sessions recorded with status and OpenCode session ID
- **Helm chart** — single `helm install` deploys the full platform
- **Kubernetes Gateway API** — HTTPRoute via Traefik v3.7

---

## Prerequisites

- Kind cluster named `gateway-lab`
- MetalLB configured with an IP pool (e.g. `172.18.255.200–250`)
- Ollama at `10.0.0.224:11434` with `qwen2.5:1.5b` pulled
- OpenCode binary at `/root/.opencode/bin/opencode` (v1.14.18+)
- Docker, Helm 3, kubectl

### Install Gateway API CRDs + Traefik

```bash
# Gateway API CRDs (experimental channel — required for Traefik v3.7)
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.5.1/experimental-install.yaml

# Traefik
helm repo add traefik https://traefik.github.io/charts
helm repo update
helm install traefik traefik/traefik \
  --namespace traefik --create-namespace \
  --set providers.kubernetesGateway.enabled=true \
  --set gateway.enabled=false \
  --set service.type=LoadBalancer \
  --wait

# Verify GatewayClass is accepted
kubectl get gatewayclass traefik
# NAME      CONTROLLER                      ACCEPTED   AGE
# traefik   traefik.io/gateway-controller   True       ...
```

---

## Deployment

### 1. Build and load images

```bash
./docker-build.sh
```

This copies the OpenCode binary and node_modules into the image, builds both images (`opencode-sandbox:latest` and `agent-sandbox-api:latest`), and loads them into the Kind cluster.

### 2. Install the Helm chart

```bash
helm install agent-sandbox ./chart \
  --namespace agent-sandbox \
  --create-namespace \
  --wait
```

### 3. Get the Gateway IP

```bash
kubectl get gateway -n agent-sandbox
# NAME               CLASS     ADDRESS          PROGRAMMED
# agent-sandbox-gw   traefik   172.18.255.203   True
```

Open `http://172.18.255.203` in your browser.

---

## Usage

### Web UI

Navigate to `http://<GATEWAY_IP>` — click **New Session** to spin up a sandbox, then chat with the storyteller agent.

### API

**Create a session (SSE):**
```bash
curl -sN -X POST http://<GATEWAY_IP>/api/sessions
# data: {"type":"progress","step":"namespace","msg":"Creating namespace session-abc123..."}
# data: {"type":"progress","step":"pod","msg":"Pod phase: Pending..."}
# data: {"type":"progress","step":"health","msg":"OpenCode is ready."}
# data: {"type":"ready","session_id":"abc123"}
# data: {"type":"done"}
```

**Chat (SSE token stream):**
```bash
curl -sN -X POST http://<GATEWAY_IP>/api/sessions/abc123/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Tell me a story about a dragon"}'
# data: {"type":"token","content":"Once"}
# data: {"type":"token","content":" upon"}
# ...
# data: {"type":"done"}
```

**List sessions:**
```bash
curl http://<GATEWAY_IP>/api/sessions
```

**Delete a session:**
```bash
curl -X DELETE http://<GATEWAY_IP>/api/sessions/abc123
# HTTP 204 — namespace is terminated, all resources cleaned up
```

---

## Project Structure

```
.
├── Dockerfile.opencode       # OpenCode pod image (debian:bookworm-slim)
├── Dockerfile.api            # API server image (python:3.13-slim)
├── docker-build.sh           # Build both images and load into Kind
├── prerequisites.sh          # Reference script (see actual steps above)
├── requirements.txt
├── chart/                    # Helm chart
│   ├── Chart.yaml
│   ├── values.yaml
│   └── templates/
│       ├── _helpers.tpl
│       ├── serviceaccount.yaml
│       ├── clusterrole.yaml          # Grants API server namespace/pod/svc management
│       ├── clusterrolebinding.yaml
│       ├── configmap.yaml            # OpenCode storyteller config template
│       ├── deployment.yaml           # API server
│       ├── service.yaml
│       ├── postgres.yaml             # PostgreSQL StatefulSet + Service + Secret
│       ├── gateway.yaml              # Gateway (Traefik, port 8000)
│       └── httproute.yaml            # HTTPRoute → API server
├── server/
│   ├── main.py               # FastAPI app, lifespan DB init
│   ├── config.py             # Env-var driven config
│   ├── db.py                 # asyncpg session CRUD
│   ├── k8s.py                # Namespace/Pod/Service lifecycle
│   ├── opencode_client.py    # httpx wrapper — SSE subscribe-before-send pattern
│   └── routes/
│       ├── sessions.py       # POST/GET/DELETE /api/sessions
│       └── chat.py           # POST /api/sessions/{id}/chat
└── frontend/
    └── index.html            # Single-file React UI (CDN, no build step)
```

---

## Configuration

All values are set in `chart/values.yaml` and injected as environment variables into the API server pod.

| Value | Default | Description |
|-------|---------|-------------|
| `ollama.baseURL` | `http://10.0.0.224:11434/v1` | Ollama API endpoint |
| `opencode.podReadyTimeout` | `120` | Seconds to wait for pod Running |
| `opencode.healthCheckTimeout` | `60` | Seconds to wait for OpenCode health |
| `postgresql.auth.database` | `agent_sandbox` | Database name |
| `postgresql.auth.username` | `sandbox` | Database user |
| `postgresql.auth.password` | `sandbox123` | Database password |
| `gateway.listenerPort` | `8000` | Must match Traefik's internal `web` entrypoint |
| `gateway.className` | `traefik` | GatewayClass name |

---

## How Session Isolation Works

Each `POST /api/sessions` call:

1. Generates a UUID (`session-{uuid}`)
2. Creates a Kubernetes **Namespace** `session-{uuid}`
3. Creates a **ConfigMap** `opencode-config` with the storyteller `opencode.json`
4. Creates a **Pod** `opencode` — runs `opencode serve --port 4096`
5. Creates a **ClusterIP Service** `opencode-svc` on port 4096
6. Polls pod phase until `Running`
7. Polls `GET /global/health` until `{"healthy":true}`
8. Records the session in PostgreSQL and emits `{"type":"ready"}`

The API server reaches each pod at:
```
http://opencode-svc.session-{uuid}.svc.cluster.local:4096
```

`DELETE /api/sessions/{id}` deletes the entire namespace, cascading all resources.

---

## Known Limitations

- **No PersistentVolume** for PostgreSQL — data is lost if the pod restarts (POC only)
- **`imagePullPolicy: Never`** — images must be pre-loaded into the Kind cluster via `kind load docker-image`
- Pod startup takes ~20–30s (OpenCode initialises node_modules on first run)
- One OpenCode pod per session is not horizontally scaled; suitable for demos and POC validation
