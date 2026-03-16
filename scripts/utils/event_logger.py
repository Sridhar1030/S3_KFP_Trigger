#!/usr/bin/env python3
"""
Structured logging utility for MinIO-KFP trigger events.

Provides JSON-formatted logging with correlation IDs and execution tracking.
"""

import json
import logging
import sys
import uuid
from datetime import datetime
from typing import Optional, Dict, Any


class JSONFormatter(logging.Formatter):
    """Custom formatter that outputs logs as JSON."""

    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON.

        Args:
            record: Log record to format

        Returns:
            JSON-formatted log string
        """
        log_data = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'message': record.getMessage(),
        }

        # Add any extra fields from the record
        if hasattr(record, 'log_id'):
            log_data['log_id'] = record.log_id
        if hasattr(record, 'execution_time_ms'):
            log_data['execution_time_ms'] = record.execution_time_ms
        if hasattr(record, 's3_uri'):
            log_data['s3_uri'] = record.s3_uri
        if hasattr(record, 'status'):
            log_data['status'] = record.status
        if hasattr(record, 'pipeline_run_id'):
            log_data['pipeline_run_id'] = record.pipeline_run_id
        if hasattr(record, 'error'):
            log_data['error'] = record.error

        return json.dumps(log_data)


def setup_logger(name: str = 'trigger_pipeline', level: str = 'INFO') -> logging.Logger:
    """
    Set up structured JSON logger.

    Args:
        name: Logger name
        level: Log level (DEBUG, INFO, WARNING, ERROR)

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))

    # Remove any existing handlers
    logger.handlers.clear()

    # Console handler with JSON formatter
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)

    # Don't propagate to root logger
    logger.propagate = False

    return logger


def generate_log_id() -> str:
    """
    Generate unique correlation ID for log entries.

    Returns:
        UUID string
    """
    return str(uuid.uuid4())


def log_trigger_event(
    logger: logging.Logger,
    s3_uri: str,
    status: str,
    log_id: Optional[str] = None,
    pipeline_run_id: Optional[str] = None,
    error: Optional[str] = None,
    execution_time_ms: Optional[int] = None,
    **extra_fields
) -> None:
    """
    Log a structured trigger event.

    Args:
        logger: Logger instance
        s3_uri: S3 URI that triggered the event
        status: Event status (success, failure, no_match)
        log_id: Optional correlation ID (generated if not provided)
        pipeline_run_id: KFP run ID if pipeline was triggered
        error: Error message if status is failure
        execution_time_ms: Execution time in milliseconds
        **extra_fields: Additional fields to include in log
    """
    if log_id is None:
        log_id = generate_log_id()

    # Create log message
    if status == 'success':
        message = f"Pipeline triggered successfully: {pipeline_run_id}"
        log_level = logging.INFO
    elif status == 'failure':
        message = f"Pipeline trigger failed: {error}"
        log_level = logging.ERROR
    elif status == 'no_match':
        message = f"No pipeline route matched for: {s3_uri}"
        log_level = logging.WARNING
    else:
        message = f"Unknown status: {status}"
        log_level = logging.WARNING

    # Build extra data
    extra = {
        'log_id': log_id,
        's3_uri': s3_uri,
        'status': status,
    }

    if pipeline_run_id:
        extra['pipeline_run_id'] = pipeline_run_id
    if error:
        extra['error'] = error
    if execution_time_ms is not None:
        extra['execution_time_ms'] = execution_time_ms

    # Add any additional fields
    extra.update(extra_fields)

    # Log with extra data
    logger.log(log_level, message, extra=extra)


# Example usage
if __name__ == '__main__':
    # Demo: Set up logger and log sample events
    logger = setup_logger(level='INFO')

    # Success event
    log_trigger_event(
        logger,
        s3_uri='s3://ml-datasets/team-fraud/data.csv',
        status='success',
        pipeline_run_id='fraud-run-2026-03-16-abc123',
        execution_time_ms=487
    )

    # Failure event
    log_trigger_event(
        logger,
        s3_uri='s3://ml-datasets/team-fraud/data.csv',
        status='failure',
        error='KFP API returned 401: Unauthorized',
        execution_time_ms=1234
    )

    # No match event
    log_trigger_event(
        logger,
        s3_uri='s3://ml-datasets/unknown-team/data.csv',
        status='no_match',
        execution_time_ms=12
    )
