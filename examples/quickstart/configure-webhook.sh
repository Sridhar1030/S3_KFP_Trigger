#!/bin/bash
#
# Configure MinIO webhook to send events to Tekton EventListener
#
# Prerequisites:
# - mc (MinIO Client) installed and configured (run setup-minio-bucket.sh first)
# - EventListener deployed and accessible
#

set -euo pipefail

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "======================================================================"
echo "Configure MinIO Webhook for S3-KFP Trigger"
echo "======================================================================"
echo

# Configuration
MINIO_ALIAS="${MINIO_ALIAS:-local}"
BUCKET_NAME="${BUCKET_NAME:-ml-datasets}"
WEBHOOK_NAME="${WEBHOOK_NAME:-tekton}"
NAMESPACE="${NAMESPACE:-s3-kfp-trigger}"

echo "Configuration:"
echo "  MinIO Alias: $MINIO_ALIAS"
echo "  Bucket Name: $BUCKET_NAME"
echo "  Webhook Name: $WEBHOOK_NAME"
echo "  EventListener Namespace: $NAMESPACE"
echo

# Check if mc is installed
if ! command -v mc &> /dev/null; then
    echo -e "${RED}ERROR: MinIO Client (mc) not found${NC}"
    echo "Run: ./setup-minio-bucket.sh first"
    exit 1
fi

# Check if oc is available
if ! command -v oc &> /dev/null; then
    echo -e "${RED}ERROR: oc CLI not found${NC}"
    exit 1
fi

# Get EventListener URL
echo "Getting EventListener URL from OpenShift..."

EVENTLISTENER_ROUTE=$(oc get route el-minio-listener -n "$NAMESPACE" -o jsonpath='{.spec.host}' 2>/dev/null || echo "")

if [ -z "$EVENTLISTENER_ROUTE" ]; then
    echo -e "${RED}ERROR: EventListener route not found${NC}"
    echo "Deploy EventListener first:"
    echo "  ./deploy-tekton.sh"
    exit 1
fi

EVENTLISTENER_URL="https://$EVENTLISTENER_ROUTE"

# For cluster-internal access (MinIO inside the cluster)
EVENTLISTENER_INTERNAL="http://el-minio-listener.${NAMESPACE}.svc.cluster.local:8080"

echo -e "${GREEN}✓ EventListener found${NC}"
echo "  External URL: $EVENTLISTENER_URL"
echo "  Internal URL: $EVENTLISTENER_INTERNAL"
echo

# Determine which URL to use
echo "Which EventListener URL should MinIO use?"
echo "  1. Internal (cluster-internal, recommended if MinIO is in the cluster)"
echo "  2. External (via Route, required if MinIO is outside the cluster)"
echo

read -p "Select (1 or 2) [default: 1]: " URL_CHOICE

if [ "${URL_CHOICE:-1}" = "2" ]; then
    WEBHOOK_ENDPOINT="$EVENTLISTENER_URL"
    echo "Using external URL: $WEBHOOK_ENDPOINT"
else
    WEBHOOK_ENDPOINT="$EVENTLISTENER_INTERNAL"
    echo "Using internal URL: $WEBHOOK_ENDPOINT"
fi

echo

# Check if webhook already configured
echo "Checking for existing webhook configuration..."

EXISTING_ARN=$(mc event list "$MINIO_ALIAS/$BUCKET_NAME" --json 2>/dev/null | grep -o "arn:minio:sqs::${WEBHOOK_NAME}:webhook" || echo "")

if [ -n "$EXISTING_ARN" ]; then
    echo -e "${YELLOW}WARNING: Webhook '$WEBHOOK_NAME' already configured for bucket '$BUCKET_NAME'${NC}"
    echo
    read -p "Remove existing webhook and reconfigure? (y/N): " REMOVE_EXISTING

    if [[ "$REMOVE_EXISTING" =~ ^[Yy]$ ]]; then
        echo "Removing existing webhook..."
        mc event remove "$MINIO_ALIAS/$BUCKET_NAME" "arn:minio:sqs::${WEBHOOK_NAME}:webhook" || {
            echo -e "${YELLOW}WARNING: Could not remove existing webhook${NC}"
        }
        echo
    else
        echo "Keeping existing configuration. Exiting."
        exit 0
    fi
fi

# Configure MinIO webhook notification target
echo "Step 1: Configuring MinIO notification target..."

# Check MinIO server version to determine config command format
mc admin info "$MINIO_ALIAS" &> /dev/null || {
    echo -e "${RED}ERROR: Cannot access MinIO admin functions${NC}"
    echo "Ensure you have admin credentials configured"
    exit 1
}

# Set webhook notification config
mc admin config set "$MINIO_ALIAS" notify_webhook:${WEBHOOK_NAME} \
    endpoint="$WEBHOOK_ENDPOINT" \
    queue_limit="1000" \
    queue_dir="" \
    client_cert="" \
    client_key="" || {
    echo -e "${RED}ERROR: Failed to configure webhook notification target${NC}"
    exit 1
}

echo -e "${GREEN}✓ Notification target configured${NC}"
echo

# Restart MinIO to apply configuration
echo "Step 2: Restarting MinIO to apply configuration..."

mc admin service restart "$MINIO_ALIAS" || {
    echo -e "${YELLOW}WARNING: Could not restart MinIO service${NC}"
    echo "You may need to restart MinIO manually:"
    echo "  oc rollout restart deployment/minio -n minio"
    echo
    read -p "Continue anyway? (y/N): " CONTINUE
    if [[ ! "$CONTINUE" =~ ^[Yy]$ ]]; then
        exit 1
    fi
}

echo "Waiting for MinIO to restart..."
sleep 5

# Verify MinIO is accessible
mc ls "$MINIO_ALIAS" > /dev/null || {
    echo -e "${RED}ERROR: MinIO not accessible after restart${NC}"
    exit 1
}

echo -e "${GREEN}✓ MinIO restarted${NC}"
echo

# Add event notification to bucket
echo "Step 3: Adding event notification to bucket..."

mc event add "$MINIO_ALIAS/$BUCKET_NAME" \
    "arn:minio:sqs::${WEBHOOK_NAME}:webhook" \
    --event put,post || {
    echo -e "${RED}ERROR: Failed to add event notification${NC}"
    exit 1
}

echo -e "${GREEN}✓ Event notification added${NC}"
echo

# List configured events
echo "Configured bucket events:"
mc event list "$MINIO_ALIAS/$BUCKET_NAME"
echo

# Test webhook
echo "Step 4: Testing webhook with file upload..."

# Create test file
echo "test,data,webhook" > /tmp/webhook-test.csv
echo "1,2,3" >> /tmp/webhook-test.csv

# Upload test file
mc cp /tmp/webhook-test.csv "$MINIO_ALIAS/$BUCKET_NAME/webhook-test-$(date +%s).csv" || {
    echo -e "${RED}ERROR: Failed to upload test file${NC}"
    exit 1
}

echo -e "${GREEN}✓ Test file uploaded${NC}"
echo

# Check for TaskRun creation
echo "Checking for TaskRun creation (waiting 10 seconds)..."
sleep 10

TASKRUNS=$(oc get taskruns -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l | tr -d ' ')

if [ "$TASKRUNS" -gt 0 ]; then
    echo -e "${GREEN}✓ TaskRun(s) found!${NC}"
    echo
    echo "Recent TaskRuns:"
    oc get taskruns -n "$NAMESPACE" --sort-by=.metadata.creationTimestamp | tail -5
    echo
    echo "Latest TaskRun logs:"
    LATEST_TR=$(oc get taskruns -n "$NAMESPACE" --sort-by=.metadata.creationTimestamp -o name | tail -1)
    oc logs "$LATEST_TR" -n "$NAMESPACE" --tail=20 2>/dev/null || echo "Logs not available yet"
else
    echo -e "${YELLOW}WARNING: No TaskRuns created${NC}"
    echo
    echo "Troubleshooting steps:"
    echo "  1. Check EventListener logs:"
    echo "     oc logs -l eventlistener=minio-listener -n $NAMESPACE"
    echo
    echo "  2. Verify webhook is configured:"
    echo "     mc event list $MINIO_ALIAS/$BUCKET_NAME"
    echo
    echo "  3. Test webhook manually:"
    echo "     curl -X POST $WEBHOOK_ENDPOINT -H 'Content-Type: application/json' -d '{\"Records\":[{\"s3\":{\"bucket\":{\"name\":\"test\"},\"object\":{\"key\":\"file.csv\"}}}]}'"
fi

echo
echo "======================================================================"
echo "MinIO Webhook Configuration Complete!"
echo "======================================================================"
echo
echo "Summary:"
echo "  ✓ Webhook target configured: $WEBHOOK_NAME"
echo "  ✓ Webhook endpoint: $WEBHOOK_ENDPOINT"
echo "  ✓ Bucket events enabled: $BUCKET_NAME"
echo "  ✓ Event types: put, post"
echo
echo "Next steps:"
echo "  1. Upload files to MinIO to trigger pipelines:"
echo "     mc cp mydata.csv $MINIO_ALIAS/$BUCKET_NAME/"
echo
echo "  2. Monitor TaskRun creation:"
echo "     oc get taskruns -n $NAMESPACE --watch"
echo
echo "  3. View TaskRun logs:"
echo "     oc logs <taskrun-name> -n $NAMESPACE"
echo
echo "  4. Update pipeline routing configuration:"
echo "     oc edit configmap pipeline-mappings -n $NAMESPACE"
echo
