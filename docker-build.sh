#!/bin/bash
set -e

CLUSTER_NAME="${KIND_CLUSTER:-gateway-lab}"

echo "==> Building opencode-sandbox image..."
BUILD=$(mktemp -d)
trap "rm -rf $BUILD" EXIT

cp /root/.opencode/bin/opencode "$BUILD/opencode"
cp -r /root/.opencode/node_modules "$BUILD/opencode-node_modules"
cp Dockerfile.opencode "$BUILD/Dockerfile"
docker build -t opencode-sandbox:latest "$BUILD"
echo "    opencode-sandbox:latest built."

echo "==> Building agent-sandbox-api image..."
docker build -t agent-sandbox-api:latest -f Dockerfile.api .
echo "    agent-sandbox-api:latest built."

echo "==> Loading images into kind cluster '$CLUSTER_NAME'..."
kind load docker-image opencode-sandbox:latest --name "$CLUSTER_NAME"
kind load docker-image agent-sandbox-api:latest --name "$CLUSTER_NAME"

echo ""
echo "Done. Both images are available in the '$CLUSTER_NAME' cluster."
docker images | grep -E "opencode-sandbox|agent-sandbox-api"
