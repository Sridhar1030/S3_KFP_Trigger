# Kubeflow Pipeline Definitions

This directory contains Kubeflow Pipeline (KFP) definitions for MinIO-triggered ML workflows.

## Files

- `sample-kfp-pipeline.py`: Example pipeline demonstrating the s3_uri parameter contract
- `sample-kfp-pipeline.yaml`: Compiled pipeline YAML (generated from .py file)

## Pipeline Contract

All pipelines triggered by MinIO uploads **MUST** accept the `s3_uri` parameter:

```python
@dsl.pipeline(
    name='Your Pipeline Name',
    description='Your pipeline description'
)
def your_pipeline(s3_uri: str):
    """
    Pipeline triggered by MinIO upload events.

    Args:
        s3_uri (str): S3 URI to uploaded file (e.g., s3://bucket/path/file.csv)
    """
    # Your pipeline components here
```

## Compiling Pipelines

### Prerequisites

Install KFP SDK:

```bash
pip install -r ../../requirements.txt
```

### Compile to YAML

```bash
# From this directory
python3 sample-kfp-pipeline.py

# Or specify custom output path
python3 -c "
from kfp import compiler
from sample_kfp_pipeline import sample_trigger_pipeline
compiler.Compiler().compile(sample_trigger_pipeline, 'custom-output.yaml')
"
```

## Uploading to RHOAI

### Option 1: Via RHOAI Web UI

1. Navigate to Data Science Pipelines in RHOAI console
2. Click "Upload pipeline"
3. Select `sample-kfp-pipeline.yaml`
4. Name: `minio-trigger-test`
5. Click "Create"

### Option 2: Via KFP CLI

```bash
# Set KFP host (RHOAI pipeline server route)
export KFP_HOST=$(oc get route ds-pipeline-dspa -n redhat-ods-applications -o jsonpath='{.spec.host}')

# Upload pipeline
kfp pipeline upload \
  --pipeline-name minio-trigger-test \
  --pipeline-package sample-kfp-pipeline.yaml \
  --host "https://$KFP_HOST"
```

### Option 3: Via OpenShift (Direct Apply)

If your cluster supports applying KFP pipelines as Kubernetes resources:

```bash
oc apply -f sample-kfp-pipeline.yaml -n s3-kfp-trigger
```

## Testing Pipelines

### Manual Trigger (No MinIO)

Test the pipeline accepts s3_uri parameter:

```bash
# Via KFP CLI
kfp run submit \
  --pipeline-name minio-trigger-test \
  --argument s3_uri="s3://test-bucket/test-file.csv" \
  --host "https://$KFP_HOST"
```

### Trigger Via Python Script

Test the trigger script (Layer 2):

```bash
python3 ../../scripts/trigger_pipeline.py \
  --s3-uri s3://ml-datasets/test-upload.csv
```

### End-to-End Test (With MinIO)

Upload file to MinIO and verify automatic triggering:

```bash
# Upload file
mc cp test-data.csv local/ml-datasets/test-upload.csv

# Verify pipeline triggered
oc get pipelineruns -n s3-kfp-trigger --watch
```

## Pipeline Parameters

### Required Parameters

- `s3_uri` (string): Full S3-compatible URI to the uploaded file
  - Format: `s3://bucket-name/path/to/file.csv`
  - Example: `s3://ml-datasets/team-fraud/training-2026-03-16.csv`

### Optional Parameters

Additional parameters can be passed from the pipeline routing configuration (`pipeline-mappings.yaml`):

```yaml
routes:
  - prefix: "ml-datasets/team-fraud/"
    pipeline: "fraud-detection-v2"
    namespace: "s3-kfp-trigger"
    parameters:  # These become pipeline parameters
      model_type: "xgboost"
      epochs: "100"
      batch_size: "32"
```

Update your pipeline definition to accept optional parameters:

```python
def your_pipeline(
    s3_uri: str,                    # Required
    model_type: str = 'random_forest',  # Optional with default
    epochs: int = 50,               # Optional with default
    batch_size: int = 16            # Optional with default
):
    # Pipeline implementation
```

## Accessing MinIO Data

Pipelines need MinIO credentials to read data. Create a Secret with MinIO access keys:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: minio-credentials
  namespace: s3-kfp-trigger
type: Opaque
stringData:
  AWS_ACCESS_KEY_ID: your-minio-access-key
  AWS_SECRET_ACCESS_KEY: your-minio-secret-key
  AWS_S3_ENDPOINT: http://minio.minio.svc.cluster.local:9000
```

Then inject into pipeline components:

```python
@dsl.component(
    base_image='python:3.9',
    packages_to_install=['boto3']
)
def load_data(s3_uri: str) -> str:
    import os
    import boto3

    # MinIO credentials from environment (injected via Secret)
    s3 = boto3.client(
        's3',
        endpoint_url=os.getenv('AWS_S3_ENDPOINT'),
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
    )

    # Parse S3 URI
    bucket = s3_uri.split('/')[2]
    key = '/'.join(s3_uri.split('/')[3:])

    # Download file
    local_path = '/tmp/data.csv'
    s3.download_file(bucket, key, local_path)

    return local_path
```

Configure secret injection in RHOAI or via PipelineRun:

```yaml
envFrom:
  - secretRef:
      name: minio-credentials
```

## Troubleshooting

### Pipeline compilation fails

```bash
# Check KFP SDK installed
python3 -c "import kfp; print(kfp.__version__)"

# Expected: 1.8.x
# If error: pip install kfp>=1.8.0
```

### Pipeline not found in RHOAI

```bash
# List available pipelines
kfp pipeline list --host "https://$KFP_HOST"

# Re-upload if missing
kfp pipeline upload -p sample-kfp-pipeline.yaml --host "https://$KFP_HOST"
```

### Pipeline run fails with auth error

```bash
# Verify service account has permissions
oc get rolebinding kfp-trigger-binding -n s3-kfp-trigger -o yaml

# Check pipeline run logs
oc logs -n s3-kfp-trigger -l pipeline.kubeflow.org/pipelineName=minio-trigger-test
```

## Examples

See `../../examples/` for:
- Multi-team pipeline configurations
- Advanced routing with parameters
- Integration test scripts
