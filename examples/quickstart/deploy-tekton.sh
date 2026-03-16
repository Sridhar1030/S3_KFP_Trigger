#!/bin/bash
#
# Deploy Tekton EventListener and Triggers
#
# This script deploys the complete Tekton infrastructure for MinIO webhook handling.
#

set -euo pipefail

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "======================================================================"
echo "Deploy Tekton EventListener for MinIO-KFP Trigger"
echo "======================================================================"
echo

# Configuration
NAMESPACE="${NAMESPACE:-s3-kfp-trigger}"
MANIFESTS_DIR="../../manifests/tekton"

echo "Configuration:"
echo "  Namespace: $NAMESPACE"
echo "  Manifests: $MANIFESTS_DIR"
echo

# Check if logged into OpenShift
if ! oc whoami &> /dev/null; then
    echo "ERROR: Not logged into OpenShift cluster"
    echo "Run: oc login --server=https://your-cluster:6443"
    exit 1
fi

echo "Logged in as: $(oc whoami)"
echo "Server: $(oc whoami --show-server)"
echo

# Check if namespace exists
if ! oc get namespace "$NAMESPACE" &> /dev/null; then
    echo "ERROR: Namespace '$NAMESPACE' does not exist"
    echo "Create it first:"
    echo "  oc new-project $NAMESPACE"
    exit 1
fi

echo "Using namespace: $NAMESPACE"
echo

# Step 1: Deploy RBAC (if not already deployed)
echo "Step 1/5: Deploying RBAC resources..."
oc apply -f "$MANIFESTS_DIR/rbac.yaml" -n "$NAMESPACE"
echo -e "${GREEN}✓ RBAC deployed${NC}"
echo

# Step 2: Deploy trigger scripts ConfigMap
echo "Step 2/5: Deploying trigger scripts ConfigMap..."
oc apply -f "$MANIFESTS_DIR/trigger-scripts-configmap.yaml" -n "$NAMESPACE"
echo -e "${GREEN}✓ Trigger scripts ConfigMap deployed${NC}"
echo

# Step 3: Deploy TriggerBinding
echo "Step 3/5: Deploying TriggerBinding..."
oc apply -f "$MANIFESTS_DIR/triggerbinding.yaml" -n "$NAMESPACE"
echo -e "${GREEN}✓ TriggerBinding deployed${NC}"
echo

# Step 4: Deploy TriggerTemplate
echo "Step 4/5: Deploying TriggerTemplate..."
oc apply -f "$MANIFESTS_DIR/triggertemplate.yaml" -n "$NAMESPACE"
echo -e "${GREEN}✓ TriggerTemplate deployed${NC}"
echo

# Step 5: Deploy EventListener
echo "Step 5/5: Deploying EventListener..."
oc apply -f "$MANIFESTS_DIR/eventlistener.yaml" -n "$NAMESPACE"
echo -e "${GREEN}✓ EventListener deployed${NC}"
echo

# Wait for EventListener pod to be ready
echo "Waiting for EventListener pod to be ready..."
sleep 5
oc wait --for=condition=ready pod -l eventlistener=minio-listener -n "$NAMESPACE" --timeout=60s || {
    echo -e "${YELLOW}WARNING: EventListener pod not ready yet. Check status:${NC}"
    echo "  oc get pods -l eventlistener=minio-listener -n $NAMESPACE"
}

# Expose EventListener as a Route (if not already exposed)
echo
echo "Exposing EventListener service as Route..."
if oc get route el-minio-listener -n "$NAMESPACE" &> /dev/null; then
    echo "Route already exists"
else
    oc expose svc el-minio-listener -n "$NAMESPACE"
    echo -e "${GREEN}✓ Route created${NC}"
fi

# Get EventListener URL
EVENTLISTENER_URL=$(oc get route el-minio-listener -n "$NAMESPACE" -o jsonpath='{.spec.host}')

echo
echo "======================================================================"
echo "Deployment Complete!"
echo "======================================================================"
echo
echo "EventListener URL: https://$EVENTLISTENER_URL"
echo
echo "Resources deployed:"
echo "  ✓ ServiceAccount: kfp-trigger-sa"
echo "  ✓ Role: kfp-pipeline-runner"
echo "  ✓ RoleBinding: kfp-trigger-binding"
echo "  ✓ ConfigMap: trigger-scripts"
echo "  ✓ TriggerBinding: minio-event-binding"
echo "  ✓ TriggerTemplate: kfp-trigger-template"
echo "  ✓ EventListener: minio-listener"
echo "  ✓ Route: el-minio-listener"
echo
echo "Next steps:"
echo "  1. Test EventListener with curl:"
echo "     curl -X POST https://$EVENTLISTENER_URL \\"
echo "       -H 'Content-Type: application/json' \\"
echo "       -d @../../tests/fixtures/sample-minio-event.json"
echo
echo "  2. Or run integration test:"
echo "     ../../tests/integration/test_eventlistener.sh"
echo
echo "  3. Configure MinIO webhook:"
echo "     ./configure-webhook.sh"
echo
