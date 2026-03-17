# Testing Guide: Layer Isolation Testing

**Feature**: MinIO-KFP Automatic Pipeline Trigger
**Date**: 2026-03-16
**Constitutional Principle**: Backward Integration (Layer 1 → 2 → 3 → 4)

## Overview

This guide documents layer isolation testing procedures following the constitutional backward integration principle. Each layer is tested independently before integration with the previous layer.

**Testing Strategy**:
1. **Layer 1 (KFP Pipeline)**: Test pipeline accepts s3_uri parameter
2. **Layer 2 (Python Script)**: Test script triggers Layer 1
3. **Layer 3 (Tekton EventListener)**: Test EventListener triggers Layer 2
4. **Layer 4 (MinIO Webhook)**: Test MinIO triggers Layer 3
5. **End-to-End**: Verify complete flow

## Prerequisites

```bash
# Verify cluster access
oc whoami
oc project s3-kfp-trigger

# Verify namespace resources
oc get serviceaccount kfp-trigger-sa
oc get configmap pipeline-mappings
oc get configmap trigger-scripts
```

---

## Layer 1: KFP Pipeline Testing

**Purpose**: Verify KFP pipeline accepts `s3_uri` parameter and executes successfully

**Prerequisites**:
- Pipeline uploaded to RHOAI with name: `sample-pipeline`
- KFP CLI installed: `pip install kfp>=1.8.0`

### Test 1.1: Compile Pipeline

```bash
cd manifests/pipelines/

# Install KFP SDK
pip install kfp>=1.8.0

# Compile pipeline
python sample-kfp-pipeline.py

# Expected output:
# Pipeline compiled successfully to: sample-kfp-pipeline.yaml

# Verify YAML created
ls -l sample-kfp-pipeline.yaml
```

**Success Criteria**: Pipeline YAML file created without errors

### Test 1.2: Upload Pipeline to RHOAI

```bash
# Get RHOAI pipeline server route
KFP_HOST=$(oc get route ds-pipeline-dspa -n redhat-ods-applications -o jsonpath='{.spec.host}')

# Upload pipeline
kfp pipeline upload \
  --pipeline-name sample-pipeline \
  --pipeline-package sample-kfp-pipeline.yaml \
  --host "https://$KFP_HOST"

# Verify pipeline exists
kfp pipeline list --host "https://$KFP_HOST" | grep sample-pipeline
```

**Success Criteria**: Pipeline appears in RHOAI UI and CLI list

### Test 1.3: Trigger Pipeline Manually

```bash
# Trigger pipeline with test S3 URI
kfp run submit \
  --pipeline-name sample-pipeline \
  --argument s3_uri="s3://ml-datasets/test-layer1.csv" \
  --host "https://$KFP_HOST"

# Monitor run
kfp run list --host "https://$KFP_HOST" | head -5

# Check RHOAI UI
echo "Verify run in RHOAI UI: https://$KFP_HOST"
```

**Success Criteria**:
- ✅ Pipeline run created
- ✅ Run status: Succeeded
- ✅ Pipeline logs show s3_uri parameter value

**✅ Layer 1 Complete**: KFP pipeline independently tested and verified

---

## Layer 2: Python Trigger Script Testing

**Purpose**: Verify Python script can trigger Layer 1 (KFP pipeline) via API

**Prerequisites**:
- Layer 1 testing complete
- ConfigMaps deployed (pipeline-mappings, trigger-scripts)
- RBAC configured (kfp-trigger-sa)

### Test 2.1: Verify ConfigMaps

```bash
# Check trigger scripts ConfigMap
oc get configmap trigger-scripts -o yaml | head -20

# Verify all three scripts embedded
oc get configmap trigger-scripts -o jsonpath='{.data}' | grep -o 'trigger_pipeline.py\|kfp_client.py\|event_logger.py'

# Check pipeline mappings ConfigMap
oc get configmap pipeline-mappings -o yaml

# Verify test route exists
oc get configmap pipeline-mappings -o jsonpath='{.data.mappings\.yaml}' | grep 'ml-datasets/'
```

**Success Criteria**: All scripts present, test route configured

### Test 2.2: Trigger Script via TaskRun

Create test TaskRun: `test-layer2-taskrun.yaml`

```yaml
apiVersion: tekton.dev/v1beta1
kind: TaskRun
metadata:
  name: test-layer2-trigger
  namespace: s3-kfp-trigger
spec:
  serviceAccountName: kfp-trigger-sa
  taskSpec:
    steps:
      - name: trigger-pipeline
        image: python:3.9-slim
        script: |
          #!/bin/bash
          set -e
          echo "Installing dependencies..."
          pip install --quiet kfp>=1.8.0 kubernetes>=25.0.0 pyyaml>=6.0

          echo "Triggering pipeline..."
          python /scripts/trigger_pipeline.py --s3-uri "s3://ml-datasets/test-layer2.csv"
        env:
          - name: KFP_HOST
            value: "https://ds-pipeline-dspa.redhat-ods-applications.svc.cluster.local:8443"
          - name: PIPELINE_MAPPINGS_PATH
            value: "/config/mappings.yaml"
        volumeMounts:
          - name: scripts
            mountPath: /scripts
          - name: config
            mountPath: /config
    volumes:
      - name: scripts
        configMap:
          name: trigger-scripts
      - name: config
        configMap:
          name: pipeline-mappings
```

Run test:

```bash
# Apply TaskRun
oc apply -f test-layer2-taskrun.yaml

# Monitor TaskRun
oc get taskrun test-layer2-trigger -w

# Wait for completion (timeout 2 minutes)
oc wait --for=condition=Succeeded taskrun/test-layer2-trigger --timeout=120s

# Check logs
oc logs taskrun/test-layer2-trigger
```

**Expected Log Output**:
```json
{
  "timestamp": "2026-03-16T...",
  "log_id": "...",
  "status": "success",
  "s3_uri": "s3://ml-datasets/test-layer2.csv",
  "pipeline": "sample-pipeline",
  "pipeline_run_id": "..."
}
```

**Success Criteria**:
- ✅ TaskRun status: Succeeded
- ✅ Logs show `"status": "success"`
- ✅ Pipeline run ID present in logs
- ✅ Pipeline run visible in RHOAI UI

### Test 2.3: Test No-Match Scenario

```bash
# Create TaskRun with unmapped S3 URI
cat <<EOF | oc apply -f -
apiVersion: tekton.dev/v1beta1
kind: TaskRun
metadata:
  name: test-layer2-nomatch
  namespace: s3-kfp-trigger
spec:
  serviceAccountName: kfp-trigger-sa
  taskSpec:
    steps:
      - name: trigger-pipeline
        image: python:3.9-slim
        script: |
          #!/bin/bash
          pip install --quiet kfp>=1.8.0 kubernetes>=25.0.0 pyyaml>=6.0
          python /scripts/trigger_pipeline.py --s3-uri "s3://unmapped-bucket/file.csv" || exit 0
        env:
          - name: KFP_HOST
            value: "https://ds-pipeline-dspa.redhat-ods-applications.svc.cluster.local:8443"
          - name: PIPELINE_MAPPINGS_PATH
            value: "/config/mappings.yaml"
        volumeMounts:
          - name: scripts
            mountPath: /scripts
          - name: config
            mountPath: /config
    volumes:
      - name: scripts
        configMap:
          name: trigger-scripts
      - name: config
        configMap:
          name: pipeline-mappings
EOF

# Check logs
oc logs taskrun/test-layer2-nomatch
```

**Expected Log Output**:
```json
{
  "timestamp": "2026-03-16T...",
  "status": "no_match",
  "s3_uri": "s3://unmapped-bucket/file.csv"
}
```

**Success Criteria**:
- ✅ Script exits with code 2
- ✅ Logs show `"status": "no_match"`
- ✅ No pipeline run created

**✅ Layer 2 Complete**: Python trigger script independently tested against Layer 1

---

## Layer 3: Tekton EventListener Testing

**Purpose**: Verify EventListener receives webhooks and triggers Layer 2 (Python script)

**Prerequisites**:
- Layer 2 testing complete
- EventListener deployed and running
- TriggerBinding and TriggerTemplate configured

### Test 3.1: Verify EventListener Deployment

```bash
# Check EventListener resource
oc get eventlistener minio-listener

# Check EventListener pod
oc get pods -l eventlistener=minio-listener

# Verify pod is running
oc get pods -l eventlistener=minio-listener -o jsonpath='{.items[0].status.phase}'

# Check EventListener service
oc get svc el-minio-listener

# Check EventListener route
oc get route el-minio-listener
EVENTLISTENER_URL=$(oc get route el-minio-listener -o jsonpath='{.spec.host}')
echo "EventListener URL: https://$EVENTLISTENER_URL"
```

**Success Criteria**:
- ✅ EventListener resource exists
- ✅ Pod status: Running
- ✅ Service and Route created

### Test 3.2: Test EventListener with curl (External Route)

Create test MinIO event: `test-minio-event.json`

```json
{
  "Records": [
    {
      "eventName": "s3:ObjectCreated:Put",
      "s3": {
        "bucket": {
          "name": "ml-datasets"
        },
        "object": {
          "key": "test-layer3-external.csv"
        }
      }
    }
  ]
}
```

Send webhook:

```bash
# Get EventListener external URL
EVENTLISTENER_URL=$(oc get route el-minio-listener -o jsonpath='{.spec.host}')

# Send test webhook
curl -X POST "https://$EVENTLISTENER_URL" \
  -H "Content-Type: application/json" \
  -d @test-minio-event.json

# Check response (should be 201 Created or 202 Accepted)
```

**Note**: External route may return 503 if cluster ingress not configured properly. Use internal test instead.

### Test 3.3: Test EventListener with curl (Internal)

```bash
# Create test pod for internal access
oc run curl-test --rm -it --image=curlimages/curl --restart=Never -- sh

# Inside pod:
cat > /tmp/test-event.json <<'EOF'
{
  "Records": [
    {
      "eventName": "s3:ObjectCreated:Put",
      "s3": {
        "bucket": {
          "name": "ml-datasets"
        },
        "object": {
          "key": "test-layer3-internal.csv"
        }
      }
    }
  ]
}
EOF

curl -X POST "http://el-minio-listener.s3-kfp-trigger.svc.cluster.local:8080" \
  -H "Content-Type: application/json" \
  -d @/tmp/test-event.json

exit
```

### Test 3.4: Verify TaskRun Created

```bash
# List TaskRuns (should see new one)
oc get taskruns

# Get latest TaskRun
LATEST_TASKRUN=$(oc get taskruns --sort-by=.metadata.creationTimestamp -o name | tail -1)
echo "Latest TaskRun: $LATEST_TASKRUN"

# Check TaskRun logs
oc logs "$LATEST_TASKRUN"

# Verify pipeline was triggered
oc get taskruns "$LATEST_TASKRUN" -o jsonpath='{.status.conditions[0].reason}'
```

**Expected Log Output**:
```json
{
  "timestamp": "2026-03-16T...",
  "status": "success",
  "s3_uri": "s3://ml-datasets/test-layer3-internal.csv",
  "pipeline_run_id": "..."
}
```

**Success Criteria**:
- ✅ TaskRun created within 5 seconds of webhook
- ✅ TaskRun status: Succeeded
- ✅ Logs show successful pipeline trigger
- ✅ Pipeline run visible in RHOAI UI

### Test 3.5: EventListener Integration Test Script

Run automated test:

```bash
cd tests/integration/

# Make script executable if needed
chmod +x test_eventlistener.sh

# Run test (uses internal cluster URL)
./test_eventlistener.sh

# Expected output:
# ✓ EventListener pod running
# ✓ Webhook accepted
# ✓ TaskRun created
# ✓ Pipeline triggered
```

**Success Criteria**: All test checks pass

**✅ Layer 3 Complete**: EventListener independently tested against Layer 2

---

## Layer 4: MinIO Webhook Testing

**Purpose**: Verify MinIO webhook sends events to Layer 3 (EventListener)

**Prerequisites**:
- Layer 3 testing complete
- MinIO deployed in cluster
- mc (MinIO Client) installed locally

### Test 4.1: Setup MinIO Bucket

```bash
cd examples/quickstart/

# Run bucket setup script
./setup-minio-bucket.sh

# Expected output:
# ✓ MinIO alias configured: local
# ✓ Bucket created: ml-datasets
# ✓ Test file uploaded: test-upload.csv
```

**Success Criteria**:
- ✅ MinIO alias configured
- ✅ Bucket exists
- ✅ Test file uploaded

### Test 4.2: Configure MinIO Webhook

```bash
# Run webhook configuration script
./configure-webhook.sh

# Select internal EventListener URL (option 1)

# Expected output:
# ✓ Notification target configured
# ✓ MinIO restarted
# ✓ Event notification added
# ✓ Test file uploaded
# ✓ TaskRun(s) found!
```

**Success Criteria**:
- ✅ Webhook notification target configured
- ✅ Event notification added to bucket
- ✅ Test upload triggers TaskRun

### Test 4.3: Verify Webhook Configuration

```bash
# List bucket events
mc event list local/ml-datasets

# Expected output:
# arn:minio:sqs::tekton:webhook   s3:ObjectCreated:*   Filter: suffix="" prefix=""
```

**Success Criteria**: Webhook ARN listed with correct event types

### Test 4.4: Manual File Upload Test

```bash
# Create test file
echo "timestamp,value,category" > /tmp/manual-test.csv
echo "2026-03-16T10:00:00Z,42.5,A" >> /tmp/manual-test.csv

# Upload to MinIO
mc cp /tmp/manual-test.csv local/ml-datasets/manual-layer4-test.csv

# Monitor TaskRun creation
oc get taskruns -w

# Wait 10 seconds, then check latest TaskRun
sleep 10
LATEST_TASKRUN=$(oc get taskruns --sort-by=.metadata.creationTimestamp -o name | tail -1)
oc logs "$LATEST_TASKRUN"
```

**Expected Log Output**:
```json
{
  "status": "success",
  "s3_uri": "s3://ml-datasets/manual-layer4-test.csv",
  "pipeline_run_id": "..."
}
```

**Success Criteria**:
- ✅ TaskRun created within 30 seconds
- ✅ TaskRun logs show success
- ✅ Pipeline run created in RHOAI

**✅ Layer 4 Complete**: MinIO webhook independently tested against Layer 3

---

## End-to-End Integration Test

**Purpose**: Verify complete flow from MinIO upload to pipeline execution

### Test E2E: Full Integration Test

```bash
cd tests/integration/

# Run end-to-end test
./test_minio_webhook.sh

# Expected output:
# ======================================================================
# End-to-End Integration Test: MinIO → Tekton → KFP
# ======================================================================
#
# Configuration:
#   MinIO Alias: local
#   Bucket: ml-datasets
#   Namespace: s3-kfp-trigger
#   Test File Prefix: e2e-test-1710590000
#
# Checking prerequisites...
# ✓ MinIO Client (mc) found
# ✓ oc CLI found
# ✓ Logged into OpenShift: <username>
# ✓ MinIO alias configured
# ✓ Bucket exists
# ✓ EventListener deployed
# ✓ EventListener pod running
#
# All prerequisites met!
#
# Getting baseline TaskRun count...
# TaskRuns before test: 5
#
# Creating test data file...
# ✓ Test data created: /tmp/e2e-test-1710590000.csv
#
# Uploading file to MinIO bucket...
# ✓ File uploaded successfully
#
# Waiting for TaskRun creation (max 30 seconds)...
# ✓ New TaskRun detected after 8 seconds!
#
# Getting latest TaskRun details...
# Latest TaskRun: taskrun/kfp-trigger-abc123
#
# TaskRun Status:
# NAME                  SUCCEEDED   REASON      STARTTIME   COMPLETIONTIME
# kfp-trigger-abc123    True        Succeeded   2m ago      1m ago
#
# TaskRun Parameters:
#   s3_uri: s3://ml-datasets/e2e-test-1710590000.csv
# ✓ S3 URI matches expected value
#
# Waiting for TaskRun to complete (max 60 seconds)...
# ✓ TaskRun completed successfully!
#
# TaskRun Logs (last 50 lines):
# ----------------------------------------------------------------------
# {"timestamp": "2026-03-16T10:00:00Z", "status": "success", ...}
# ----------------------------------------------------------------------
#
# Analyzing trigger output...
# ✓ Pipeline triggered successfully
#   Pipeline Run ID: abc123-xyz789
#
# ======================================================================
# Test Summary
# ======================================================================
#
# ✓ File uploaded to MinIO
# ✓ Webhook triggered TaskRun
# ✓ Trigger script executed
#
# Test Results:
#   File: ml-datasets/e2e-test-1710590000.csv
#   TaskRun: taskrun/kfp-trigger-abc123
#   S3 URI: s3://ml-datasets/e2e-test-1710590000.csv
#   Status: Succeeded
#
# End-to-end integration test PASSED
```

**Success Criteria**:
- ✅ All prerequisites met
- ✅ File uploaded to MinIO
- ✅ TaskRun created within 30 seconds
- ✅ TaskRun completed successfully
- ✅ Logs show `"status": "success"`
- ✅ Pipeline run ID present
- ✅ Pipeline visible in RHOAI UI

---

## Test Summary

| Layer | Test Type | Command | Expected Result |
|-------|-----------|---------|-----------------|
| Layer 1 | Pipeline Compilation | `python sample-kfp-pipeline.py` | YAML created |
| Layer 1 | Pipeline Upload | `kfp pipeline upload ...` | Pipeline in RHOAI |
| Layer 1 | Manual Trigger | `kfp run submit ...` | Run succeeds |
| Layer 2 | Script via TaskRun | `oc apply -f test-layer2-taskrun.yaml` | Pipeline triggered |
| Layer 2 | No-Match Scenario | `oc logs taskrun/test-layer2-nomatch` | Exit code 2 |
| Layer 3 | EventListener Status | `oc get pods -l eventlistener=minio-listener` | Pod Running |
| Layer 3 | Webhook via curl | `curl -X POST http://el-minio-listener...` | TaskRun created |
| Layer 3 | Integration Script | `./test_eventlistener.sh` | All checks pass |
| Layer 4 | Bucket Setup | `./setup-minio-bucket.sh` | Bucket created |
| Layer 4 | Webhook Config | `./configure-webhook.sh` | Events configured |
| Layer 4 | Manual Upload | `mc cp test.csv local/ml-datasets/` | TaskRun created |
| E2E | Full Integration | `./test_minio_webhook.sh` | Complete flow works |

---

## Troubleshooting

### TaskRun Fails Immediately

**Check logs**:
```bash
oc logs taskrun/<name>
```

**Common issues**:
- Missing ConfigMap: Check `oc get configmap trigger-scripts`
- RBAC issues: Check `oc get rolebinding kfp-trigger-binding`
- KFP host unreachable: Verify `KFP_HOST` environment variable

### EventListener Not Creating TaskRuns

**Check EventListener logs**:
```bash
oc logs -l eventlistener=minio-listener
```

**Common issues**:
- TriggerBinding not found: `oc get triggerbinding minio-event-binding`
- TriggerTemplate not found: `oc get triggertemplate kfp-trigger-template`
- RBAC missing Tekton permissions: Check for ClusterRole

### MinIO Webhook Not Firing

**Check MinIO logs**:
```bash
oc logs -n minio deployment/minio | grep webhook
```

**Test webhook manually**:
```bash
mc event list local/ml-datasets
```

**Common issues**:
- Webhook not configured: Run `configure-webhook.sh`
- EventListener URL unreachable from MinIO: Use internal cluster URL
- MinIO restart needed: `mc admin service restart local`

---

## Next Steps

After successful layer isolation testing:

1. **Production Deployment**: Apply resource limits, HA configuration
2. **Multi-Tenancy (User Story 2)**: Add team-specific routes
3. **Monitoring (User Story 3)**: Set up log aggregation and alerts
4. **Performance Testing**: Measure end-to-end latency
5. **Load Testing**: Test concurrent file uploads

For more details, see:
- [quickstart.md](../specs/001-minio-kfp-trigger/quickstart.md) - Step-by-step setup guide
- [quickstart-validation.md](./quickstart-validation.md) - Implementation vs guide comparison
- [architecture.md](./architecture.md) - System architecture (when created)
