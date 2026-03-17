#!/bin/bash
#
# Quick test script to trigger a KFP pipeline via EventListener
#
set -e

echo "🚀 Testing MinIO → Tekton → KFP Pipeline Trigger"
echo "================================================"
echo

# Get EventListener URL
EVENTLISTENER_URL="http://el-minio-listener-s3-kfp-trigger.apps.sridhartest-pool-7f6n4.aws.rh-ods.com"
echo "EventListener URL: $EVENTLISTENER_URL"
echo

# Create test MinIO event payload
cat > /tmp/test-minio-event.json <<'EOF'
{
  "EventName": "s3:ObjectCreated:Put",
  "Key": "ml-datasets/test-upload.csv",
  "Records": [
    {
      "eventVersion": "2.0",
      "eventSource": "minio:s3",
      "awsRegion": "",
      "eventTime": "2026-03-17T10:30:00.000Z",
      "eventName": "s3:ObjectCreated:Put",
      "userIdentity": {
        "principalId": "test-user"
      },
      "requestParameters": {
        "sourceIPAddress": "192.168.1.100"
      },
      "responseElements": {
        "x-amz-request-id": "17C123456789ABCD",
        "x-minio-deployment-id": "test123"
      },
      "s3": {
        "s3SchemaVersion": "1.0",
        "configurationId": "webhook-config",
        "bucket": {
          "name": "ml-datasets",
          "ownerIdentity": {
            "principalId": "minio"
          },
          "arn": "arn:aws:s3:::ml-datasets"
        },
        "object": {
          "key": "test-upload.csv",
          "size": 1024,
          "eTag": "d41d8cd98f00b204e9800998ecf8427e",
          "sequencer": "17C1234567890000"
        }
      }
    }
  ]
}
EOF

echo "📤 Sending webhook event to EventListener..."
curl -X POST "$EVENTLISTENER_URL" \
  -H "Content-Type: application/json" \
  -d @/tmp/test-minio-event.json \
  -v
echo
echo

echo "⏳ Waiting 3 seconds for TaskRun to be created..."
sleep 3
echo

echo "📋 Recent TaskRuns in s3-kfp-trigger namespace:"
oc get taskruns -n s3-kfp-trigger --sort-by=.metadata.creationTimestamp | tail -5
echo

echo "🔍 Getting the latest TaskRun..."
LATEST_TASKRUN=$(oc get taskruns -n s3-kfp-trigger --sort-by=.metadata.creationTimestamp -o name | tail -1)
echo "Latest TaskRun: $LATEST_TASKRUN"
echo

if [ -n "$LATEST_TASKRUN" ]; then
    echo "📜 TaskRun logs:"
    echo "----------------------------------------"
    oc logs "$LATEST_TASKRUN" -n s3-kfp-trigger --follow 2>&1 || true
    echo "----------------------------------------"
    echo

    echo "✅ TaskRun status:"
    oc get "$LATEST_TASKRUN" -n s3-kfp-trigger -o jsonpath='{.status.conditions[0].message}'
    echo
    echo

    echo "🎯 Checking for KFP pipeline runs..."
    oc get pipelineruns -n s3-kfp-trigger 2>/dev/null | tail -5 || echo "No pipeline runs found yet"
    echo
else
    echo "❌ No TaskRun was created. Check EventListener logs:"
    oc logs -n s3-kfp-trigger deployment/el-minio-listener --tail=20
fi

echo
echo "✨ Test complete!"
