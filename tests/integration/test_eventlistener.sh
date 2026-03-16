#!/bin/bash
#
# Integration test for Tekton EventListener
#
# Tests that the EventListener receives webhook payloads and creates TaskRuns.
# Requires: oc CLI, curl, jq (optional)
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "======================================================================"
echo "Tekton EventListener Integration Test"
echo "======================================================================"
echo

# Check prerequisites
if ! command -v oc &> /dev/null; then
    echo -e "${RED}ERROR: oc CLI not found${NC}"
    echo "Install from: https://mirror.openshift.com/pub/openshift-v4/clients/ocp/"
    exit 1
fi

if ! command -v curl &> /dev/null; then
    echo -e "${RED}ERROR: curl not found${NC}"
    exit 1
fi

# Configuration
NAMESPACE="${NAMESPACE:-s3-kfp-trigger}"
EVENTLISTENER_NAME="minio-listener"
FIXTURE_FILE="${FIXTURE_FILE:-../../tests/fixtures/sample-minio-event.json}"

echo "Configuration:"
echo "  Namespace: $NAMESPACE"
echo "  EventListener: $EVENTLISTENER_NAME"
echo "  Test fixture: $FIXTURE_FILE"
echo

# Check if EventListener exists
echo "Checking if EventListener exists..."
if ! oc get eventlistener "$EVENTLISTENER_NAME" -n "$NAMESPACE" &> /dev/null; then
    echo -e "${RED}ERROR: EventListener '$EVENTLISTENER_NAME' not found in namespace '$NAMESPACE'${NC}"
    echo "Deploy EventListener first:"
    echo "  oc apply -f ../../manifests/tekton/"
    exit 1
fi
echo -e "${GREEN}✓ EventListener found${NC}"
echo

# Get EventListener URL
echo "Getting EventListener URL..."
EVENTLISTENER_URL=$(oc get route "el-$EVENTLISTENER_NAME" -n "$NAMESPACE" -o jsonpath='{.spec.host}' 2>/dev/null || echo "")

if [ -z "$EVENTLISTENER_URL" ]; then
    echo -e "${YELLOW}WARNING: EventListener route not found. Attempting to create...${NC}"
    oc expose svc "el-$EVENTLISTENER_NAME" -n "$NAMESPACE" || {
        echo -e "${RED}ERROR: Failed to expose EventListener service${NC}"
        exit 1
    }
    sleep 2
    EVENTLISTENER_URL=$(oc get route "el-$EVENTLISTENER_NAME" -n "$NAMESPACE" -o jsonpath='{.spec.host}')
fi

echo "EventListener URL: https://$EVENTLISTENER_URL"
echo

# Check if test fixture exists
if [ ! -f "$FIXTURE_FILE" ]; then
    echo -e "${RED}ERROR: Test fixture not found: $FIXTURE_FILE${NC}"
    exit 1
fi

echo "Test fixture content:"
cat "$FIXTURE_FILE" | head -20
echo "..."
echo

# Get current TaskRun count before test
echo "Counting existing TaskRuns..."
TASKRUNS_BEFORE=$(oc get taskruns -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l | tr -d ' ')
echo "TaskRuns before test: $TASKRUNS_BEFORE"
echo

# Send webhook to EventListener
echo "Sending test webhook to EventListener..."
echo "POST https://$EVENTLISTENER_URL"
echo

RESPONSE=$(curl -s -w "\nHTTP_CODE:%{http_code}" -X POST "https://$EVENTLISTENER_URL" \
    -H "Content-Type: application/json" \
    -d @"$FIXTURE_FILE")

HTTP_CODE=$(echo "$RESPONSE" | grep "HTTP_CODE:" | cut -d':' -f2)
BODY=$(echo "$RESPONSE" | sed '/HTTP_CODE:/d')

echo "Response HTTP code: $HTTP_CODE"
echo "Response body:"
echo "$BODY"
echo

# Check HTTP response code
if [ "$HTTP_CODE" != "201" ] && [ "$HTTP_CODE" != "200" ]; then
    echo -e "${RED}ERROR: Unexpected HTTP code: $HTTP_CODE${NC}"
    echo "Expected: 201 (Created) or 200 (OK)"
    exit 1
fi
echo -e "${GREEN}✓ HTTP response OK${NC}"
echo

# Wait for TaskRun to be created
echo "Waiting for TaskRun to be created (timeout: 10 seconds)..."
sleep 5

TASKRUNS_AFTER=$(oc get taskruns -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l | tr -d ' ')
echo "TaskRuns after test: $TASKRUNS_AFTER"

if [ "$TASKRUNS_AFTER" -le "$TASKRUNS_BEFORE" ]; then
    echo -e "${YELLOW}WARNING: No new TaskRun created${NC}"
    echo "Checking EventListener logs..."
    oc logs -n "$NAMESPACE" -l eventlistener="$EVENTLISTENER_NAME" --tail=50 || true
    echo
    echo -e "${RED}ERROR: TaskRun was not created by webhook${NC}"
    exit 1
fi

echo -e "${GREEN}✓ New TaskRun created${NC}"
echo

# Get the latest TaskRun
echo "Getting latest TaskRun details..."
LATEST_TASKRUN=$(oc get taskruns -n "$NAMESPACE" --sort-by=.metadata.creationTimestamp -o name | tail -1)
echo "Latest TaskRun: $LATEST_TASKRUN"
echo

# Show TaskRun status
echo "TaskRun status:"
oc get "$LATEST_TASKRUN" -n "$NAMESPACE"
echo

# Show TaskRun parameters
echo "TaskRun parameters:"
oc get "$LATEST_TASKRUN" -n "$NAMESPACE" -o jsonpath='{.spec.params}' | grep -o '"name":"[^"]*","value":"[^"]*"' || echo "No parameters found"
echo
echo

# Show TaskRun logs (if available)
echo "TaskRun logs (most recent 20 lines):"
oc logs "$LATEST_TASKRUN" -n "$NAMESPACE" --tail=20 2>/dev/null || {
    echo -e "${YELLOW}TaskRun logs not yet available (TaskRun may not have started)${NC}"
}
echo

# Summary
echo "======================================================================"
echo "Test Summary"
echo "======================================================================"
echo -e "${GREEN}✓ EventListener is accessible${NC}"
echo -e "${GREEN}✓ Webhook payload accepted (HTTP $HTTP_CODE)${NC}"
echo -e "${GREEN}✓ TaskRun created: $LATEST_TASKRUN${NC}"
echo
echo "To monitor TaskRun execution:"
echo "  oc logs -f $LATEST_TASKRUN -n $NAMESPACE"
echo
echo "To check TaskRun status:"
echo "  oc get $LATEST_TASKRUN -n $NAMESPACE"
echo
echo -e "${GREEN}Integration test PASSED${NC}"
