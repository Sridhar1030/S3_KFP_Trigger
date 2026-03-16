#!/usr/bin/env python3
"""
Sample Kubeflow Pipeline for MinIO-triggered ML workflows.

This pipeline demonstrates the minimal contract for automatic triggering:
- Accepts s3_uri parameter (required)
- Can be triggered via KFP SDK
- Processes data from MinIO buckets

Usage:
    python sample-kfp-pipeline.py  # Compiles to YAML
"""

from kfp import dsl


@dsl.component(
    base_image='python:3.9-slim',
    packages_to_install=['boto3']
)
def print_s3_info(s3_uri: str):
    """
    Simple component that prints S3 URI information.

    In a real pipeline, this would load and process data from MinIO.

    Args:
        s3_uri: Full S3 URI (e.g., s3://ml-datasets/team-fraud/data.csv)
    """
    import os

    print("=" * 60)
    print("MinIO-Triggered Pipeline Execution")
    print("=" * 60)
    print(f"Processing data from: {s3_uri}")
    print()

    # Parse S3 URI
    if s3_uri.startswith('s3://'):
        uri_parts = s3_uri[5:].split('/', 1)
        bucket = uri_parts[0]
        object_key = uri_parts[1] if len(uri_parts) > 1 else ''

        print(f"Bucket: {bucket}")
        print(f"Object Key: {object_key}")
    else:
        print(f"WARNING: Invalid S3 URI format: {s3_uri}")

    print()
    print("MinIO credentials should be available as environment variables:")
    print(f"- AWS_S3_ENDPOINT: {os.getenv('AWS_S3_ENDPOINT', 'NOT SET')}")
    print(f"- AWS_ACCESS_KEY_ID: {'SET' if os.getenv('AWS_ACCESS_KEY_ID') else 'NOT SET'}")
    print(f"- AWS_SECRET_ACCESS_KEY: {'SET' if os.getenv('AWS_SECRET_ACCESS_KEY') else 'NOT SET'}")
    print()
    print("Pipeline execution complete!")
    print("=" * 60)


@dsl.component(
    base_image='python:3.9-slim',
    packages_to_install=['pandas']
)
def simulate_data_processing(s3_uri: str) -> str:
    """
    Simulate data processing step.

    Args:
        s3_uri: S3 URI to process

    Returns:
        Processing result message
    """
    import time

    print(f"[Data Processing] Starting processing for: {s3_uri}")

    # Simulate processing time
    time.sleep(2)

    result = f"Successfully processed data from {s3_uri}"
    print(f"[Data Processing] {result}")

    return result


@dsl.component(
    base_image='python:3.9-slim'
)
def log_completion(processing_result: str):
    """
    Log pipeline completion.

    Args:
        processing_result: Result from previous processing step
    """
    print("=" * 60)
    print("[Pipeline Complete]")
    print(f"Result: {processing_result}")
    print("=" * 60)


@dsl.pipeline(
    name='MinIO Trigger Test Pipeline',
    description='Sample pipeline triggered automatically by MinIO file uploads'
)
def sample_trigger_pipeline(s3_uri: str):
    """
    Sample ML pipeline triggered by MinIO upload events.

    This pipeline demonstrates the required contract:
    - Accepts s3_uri parameter (REQUIRED)
    - Can be triggered programmatically via KFP SDK
    - Simulates typical ML workflow steps

    Args:
        s3_uri (str): S3 URI to uploaded file
                      Format: s3://bucket-name/path/to/file.csv
                      Example: s3://ml-datasets/team-fraud/training-2026-03-16.csv
    """
    # Step 1: Print S3 information
    print_task = print_s3_info(s3_uri=s3_uri)

    # Step 2: Simulate data processing
    process_task = simulate_data_processing(s3_uri=s3_uri)
    process_task.after(print_task)

    # Step 3: Log completion
    complete_task = log_completion(processing_result=process_task.output)
    complete_task.after(process_task)


if __name__ == '__main__':
    from kfp import compiler

    # Compile pipeline to YAML
    output_file = 'sample-kfp-pipeline.yaml'

    compiler.Compiler().compile(
        pipeline_func=sample_trigger_pipeline,
        package_path=output_file
    )

    print(f"✅ Pipeline compiled successfully!")
    print(f"   Output: {output_file}")
    print()
    print("Next steps:")
    print("1. Upload to RHOAI:")
    print(f"   kfp pipeline upload -p {output_file}")
    print()
    print("2. Or apply directly to OpenShift:")
    print(f"   oc apply -f {output_file}")
    print()
    print("3. Test manual trigger:")
    print("   python ../scripts/trigger_pipeline.py --s3-uri s3://test-bucket/test-file.csv")
