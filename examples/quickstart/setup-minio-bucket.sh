#!/bin/bash
#
# Setup MinIO bucket and test data for S3-KFP trigger
#
# Prerequisites:
# - mc (MinIO Client) installed
# - MinIO server running in OpenShift cluster
#

set -euo pipefail

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "======================================================================"
echo "MinIO Bucket Setup for S3-KFP Trigger"
echo "======================================================================"
echo

# Configuration
MINIO_ALIAS="${MINIO_ALIAS:-local}"
BUCKET_NAME="${BUCKET_NAME:-ml-datasets}"
MINIO_NAMESPACE="${MINIO_NAMESPACE:-minio}"

echo "Configuration:"
echo "  MinIO Alias: $MINIO_ALIAS"
echo "  Bucket Name: $BUCKET_NAME"
echo "  MinIO Namespace: $MINIO_NAMESPACE"
echo

# Check if mc is installed
if ! command -v mc &> /dev/null; then
    echo -e "${RED}ERROR: MinIO Client (mc) not found${NC}"
    echo "Install from: https://min.io/download"
    echo
    echo "macOS:"
    echo "  brew install minio/stable/mc"
    echo
    echo "Linux:"
    echo "  wget https://dl.min.io/client/mc/release/linux-amd64/mc"
    echo "  chmod +x mc"
    echo "  sudo mv mc /usr/local/bin/"
    exit 1
fi

echo -e "${GREEN}✓ MinIO Client (mc) found${NC}"
mc --version
echo

# Get MinIO endpoint from OpenShift
echo "Getting MinIO endpoint from OpenShift..."

# Try to get MinIO route
MINIO_ROUTE=$(oc get route minio -n "$MINIO_NAMESPACE" -o jsonpath='{.spec.host}' 2>/dev/null || echo "")

if [ -z "$MINIO_ROUTE" ]; then
    echo -e "${YELLOW}WARNING: MinIO route not found in namespace '$MINIO_NAMESPACE'${NC}"
    echo
    echo "Available options:"
    echo "  1. MinIO is in a different namespace (set MINIO_NAMESPACE env var)"
    echo "  2. MinIO uses a Service instead of Route (for cluster-internal access)"
    echo "  3. MinIO is not yet deployed"
    echo
    read -p "Enter MinIO endpoint manually (e.g., minio.minio.svc.cluster.local:9000): " MINIO_ENDPOINT

    if [ -z "$MINIO_ENDPOINT" ]; then
        echo -e "${RED}ERROR: No MinIO endpoint provided${NC}"
        exit 1
    fi

    MINIO_URL="http://$MINIO_ENDPOINT"
else
    MINIO_URL="https://$MINIO_ROUTE"
fi

echo "MinIO URL: $MINIO_URL"
echo

# Get MinIO credentials
echo "MinIO Credentials:"
echo

if [ -n "${MINIO_ACCESS_KEY:-}" ] && [ -n "${MINIO_SECRET_KEY:-}" ]; then
    echo "Using credentials from environment variables"
    ACCESS_KEY="$MINIO_ACCESS_KEY"
    SECRET_KEY="$MINIO_SECRET_KEY"
else
    # Try to get from OpenShift Secret
    echo "Attempting to retrieve credentials from OpenShift Secret..."

    ACCESS_KEY=$(oc get secret minio -n "$MINIO_NAMESPACE" -o jsonpath='{.data.accesskey}' 2>/dev/null | base64 -d || echo "")
    SECRET_KEY=$(oc get secret minio -n "$MINIO_NAMESPACE" -o jsonpath='{.data.secretkey}' 2>/dev/null | base64 -d || echo "")

    if [ -z "$ACCESS_KEY" ] || [ -z "$SECRET_KEY" ]; then
        echo -e "${YELLOW}Could not retrieve credentials from Secret${NC}"
        echo
        read -p "Enter MinIO Access Key: " ACCESS_KEY
        read -s -p "Enter MinIO Secret Key: " SECRET_KEY
        echo

        if [ -z "$ACCESS_KEY" ] || [ -z "$SECRET_KEY" ]; then
            echo -e "${RED}ERROR: Credentials required${NC}"
            exit 1
        fi
    else
        echo -e "${GREEN}✓ Credentials retrieved from Secret${NC}"
    fi
fi

echo

# Configure mc alias
echo "Configuring MinIO client alias: $MINIO_ALIAS"

mc alias set "$MINIO_ALIAS" "$MINIO_URL" "$ACCESS_KEY" "$SECRET_KEY" --insecure || {
    echo -e "${RED}ERROR: Failed to configure MinIO alias${NC}"
    echo "Check that:"
    echo "  - MinIO server is accessible"
    echo "  - Credentials are correct"
    echo "  - Network connectivity is working"
    exit 1
}

echo -e "${GREEN}✓ MinIO alias configured${NC}"
echo

# Test connection
echo "Testing connection to MinIO..."
mc ls "$MINIO_ALIAS" --insecure > /dev/null || {
    echo -e "${RED}ERROR: Cannot connect to MinIO${NC}"
    exit 1
}
echo -e "${GREEN}✓ Connection successful${NC}"
echo

# Create bucket
echo "Creating bucket: $BUCKET_NAME"

if mc ls "$MINIO_ALIAS/$BUCKET_NAME" --insecure &> /dev/null; then
    echo -e "${YELLOW}Bucket '$BUCKET_NAME' already exists${NC}"
else
    mc mb "$MINIO_ALIAS/$BUCKET_NAME" --insecure || {
        echo -e "${RED}ERROR: Failed to create bucket${NC}"
        exit 1
    }
    echo -e "${GREEN}✓ Bucket created${NC}"
fi

echo

# Create sample test data
echo "Creating sample test data..."

cat > /tmp/test-data.csv << 'EOF'
timestamp,value,category,label
2026-03-16T10:00:00Z,42.5,A,positive
2026-03-16T10:01:00Z,38.2,B,negative
2026-03-16T10:02:00Z,51.7,A,positive
2026-03-16T10:03:00Z,29.8,C,neutral
2026-03-16T10:04:00Z,65.3,B,positive
EOF

echo -e "${GREEN}✓ Test data created: /tmp/test-data.csv${NC}"
echo

# Upload test file
echo "Uploading test file to bucket..."

mc cp /tmp/test-data.csv "$MINIO_ALIAS/$BUCKET_NAME/test-upload.csv" --insecure

echo -e "${GREEN}✓ Test file uploaded${NC}"
echo

# List bucket contents
echo "Bucket contents:"
mc ls "$MINIO_ALIAS/$BUCKET_NAME/" --insecure

echo
echo "======================================================================"
echo "MinIO Bucket Setup Complete!"
echo "======================================================================"
echo
echo "Summary:"
echo "  ✓ MinIO alias configured: $MINIO_ALIAS"
echo "  ✓ Bucket created: $BUCKET_NAME"
echo "  ✓ Test file uploaded: test-upload.csv"
echo
echo "Next steps:"
echo "  1. Configure MinIO webhook to trigger EventListener:"
echo "     ./configure-webhook.sh"
echo
echo "  2. Or manually upload more files:"
echo "     mc cp myfile.csv $MINIO_ALIAS/$BUCKET_NAME/"
echo
echo "  3. Verify uploads trigger pipelines:"
echo "     oc get taskruns -n s3-kfp-trigger --watch"
echo
