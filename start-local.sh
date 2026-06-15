#!/bin/bash
# Local dev mode: run the API server on the host against the kind cluster.
# Requires: pip install -r requirements.txt, PostgreSQL running locally or port-forwarded.
set -e

cd "$(dirname "$0")"

export DATABASE_URL="${DATABASE_URL:-postgresql://sandbox:sandbox123@localhost:5432/agent_sandbox}"
export OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://10.0.0.224:11434/v1}"
export OPENCODE_IMAGE="${OPENCODE_IMAGE:-opencode-sandbox:latest}"

echo "Starting API server at http://localhost:8080"
exec uvicorn server.main:app --host 0.0.0.0 --port 8080 --reload
