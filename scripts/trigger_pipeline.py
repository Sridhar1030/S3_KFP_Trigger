#!/usr/bin/env python3
"""
MinIO-KFP Pipeline Trigger Script

Triggered by Tekton TaskRun when MinIO webhook events are received.
Routes S3 URIs to appropriate Kubeflow pipelines based on bucket path.
"""

import argparse
import os
import sys
import time
from typing import Optional, Dict, Any

import yaml

# Import utilities
from utils.event_logger import setup_logger, log_trigger_event, generate_log_id
from utils.kfp_client import get_kfp_client, trigger_pipeline


# Exit codes
EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_NO_MATCH = 2


def load_config(config_path: str) -> Dict[str, Any]:
    """
    Load pipeline routing configuration from YAML file.

    Args:
        config_path: Path to pipeline-mappings.yaml

    Returns:
        Configuration dictionary with 'routes' key

    Raises:
        FileNotFoundError: If config file not found
        yaml.YAMLError: If config file is invalid YAML
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"Pipeline mappings configuration not found: {config_path}\n"
            f"Ensure the ConfigMap is mounted at {config_path}"
        )

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    if not config or 'routes' not in config:
        raise ValueError(
            f"Invalid configuration: 'routes' key not found in {config_path}"
        )

    return config


def find_route(s3_uri: str, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Find matching pipeline route for S3 URI using longest-prefix-match.

    Args:
        s3_uri: Full S3 URI (e.g., s3://ml-datasets/team-fraud/data.csv)
        config: Configuration dictionary from load_config()

    Returns:
        Matching route dict or None if no match

    Example:
        >>> config = {'routes': [
        ...     {'prefix': 'ml-datasets/team-fraud/', 'pipeline': 'fraud-v2'},
        ...     {'prefix': 'ml-datasets/', 'pipeline': 'default'}
        ... ]}
        >>> route = find_route('s3://ml-datasets/team-fraud/data.csv', config)
        >>> route['pipeline']
        'fraud-v2'
    """
    # Strip s3:// prefix
    if not s3_uri.startswith('s3://'):
        return None

    bucket_key = s3_uri[5:]  # Remove 's3://'

    # Get routes and sort by prefix length (longest first for longest-prefix-match)
    routes = config.get('routes', [])
    sorted_routes = sorted(routes, key=lambda r: len(r.get('prefix', '')), reverse=True)

    # Find first matching route
    for route in sorted_routes:
        prefix = route.get('prefix', '')
        enabled = route.get('enabled', True)

        if enabled and bucket_key.startswith(prefix):
            return route

    return None


def parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    """
    Parse S3 URI into bucket and key.

    Args:
        s3_uri: Full S3 URI (e.g., s3://bucket/path/file.csv)

    Returns:
        Tuple of (bucket, object_key)

    Example:
        >>> bucket, key = parse_s3_uri('s3://ml-datasets/team-fraud/data.csv')
        >>> bucket
        'ml-datasets'
        >>> key
        'team-fraud/data.csv'
    """
    if not s3_uri.startswith('s3://'):
        raise ValueError(f"Invalid S3 URI format: {s3_uri}")

    parts = s3_uri[5:].split('/', 1)
    bucket = parts[0]
    object_key = parts[1] if len(parts) > 1 else ''

    return bucket, object_key


def main():
    """
    Main entry point for pipeline trigger script.

    Reads CLI arguments, loads configuration, routes S3 URI to pipeline,
    and triggers KFP pipeline run.

    Exit codes:
        0: Success - pipeline triggered
        1: Failure - error occurred
        2: No match - no route found for S3 URI
    """
    # Parse CLI arguments
    parser = argparse.ArgumentParser(
        description='Trigger Kubeflow pipeline from MinIO upload event'
    )
    parser.add_argument(
        '--s3-uri',
        required=True,
        help='S3 URI to uploaded file (e.g., s3://bucket/path/file.csv)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Validate routing logic without triggering pipeline'
    )

    args = parser.parse_args()
    s3_uri = args.s3_uri
    dry_run = args.dry_run

    # Set up logging
    log_level = os.getenv('LOG_LEVEL', 'INFO')
    logger = setup_logger('trigger_pipeline', level=log_level)

    # Generate correlation ID
    log_id = generate_log_id()

    # Track execution time
    start_time = time.time()

    try:
        # Load configuration
        config_path = os.getenv('PIPELINE_MAPPINGS_PATH', '/config/mappings.yaml')
        config = load_config(config_path)

        logger.info(f"Configuration loaded from {config_path}")
        logger.info(f"Processing S3 URI: {s3_uri}")

        # Find matching route
        route = find_route(s3_uri, config)

        if not route:
            # No route matched - log and exit with code 2
            execution_time_ms = int((time.time() - start_time) * 1000)
            bucket, object_key = parse_s3_uri(s3_uri)

            log_trigger_event(
                logger,
                s3_uri=s3_uri,
                status='no_match',
                log_id=log_id,
                execution_time_ms=execution_time_ms,
                bucket=bucket,
                object_key=object_key
            )

            return EXIT_NO_MATCH

        # Route found
        pipeline_name = route['pipeline']
        namespace = route.get('namespace', os.getenv('NAMESPACE', 's3-kfp-trigger'))
        extra_params = route.get('parameters', {})

        logger.info(f"Route matched: {route['prefix']} → {pipeline_name}")

        if dry_run:
            logger.info(f"DRY RUN - would trigger pipeline: {pipeline_name}")
            logger.info(f"  Namespace: {namespace}")
            logger.info(f"  Parameters: s3_uri={s3_uri}, {extra_params}")
            return EXIT_SUCCESS

        # Get KFP client
        kfp_host = os.getenv('KFP_HOST')
        client = get_kfp_client(host=kfp_host)

        logger.info(f"Connected to KFP API: {kfp_host or 'default'}")

        # Trigger pipeline
        run = trigger_pipeline(
            client,
            pipeline_name=pipeline_name,
            s3_uri=s3_uri,
            namespace=namespace,
            extra_params=extra_params
        )

        # Success - log and exit with code 0
        execution_time_ms = int((time.time() - start_time) * 1000)
        bucket, object_key = parse_s3_uri(s3_uri)

        log_trigger_event(
            logger,
            s3_uri=s3_uri,
            status='success',
            log_id=log_id,
            pipeline_run_id=run.id,
            execution_time_ms=execution_time_ms,
            bucket=bucket,
            object_key=object_key,
            pipeline_name=pipeline_name,
            namespace=namespace
        )

        return EXIT_SUCCESS

    except FileNotFoundError as e:
        # Configuration file not found
        execution_time_ms = int((time.time() - start_time) * 1000)

        log_trigger_event(
            logger,
            s3_uri=s3_uri,
            status='failure',
            log_id=log_id,
            error=f"Configuration error: {str(e)}",
            execution_time_ms=execution_time_ms
        )

        return EXIT_FAILURE

    except ValueError as e:
        # Invalid configuration, S3 URI, or pipeline not found
        execution_time_ms = int((time.time() - start_time) * 1000)

        log_trigger_event(
            logger,
            s3_uri=s3_uri,
            status='failure',
            log_id=log_id,
            error=f"Validation error: {str(e)}",
            execution_time_ms=execution_time_ms
        )

        return EXIT_FAILURE

    except ImportError as e:
        # KFP module not installed
        execution_time_ms = int((time.time() - start_time) * 1000)

        log_trigger_event(
            logger,
            s3_uri=s3_uri,
            status='failure',
            log_id=log_id,
            error=f"KFP module not installed: {str(e)}",
            execution_time_ms=execution_time_ms
        )

        return EXIT_FAILURE

    except Exception as e:
        # Unexpected error
        execution_time_ms = int((time.time() - start_time) * 1000)

        log_trigger_event(
            logger,
            s3_uri=s3_uri,
            status='failure',
            log_id=log_id,
            error=f"Unexpected error: {str(e)}",
            execution_time_ms=execution_time_ms
        )

        return EXIT_FAILURE


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
