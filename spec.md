# Feature Specification: Agent Sandbox POC

**Feature Branch**: `main`

**Created**: 2026-06-15

**Status**: Implemented

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Create an isolated AI agent session (Priority: P1)

A developer opens the web UI and clicks "+ New" to spin up a fresh, isolated OpenCode agent
session. Within seconds, a pre-warmed sandbox pod is allocated and the session is ready to
accept messages — no waiting for container image pulls.

**Why this priority**: This is the entry point for every other capability. Without reliable,
fast session creation nothing else works.

**Independent Test**: Open `http://<gateway-ip>/`, click "+ New", and observe that a session
appears in the sidebar with status `ready` in under 10 seconds.

**Acceptance Scenarios**:

1. **Given** the web UI is open, **When** the user clicks "+ New", **Then** a progress stream
   appears showing "Claiming sandbox from warm pool…", "Sandbox is ready.", and the session
   ID becomes visible with status `ready`.
2. **Given** a `SandboxWarmPool` with 2 replicas is configured, **When** a session is created,
   **Then** the `POST /api/sessions` SSE stream completes without a pod scheduling delay
   (warm pod is claimed, not cold-started).
3. **Given** session creation fails (e.g., warm pool exhausted), **When** the error occurs,
   **Then** the UI displays an error message and the session record is marked `error`.

---

### User Story 2 - Chat with the AI agent (Priority: P1)

The user selects a ready session and sends a message. The agent responds token-by-token in
real time, streamed back to the browser.

**Why this priority**: Core product value — without chat the system is a container launcher,
not an agent platform.

**Independent Test**: With a ready session, send `POST /api/sessions/{id}/chat` with
`{"message": "say hi"}` and observe `data: {"type":"token", ...}` lines followed by
`data: {"type":"done"}`.

**Acceptance Scenarios**:

1. **Given** a `ready` session, **When** the user types a message and presses Enter,
   **Then** the assistant response appears token-by-token without page reload.
2. **Given** a chat message is in-flight, **When** tokens arrive, **Then** the streaming
   cursor is visible and the send button is disabled.
3. **Given** the agent has bash/read/write/edit tools enabled, **When** the user asks "list
   files in /workspace", **Then** the agent invokes the bash tool and returns actual directory
   contents instead of saying it cannot access the filesystem.

---

### User Story 3 - Browse and manage workspace files (Priority: P2)

Each session has a persistent `/workspace` directory. The user can browse the file tree,
upload files for the agent to work with, and download files the agent has produced — all
from the web UI without SSH.

**Why this priority**: Without file access the user has no way to supply inputs or retrieve
outputs; the agent's work is invisible.

**Independent Test**: With a ready session, call `GET /api/sessions/{id}/files` (empty `[]`),
upload a file with `POST /api/sessions/{id}/files/hello.txt`, list again (file appears), then
`DELETE /api/sessions/{id}/files/hello.txt` (204). Open the UI and verify the Files panel
reflects each operation.

**Acceptance Scenarios**:

1. **Given** a ready session, **When** the user opens the Files panel, **Then** the contents
   of `/workspace` are listed as a browsable directory tree.
2. **Given** the file browser is showing a directory, **When** the user clicks a folder,
   **Then** the panel navigates into that directory with a breadcrumb showing the path.
3. **Given** the file browser is open, **When** the user clicks "Upload" and selects a file,
   **Then** the file is written to the current directory in the sandbox and appears in the listing.
4. **Given** a file exists in the workspace, **When** the user clicks it, **Then** the file
   is downloaded to the browser.
5. **Given** the agent just responded, **When** the chat `done` event fires, **Then** the
   file panel auto-refreshes so newly-created files appear without manual reload.

---

### User Story 4 - Delete a session and release resources (Priority: P2)

The user deletes a session from the sidebar. The associated `SandboxClaim` is deleted and
the controller recycles the sandbox back into the warm pool (or deprovisions it), freeing
cluster resources.

**Why this priority**: Without cleanup, the cluster fills with idle sandboxes.

**Independent Test**: `DELETE /api/sessions/{id}` returns 204; the `SandboxClaim`
`session-{id}` no longer exists in the cluster; the session DB record is marked `deleted`.

**Acceptance Scenarios**:

1. **Given** an active session, **When** the user clicks "Delete", **Then** the session
   disappears from the sidebar and the backend deletes the `SandboxClaim`.
2. **Given** a deleted session, **When** `GET /api/sessions/{id}` is called, **Then** the
   record is returned with `status: deleted`.

---

### User Story 5 - Workspace persists across pod restarts (Priority: P3)

If the sandbox pod crashes and restarts, the `/workspace` PVC retains all files. The user
can continue the session without losing generated artefacts.

**Why this priority**: Reliability requirement — crash resilience is necessary for production
trust but does not affect the core demo flow.

**Independent Test**: Create a file in `/workspace`, delete the pod manually, wait for it to
restart, and verify the file is still present via `GET /api/sessions/{id}/files`.

**Acceptance Scenarios**:

1. **Given** a file exists in the sandbox workspace, **When** the pod is restarted, **Then**
   `GET /api/sessions/{id}/files` still returns the file after the pod is `Running` again.

---

### Edge Cases

- What happens when all warm pool pods are claimed? Session creation waits up to
  `SANDBOX_READY_TIMEOUT` seconds for the controller to provision a new sandbox, then
  returns a timeout error.
- What happens when a path traversal is attempted via the file API (e.g., `../etc/passwd`)?
  `_safe()` in `server/vfs.py` normalises the path and rejects any result that escapes
  `/workspace` with a `ValueError` → HTTP 500.
- What happens when the LLM is unavailable (Ollama unreachable)? OpenCode returns a 5xx;
  the chat stream emits `{"type":"error","msg":"..."}` and the UI shows the error inline.
- What happens when two users claim a pod from the same warm pool simultaneously? The
  `kubernetes-sigs/agent-sandbox` controller handles atomic assignment; each claim gets
  exactly one sandbox.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provision an isolated OpenCode sandbox per user session using
  `kubernetes-sigs/agent-sandbox` `SandboxClaim` CRDs — not raw pod or namespace creation.
- **FR-002**: The system MUST maintain a `SandboxWarmPool` so that new sessions are
  allocated in under 10 seconds without waiting for a container image pull.
- **FR-003**: The system MUST stream chat responses token-by-token to the browser via
  Server-Sent Events.
- **FR-004**: The API server MUST subscribe to the OpenCode `/event` SSE bus before sending
  the user message to ensure no tokens are missed.
- **FR-005**: Each sandbox pod MUST have a `/workspace` ReadWriteOnce PVC mounted,
  persisted independently of the pod lifecycle.
- **FR-006**: The system MUST expose REST endpoints for listing, downloading, uploading, and
  deleting files in the sandbox's `/workspace` via Kubernetes `pods/exec`.
- **FR-007**: The web UI MUST provide a 3-column layout: session list, chat, and workspace
  file browser.
- **FR-008**: The file browser MUST auto-refresh after each completed chat turn.
- **FR-009**: Session metadata (sandbox name, OpenCode session ID, status) MUST be persisted
  in PostgreSQL so the API server can reconnect after restarts.
- **FR-010**: Deleting a session MUST delete the `SandboxClaim`, triggering controller-side
  resource cleanup.
- **FR-011**: The LLM model and Ollama endpoint MUST be configurable via Helm values
  (`ollama.model`, `ollama.baseURL`) without rebuilding the container image.
- **FR-012**: The agent MUST have `bash`, `read`, `write`, and `edit` tools enabled so it
  can interact with the filesystem.

### Key Entities

- **Session**: Ties a browser user to one `SandboxClaim` and one OpenCode session. Fields:
  `id`, `status`, `sandbox_name`, `oc_session`, `created_at`, `updated_at`.
- **SandboxClaim** (`extensions.agents.x-k8s.io/v1alpha1`): One per session; claims a
  pre-warmed Sandbox from the WarmPool. Name: `session-{id}`.
- **Sandbox** (`agents.x-k8s.io/v1alpha1`): Managed by the `kubernetes-sigs/agent-sandbox`
  controller. Retains its WarmPool name (e.g. `opencode-warmpool-abc12`). Labelled with
  `agent-sandbox-poc/session: {id}` after assignment.
- **SandboxTemplate** (`extensions.agents.x-k8s.io/v1alpha1`): Blueprint defining the
  OpenCode container spec, PVC template, headless service, and config mount. Named
  `opencode-template`.
- **SandboxWarmPool** (`extensions.agents.x-k8s.io/v1alpha1`): Maintains N ready pods.
  Name: `opencode-warmpool`, replicas: 2.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new session reaches `status: ready` in under 10 seconds from `POST
  /api/sessions` (warm pool path).
- **SC-002**: The first chat token appears in the browser within 5 seconds of sending a
  message (assumes local Ollama).
- **SC-003**: File upload (`POST /api/sessions/{id}/files/{path}`) and listing (`GET`) round-
  trip successfully for files up to 10 MB.
- **SC-004**: Deleting a session results in the `SandboxClaim` being absent from the cluster
  within 5 seconds.
- **SC-005**: The Files panel reflects agent-created files without user-initiated refresh
  after each chat turn completes.
- **SC-006**: Zero pod-level namespace isolation failures — each session's sandbox is
  inaccessible from other session pods (enforced by the agent-sandbox controller's network
  policy layer or `networkPolicyManagement: Unmanaged` with platform-level isolation).

---

## Assumptions

- The cluster runs `kubernetes-sigs/agent-sandbox` v0.4.6+ with all four CRDs installed:
  `sandboxes`, `sandboxclaims`, `sandboxtemplates`, `sandboxwarmpools`.
- An Ollama instance is reachable at the URL configured in `ollama.baseURL` (default:
  `http://10.0.0.224:11434/v1`) and the selected model (default: `nemotron-3-nano:4b`) has
  been pulled.
- The Kubernetes cluster provides a default `StorageClass` (e.g., `standard`) that supports
  `ReadWriteOnce` PVCs for the `/workspace` volume.
- Container images (`opencode-sandbox:latest`, `agent-sandbox-api:latest`) are pre-loaded
  into the cluster nodes (Kind: via `kind load docker-image`; production: registry push).
- The cluster uses Traefik as the Gateway API controller, with an `HTTPRoute` at the
  configured gateway IP forwarding traffic to the API service on port 8080.
- Mobile support and user authentication are out of scope for this POC; the API is
  unauthenticated and single-tenant.
- The `nemotron-3-nano:4b` model's tool-calling quality is acceptable for a POC; production
  would use a larger, instruction-tuned model.
