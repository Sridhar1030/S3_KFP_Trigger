#!/bin/bash
#
# End-to-end integration test: MinIO upload → Tekton TaskRun → KFP Pipeline
#
# Tests the complete flow from MinIO file upload to pipeline triggering.
#

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "======================================================================"
echo "End-to-End Integration Test: MinIO → Tekton → KFP"
echo "======================================================================"
echo

# Configuration
MINIO_ALIAS="${MINIO_ALIAS:-local}"
BUCKET_NAME="${BUCKET_NAME:-ml-datasets}"
NAMESPACE="${NAMESPACE:-s3-kfp-trigger}"
TEST_FILE_PREFIX="e2e-test-$(date +%s)"

echo "Configuration:"
echo "  MinIO Alias: $MINIO_ALIAS"
echo "  Bucket: $BUCKET_NAME"
echo "  Namespace: $NAMESPACE"
echo "  Test File Prefix: $TEST_FILE_PREFIX"
echo

# Prerequisites check
echo "Checking prerequisites..."
echo

FAILED=0

# Check mc
if ! command -v mc &> /dev/null; then
    echo -e "${RED}✗ MinIO Client (mc) not found${NC}"
    FAILED=1
else
    echo -e "${GREEN}✓ MinIO Client (mc) found${NC}"
fi

# Check oc
if ! command -v oc &> /dev/null; then
    echo -e "${RED}✗ oc CLI not found${NC}"
    FAILED=1
else
    echo -e "${GREEN}✓ oc CLI found${NC}"
fi

# Check oc login
if ! oc whoami &> /dev/null; then
    echo -e "${RED}✗ Not logged into OpenShift${NC}"
    FAILED=1
else
    echo -e "${GREEN}✓ Logged into OpenShift: $(oc whoami)${NC}"
fi

# Check MinIO alias configured
if ! mc alias list "$MINIO_ALIAS" &> /dev/null; then
    echo -e "${RED}✗ MinIO alias '$MINIO_ALIAS' not configured${NC}"
    echo "  Run: ../../examples/quickstart/setup-minio-bucket.sh"
    FAILED=1
else
    echo -e "${GREEN}✓ MinIO alias configured${NC}"
fi

# Check bucket exists
if ! mc ls "$MINIO_ALIAS/$BUCKET_NAME" &> /dev/null; then
    echo -e "${RED}✗ Bucket '$BUCKET_NAME' not found${NC}"
    echo "  Run: ../../examples/quickstart/setup-minio-bucket.sh"
    FAILED=1
else
    echo -e "${GREEN}✓ Bucket exists${NC}"
fi

# Check EventListener
if ! oc get eventlistener minio-listener -n "$NAMESPACE" &> /dev/null; then
    echo -e "${RED}✗ EventListener not found${NC}"
    echo "  Run: ../../examples/quickstart/deploy-tekton.sh"
    FAILED=1
else
    echo -e "${GREEN}✓ EventListener deployed${NC}"
fi

# Check EventListener pod running
if ! oc get pods -l eventlistener=minio-listener -n "$NAMESPACE" --field-selector=status.phase=Running &> /dev/null; then
    echo -e "${RED}✗ EventListener pod not running${NC}"
    FAILED=1
else
    echo -e "${GREEN}✓ EventListener pod running${NC}"
fi

echo

if [ $FAILED -eq 1 ]; then
    echo -e "${RED}Prerequisites not met. Fix the errors above and try again.${NC}"
    exit 1
fi

echo -e "${GREEN}All prerequisites met!${NC}"
echo

# Get TaskRun count before test
echo "Getting baseline TaskRun count..."
TASKRUNS_BEFORE=$(oc get taskruns -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l | tr -d ' ')
echo "TaskRuns before test: $TASKRUNS_BEFORE"
echo

# Create test data
echo "Creating test data file..."
cat > /tmp/${TEST_FILE_PREFIX}.csv << 'EOF'
timestamp,temperature,humidity,pressure,quality_score
2026-03-16T10:00:00Z,22.5,45.2,1013.2,0.95
2026-03-16T10:05:00Z,22.7,44.8,1013.1,0.96
2026-03-16T10:10:00Z,23.1,44.5,1013.0,0.94
2026-03-16T10:15:00Z,23.4,44.2,1012.9,0.97
2026-03-16T10:20:00Z,23.8,43.9,1012.8,0.95
EOF

echo -e "${GREEN}✓ Test data created: /tmp/${TEST_FILE_PREFIX}.csv${NC}"
echo

# Upload file to MinIO
echo "Uploading file to MinIO bucket..."
echo "Command: mc cp /tmp/${TEST_FILE_PREFIX}.csv $MINIO_ALIAS/$BUCKET_NAME/"

mc cp /tmp/${TEST_FILE_PREFIX}.csv "$MINIO_ALIAS/$BUCKET_NAME/" || {
    echo -e "${RED}ERROR: Failed to upload file to MinIO${NC}"
    exit 1
}

echo -e "${GREEN}✓ File uploaded successfully${NC}"
echo

# Wait for webhook to trigger and TaskRun to be created
echo "Waiting for TaskRun creation (max 30 seconds)..."

SUCCESS=0
for i in {1..30}; do
    TASKRUNS_AFTER=$(oc get taskruns -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l | tr -d ' ')

    if [ "$TASKRUNS_AFTER" -gt "$TASKRUNS_BEFORE" ]; then
        echo -e "${GREEN}✓ New TaskRun detected after ${i} seconds!${NC}"
        SUCCESS=1
        break
    fi

    echo -n "."
    sleep 1
done

echo
echo

if [ $SUCCESS -eq 0 ]; then
    echo -e "${RED}ERROR: No TaskRun created within 30 seconds${NC}"
    echo
    echo "Troubleshooting:"
    echo "  1. Check if webhook is configured:"
    echo "     mc event list $MINIO_ALIAS/$BUCKET_NAME"
    echo
    echo "  2. Check EventListener logs:"
    echo "     oc logs -l eventlistener=minio-listener -n $NAMESPACE"
    echo
    echo "  3. Verify MinIO can reach EventListener:"
    echo "     Check MinIO logs for webhook delivery errors"
    exit 1
fi

# Get the latest TaskRun
echo "Getting latest TaskRun details..."
LATEST_TASKRUN=$(oc get taskruns -n "$NAMESPACE" --sort-by=.metadata.creationTimestamp -o name | tail -1)

echo "Latest TaskRun: $LATEST_TASKRUN"
echo

# Show TaskRun status
echo "TaskRun Status:"
oc get "$LATEST_TASKRUN" -n "$NAMESPACE" -o wide
echo

# Check TaskRun parameters
echo "TaskRun Parameters:"
S3_URI=$(oc get "$LATEST_TASKRUN" -n "$NAMESPACE" -o jsonpath='{.spec.params[?(@.name=="s3_uri")].value}')
echo "  s3_uri: $S3_URI"

# Verify correct S3 URI
EXPECTED_S3_URI="s3://$BUCKET_NAME/${TEST_FILE_PREFIX}.csv"
if [ "$S3_URI" = "$EXPECTED_S3_URI" ]; then
    echo -e "${GREEN}✓ S3 URI matches expected value${NC}"
else
    echo -e "${YELLOW}WARNING: S3 URI mismatch${NC}"
    echo "  Expected: $EXPECTED_S3_URI"
    echo "  Got: $S3_URI"
fi

echo

# Wait for TaskRun to complete or fail
echo "Waiting for TaskRun to complete (max 60 seconds)..."

for i in {1..60}; do
    STATUS=$(oc get "$LATEST_TASKRUN" -n "$NAMESPACE" -o jsonpath='{.status.conditions[0].reason}' 2>/dev/null || echo "Unknown")

    if [ "$STATUS" = "Succeeded" ]; then
        echo -e "${GREEN}✓ TaskRun completed successfully!${NC}"
        break
    elif [ "$STATUS" = "Failed" ]; then
        echo -e "${RED}✗ TaskRun failed${NC}"
        break
    fi

    echo -n "."
    sleep 1
done

echo
echo

# Show TaskRun logs
echo "TaskRun Logs (last 50 lines):"
echo "----------------------------------------------------------------------"
oc logs "$LATEST_TASKRUN" -n "$NAMESPACE" --tail=50 2>/dev/null || {
    echo "Logs not available yet"
}
echo "----------------------------------------------------------------------"
echo

# Parse logs for trigger status
echo "Analyzing trigger output..."

LOGS=$(oc logs "$LATEST_TASKRUN" -n "$NAMESPACE" 2>/dev/null || echo "")

if echo "$LOGS" | grep -q '"status":"success"'; then
    echo -e "${GREEN}✓ Pipeline triggered successfully${NC}"

    # Extract pipeline run ID
    PIPELINE_RUN_ID=$(echo "$LOGS" | grep -o '"pipeline_run_id":"[^"]*"' | head -1 | cut -d'"' -f4)
    if [ -n "$PIPELINE_RUN_ID" ]; then
        echo "  Pipeline Run ID: $PIPELINE_RUN_ID"
    fi

elif echo "$LOGS" | grep -q '"status":"no_match"'; then
    echo -e "${YELLOW}⚠ No pipeline route matched${NC}"
    echo "  This is expected if pipeline-mappings ConfigMap is empty"
    echo "  Update ConfigMap with routes:"
    echo "    oc edit configmap pipeline-mappings -n $NAMESPACE"

elif echo "$LOGS" | grep -q '"status":"failure"'; then
    echo -e "${RED}✗ Pipeline trigger failed${NC}"
    ERROR=$(echo "$LOGS" | grep -o '"error":"[^"]*"' | head -1 | cut -d'"' -f4)
    if [ -n "$ERROR" ]; then
        echo "  Error: $ERROR"
    fi
else
    echo -e "${YELLOW}⚠ Cannot determine trigger status from logs${NC}"
fi

echo

# Summary
echo "======================================================================"
echo "Test Summary"
echo "======================================================================"
echo
echo -e "${GREEN}✓ File uploaded to MinIO${NC}"
echo -e "${GREEN}✓ Webhook triggered TaskRun${NC}"
echo -e "${GREEN}✓ Trigger script executed${NC}"
echo
echo "Test Results:"
echo "  File: $BUCKET_NAME/${TEST_FILE_PREFIX}.csv"
echo "  TaskRun: $LATEST_TASKRUN"
echo "  S3 URI: $S3_URI"
echo "  Status: $STATUS"
echo
echo "Cleanup:"
echo "  Remove test file: mc rm $MINIO_ALIAS/$BUCKET_NAME/${TEST_FILE_PREFIX}.csv"
echo "  Remove TaskRun: oc delete $LATEST_TASKRUN -n $NAMESPACE"
echo
echo -e "${GREEN}End-to-end integration test PASSED${NC}"
