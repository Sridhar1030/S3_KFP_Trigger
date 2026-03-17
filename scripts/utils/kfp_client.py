#!/usr/bin/env python3
"""
Kubeflow Pipelines (KFP) client wrapper with service account authentication.

Provides authenticated KFP client for triggering pipelines from OpenShift pods.
"""

import os
from typing import Optional

try:
    import kfp
except ImportError:
    # KFP not installed - allow import for testing
    kfp = None


def get_kfp_client(
    host: Optional[str] = None,
    token_path: str = '/var/run/secrets/kubernetes.io/serviceaccount/token',
    ca_cert_path: str = '/var/run/secrets/kubernetes.io/serviceaccount/ca.crt'
) -> 'kfp.Client':
    """
    Get authenticated KFP client using service account token.

    Reads the Kubernetes service account token mounted in the pod and uses
    it to authenticate with the Kubeflow Pipelines API server.

    Args:
        host: KFP API server host URL. If not provided, reads from KFP_HOST env var.
              Default RHOAI endpoint: https://ds-pipeline-dspa.redhat-ods-applications.svc.cluster.local:8443
        token_path: Path to service account token file (mounted by Kubernetes)
        ca_cert_path: Path to CA certificate for TLS verification

    Returns:
        Authenticated kfp.Client instance

    Raises:
        ImportError: If kfp module is not installed
        FileNotFoundError: If token or CA cert file not found
        ValueError: If KFP host not specified and KFP_HOST env var not set
        Exception: If KFP client initialization fails

    Example:
        >>> client = get_kfp_client()
        >>> run = client.run_pipeline(
        ...     pipeline_name='my-pipeline',
        ...     params={'s3_uri': 's3://bucket/file.csv'}
        ... )
        >>> print(f"Pipeline run ID: {run.id}")
    """
    if kfp is None:
        raise ImportError(
            "kfp module not installed. Install with: pip install kfp>=1.8.0"
        )

    # Get KFP host from parameter or environment
    if host is None:
        host = os.getenv('KFP_HOST')

    if not host:
        # Default RHOAI endpoint
        host = 'https://ds-pipeline-dspa.redhat-ods-applications.svc.cluster.local:8443'

    # Read service account token
    if not os.path.exists(token_path):
        raise FileNotFoundError(
            f"Service account token not found at: {token_path}\n"
            f"Ensure the pod is running with a service account that has KFP permissions."
        )

    with open(token_path, 'r') as f:
        token = f.read().strip()

    if not token:
        raise ValueError(f"Service account token is empty: {token_path}")

    # Verify CA cert exists (required for TLS)
    if not os.path.exists(ca_cert_path):
        raise FileNotFoundError(
            f"CA certificate not found at: {ca_cert_path}\n"
            f"This file should be auto-mounted in Kubernetes pods."
        )

    # Create KFP client with token authentication
    try:
        client = kfp.Client(
            host=host,
            existing_token=token,
            ssl_ca_cert=ca_cert_path
        )

        return client

    except Exception as e:
        raise Exception(
            f"Failed to initialize KFP client for host={host}: {str(e)}"
        ) from e


def validate_pipeline_exists(client: 'kfp.Client', pipeline_name: str) -> Optional[str]:
    """
    Validate that a pipeline exists in KFP.

    Args:
        client: Authenticated KFP client
        pipeline_name: Name of the pipeline to validate

    Returns:
        Pipeline ID if found, None otherwise

    Example:
        >>> client = get_kfp_client()
        >>> pipeline_id = validate_pipeline_exists(client, 'fraud-detection-v2')
        >>> if pipeline_id:
        ...     print(f"Pipeline found: {pipeline_id}")
    """
    try:
        # List all pipelines
        pipelines = client.list_pipelines(page_size=1000).pipelines

        # Search for pipeline by name
        for pipeline in pipelines:
            if pipeline.name == pipeline_name:
                return pipeline.id

        return None

    except Exception as e:
        # Log error but don't raise - caller will handle None return
        print(f"Error listing pipelines: {str(e)}")
        return None


def trigger_pipeline(
    client: 'kfp.Client',
    pipeline_name: str,
    s3_uri: str,
    namespace: Optional[str] = None,
    extra_params: Optional[dict] = None
) -> 'kfp.models.ApiRun':
    """
    Trigger a KFP pipeline run with parameters.

    Args:
        client: Authenticated KFP client
        pipeline_name: Name of the pipeline to trigger
        s3_uri: S3 URI to pass to the pipeline (required parameter)
        namespace: Kubernetes namespace for pipeline execution
        extra_params: Additional parameters to pass to the pipeline

    Returns:
        KFP run object with run.id, run.name, run.status

    Raises:
        ValueError: If pipeline not found or parameters invalid
        Exception: If pipeline trigger fails

    Example:
        >>> client = get_kfp_client()
        >>> run = trigger_pipeline(
        ...     client,
        ...     pipeline_name='fraud-detection-v2',
        ...     s3_uri='s3://ml-datasets/team-fraud/data.csv',
        ...     extra_params={'model_type': 'xgboost'}
        ... )
        >>> print(f"Pipeline triggered: {run.id}")
    """
    # Validate pipeline exists
    pipeline_id = validate_pipeline_exists(client, pipeline_name)
    if not pipeline_id:
        raise ValueError(
            f"Pipeline '{pipeline_name}' not found in KFP.\n"
            f"Upload the pipeline first or check the pipeline name."
        )

    # Build parameters
    # For hello-pipeline/TestPipeline compatibility, also pass as 'recipient'
    params = {
        's3_uri': s3_uri,
        'recipient': s3_uri  # For pipelines that expect 'recipient' parameter
    }
    if extra_params:
        params.update(extra_params)

    # Generate job name with timestamp
    from datetime import datetime
    timestamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    job_name = f"minio-trigger-{timestamp}"

    # Trigger pipeline
    try:
        run = client.run_pipeline(
            experiment_id=None,  # Use default experiment
            job_name=job_name,
            pipeline_id=pipeline_id,
            params=params,
            namespace=namespace
        )

        return run

    except Exception as e:
        raise Exception(
            f"Failed to trigger pipeline '{pipeline_name}': {str(e)}"
        ) from e


# Example usage for testing
if __name__ == '__main__':
    import sys

    print("KFP Client Wrapper - Test Mode")
    print("=" * 60)

    # Check if kfp is installed
    if kfp is None:
        print("❌ KFP not installed")
        print("   Install with: pip install kfp>=1.8.0")
        sys.exit(1)

    print(f"✅ KFP version: {kfp.__version__}")
    print()

    # Check for service account token (only works inside pod)
    token_path = '/var/run/secrets/kubernetes.io/serviceaccount/token'
    if os.path.exists(token_path):
        print(f"✅ Service account token found: {token_path}")
    else:
        print(f"⚠️  Service account token not found: {token_path}")
        print("   This is normal when running outside a Kubernetes pod.")
        print("   In production, this script runs inside a Tekton TaskRun pod.")

    print()
    print("To test pipeline triggering:")
    print("  python3 ../trigger_pipeline.py --s3-uri s3://test-bucket/test.csv")
