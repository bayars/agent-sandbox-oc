#!/bin/bash
set -e

echo "==> Installing Kubernetes Gateway API CRDs (standard channel v1.2.1)..."
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.2.1/standard-install.yaml

echo "==> Waiting for Gateway API CRDs to be established..."
kubectl wait --for condition=established \
  crd/gateways.gateway.networking.k8s.io \
  crd/httproutes.gateway.networking.k8s.io \
  --timeout=60s

echo "==> Installing nginx-gateway-fabric (Gateway controller)..."
helm install ngf oci://ghcr.io/nginx/charts/nginx-gateway-fabric \
  --namespace nginx-gateway \
  --create-namespace \
  --set service.type=LoadBalancer \
  --wait \
  --timeout 5m

echo ""
echo "==> Prerequisites installed. Gateway controller service:"
kubectl get svc -n nginx-gateway
echo ""
echo "Gateway controller IP (MetalLB):"
kubectl get svc -n nginx-gateway -o jsonpath='{.items[0].status.loadBalancer.ingress[0].ip}'
echo ""
