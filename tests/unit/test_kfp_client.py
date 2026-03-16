#!/usr/bin/env python3
"""
Unit tests for KFP client wrapper.

Tests service account authentication and pipeline triggering logic.
"""

import os
import pytest
from unittest.mock import Mock, patch, mock_open, MagicMock


# Mock kfp module since it's not installed in test environment
@pytest.fixture(autouse=True)
def mock_kfp_module():
    """Mock kfp module for all tests."""
    with patch.dict('sys.modules', {'kfp': MagicMock()}):
        yield


class TestGetKFPClient:
    """Tests for get_kfp_client() function."""

    @patch('builtins.open', mock_open(read_data='test-service-account-token'))
    @patch('os.path.exists', return_value=True)
    @patch('kfp.Client')
    def test_get_client_with_defaults(self, mock_client_class, mock_exists):
        """Test getting KFP client with default parameters."""
        from scripts.utils.kfp_client import get_kfp_client

        # Mock environment
        with patch.dict(os.environ, {'KFP_HOST': 'https://kfp-api.example.com:8443'}):
            client = get_kfp_client()

            # Verify Client was called with correct parameters
            mock_client_class.assert_called_once()
            call_kwargs = mock_client_class.call_args[1]

            assert call_kwargs['host'] == 'https://kfp-api.example.com:8443'
            assert call_kwargs['existing_token'] == 'test-service-account-token'
            assert 'ssl_ca_cert' in call_kwargs

    @patch('builtins.open', mock_open(read_data='custom-token'))
    @patch('os.path.exists', return_value=True)
    @patch('kfp.Client')
    def test_get_client_with_custom_host(self, mock_client_class, mock_exists):
        """Test getting KFP client with custom host."""
        from scripts.utils.kfp_client import get_kfp_client

        client = get_kfp_client(host='https://custom-kfp.example.com')

        call_kwargs = mock_client_class.call_args[1]
        assert call_kwargs['host'] == 'https://custom-kfp.example.com'

    @patch('os.path.exists', return_value=False)
    def test_get_client_token_not_found(self, mock_exists):
        """Test error when service account token not found."""
        from scripts.utils.kfp_client import get_kfp_client

        with pytest.raises(FileNotFoundError, match="Service account token not found"):
            get_kfp_client()

    @patch('builtins.open', mock_open(read_data=''))
    @patch('os.path.exists', return_value=True)
    def test_get_client_empty_token(self, mock_exists):
        """Test error when service account token is empty."""
        from scripts.utils.kfp_client import get_kfp_client

        with pytest.raises(ValueError, match="Service account token is empty"):
            get_kfp_client()

    @patch('builtins.open', mock_open(read_data='test-token'))
    @patch('os.path.exists', side_effect=[True, False])  # Token exists, CA cert doesn't
    def test_get_client_ca_cert_not_found(self, mock_exists):
        """Test error when CA certificate not found."""
        from scripts.utils.kfp_client import get_kfp_client

        with pytest.raises(FileNotFoundError, match="CA certificate not found"):
            get_kfp_client()


class TestValidatePipelineExists:
    """Tests for validate_pipeline_exists() function."""

    def test_validate_pipeline_found(self):
        """Test finding existing pipeline."""
        from scripts.utils.kfp_client import validate_pipeline_exists

        # Mock client with pipelines
        mock_client = Mock()
        mock_pipeline1 = Mock(name='fraud-detection-v2', id='pipeline-123')
        mock_pipeline2 = Mock(name='recommender-v1', id='pipeline-456')

        mock_response = Mock(pipelines=[mock_pipeline1, mock_pipeline2])
        mock_client.list_pipelines.return_value = mock_response

        # Test finding pipeline
        pipeline_id = validate_pipeline_exists(mock_client, 'fraud-detection-v2')

        assert pipeline_id == 'pipeline-123'
        mock_client.list_pipelines.assert_called_once_with(page_size=1000)

    def test_validate_pipeline_not_found(self):
        """Test when pipeline doesn't exist."""
        from scripts.utils.kfp_client import validate_pipeline_exists

        mock_client = Mock()
        mock_pipeline = Mock(name='other-pipeline', id='pipeline-789')
        mock_response = Mock(pipelines=[mock_pipeline])
        mock_client.list_pipelines.return_value = mock_response

        pipeline_id = validate_pipeline_exists(mock_client, 'non-existent-pipeline')

        assert pipeline_id is None

    def test_validate_pipeline_api_error(self):
        """Test handling of API errors."""
        from scripts.utils.kfp_client import validate_pipeline_exists

        mock_client = Mock()
        mock_client.list_pipelines.side_effect = Exception("API connection error")

        pipeline_id = validate_pipeline_exists(mock_client, 'any-pipeline')

        assert pipeline_id is None


class TestTriggerPipeline:
    """Tests for trigger_pipeline() function."""

    @patch('scripts.utils.kfp_client.validate_pipeline_exists', return_value='pipeline-123')
    def test_trigger_pipeline_success(self, mock_validate):
        """Test successfully triggering a pipeline."""
        from scripts.utils.kfp_client import trigger_pipeline

        # Mock client and run
        mock_client = Mock()
        mock_run = Mock(id='run-456', name='minio-trigger-20260316', status='Pending')
        mock_client.run_pipeline.return_value = mock_run

        # Trigger pipeline
        run = trigger_pipeline(
            mock_client,
            pipeline_name='fraud-detection-v2',
            s3_uri='s3://ml-datasets/team-fraud/data.csv',
            extra_params={'model_type': 'xgboost'}
        )

        # Verify
        assert run.id == 'run-456'
        mock_validate.assert_called_once_with(mock_client, 'fraud-detection-v2')

        # Check run_pipeline was called with correct params
        call_kwargs = mock_client.run_pipeline.call_args[1]
        assert call_kwargs['pipeline_id'] == 'pipeline-123'
        assert call_kwargs['params']['s3_uri'] == 's3://ml-datasets/team-fraud/data.csv'
        assert call_kwargs['params']['model_type'] == 'xgboost'

    @patch('scripts.utils.kfp_client.validate_pipeline_exists', return_value=None)
    def test_trigger_pipeline_not_found(self, mock_validate):
        """Test error when pipeline doesn't exist."""
        from scripts.utils.kfp_client import trigger_pipeline

        mock_client = Mock()

        with pytest.raises(ValueError, match="Pipeline .* not found"):
            trigger_pipeline(
                mock_client,
                pipeline_name='non-existent-pipeline',
                s3_uri='s3://bucket/file.csv'
            )

    @patch('scripts.utils.kfp_client.validate_pipeline_exists', return_value='pipeline-123')
    def test_trigger_pipeline_api_error(self, mock_validate):
        """Test handling of API errors during trigger."""
        from scripts.utils.kfp_client import trigger_pipeline

        mock_client = Mock()
        mock_client.run_pipeline.side_effect = Exception("API error")

        with pytest.raises(Exception, match="Failed to trigger pipeline"):
            trigger_pipeline(
                mock_client,
                pipeline_name='test-pipeline',
                s3_uri='s3://bucket/file.csv'
            )
