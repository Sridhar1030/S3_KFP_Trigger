#!/usr/bin/env python3
"""
Unit tests for trigger_pipeline routing logic.

Tests configuration loading, route matching, and S3 URI parsing.
"""

import os
import pytest
import tempfile
import yaml
from unittest.mock import patch, mock_open

# Add scripts directory to path
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../scripts'))

from trigger_pipeline import load_config, find_route, parse_s3_uri


class TestLoadConfig:
    """Tests for load_config() function."""

    def test_load_valid_config(self):
        """Test loading valid configuration file."""
        config_data = """
routes:
  - prefix: "ml-datasets/team-fraud/"
    pipeline: "fraud-detection-v2"
    namespace: "s3-kfp-trigger"
    enabled: true
  - prefix: "ml-datasets/"
    pipeline: "default-pipeline"
    namespace: "s3-kfp-trigger"
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(config_data)
            config_path = f.name

        try:
            config = load_config(config_path)

            assert 'routes' in config
            assert len(config['routes']) == 2
            assert config['routes'][0]['pipeline'] == 'fraud-detection-v2'
            assert config['routes'][1]['pipeline'] == 'default-pipeline'
        finally:
            os.unlink(config_path)

    def test_load_config_file_not_found(self):
        """Test error when config file doesn't exist."""
        with pytest.raises(FileNotFoundError, match="Pipeline mappings configuration not found"):
            load_config('/non/existent/path.yaml')

    def test_load_config_invalid_yaml(self):
        """Test error when config file is invalid YAML."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("invalid: yaml: content:\n  - broken")
            config_path = f.name

        try:
            with pytest.raises(yaml.YAMLError):
                load_config(config_path)
        finally:
            os.unlink(config_path)

    def test_load_config_missing_routes_key(self):
        """Test error when 'routes' key is missing."""
        config_data = """
other_key: value
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(config_data)
            config_path = f.name

        try:
            with pytest.raises(ValueError, match="'routes' key not found"):
                load_config(config_path)
        finally:
            os.unlink(config_path)


class TestFindRoute:
    """Tests for find_route() function."""

    def test_find_route_exact_match(self):
        """Test finding route with exact prefix match."""
        config = {
            'routes': [
                {
                    'prefix': 'ml-datasets/team-fraud/',
                    'pipeline': 'fraud-detection-v2',
                    'enabled': True
                }
            ]
        }

        route = find_route('s3://ml-datasets/team-fraud/data.csv', config)

        assert route is not None
        assert route['pipeline'] == 'fraud-detection-v2'

    def test_find_route_longest_prefix_match(self):
        """Test longest-prefix-match algorithm."""
        config = {
            'routes': [
                {
                    'prefix': 'ml-datasets/',
                    'pipeline': 'default-pipeline',
                    'enabled': True
                },
                {
                    'prefix': 'ml-datasets/team-fraud/',
                    'pipeline': 'fraud-detection-v2',
                    'enabled': True
                },
                {
                    'prefix': 'ml-datasets/team-fraud/production/',
                    'pipeline': 'fraud-production-v3',
                    'enabled': True
                }
            ]
        }

        # Should match most specific route
        route = find_route('s3://ml-datasets/team-fraud/production/data.csv', config)
        assert route['pipeline'] == 'fraud-production-v3'

        # Should match second most specific
        route = find_route('s3://ml-datasets/team-fraud/staging/data.csv', config)
        assert route['pipeline'] == 'fraud-detection-v2'

        # Should match least specific (default)
        route = find_route('s3://ml-datasets/team-other/data.csv', config)
        assert route['pipeline'] == 'default-pipeline'

    def test_find_route_disabled_route(self):
        """Test that disabled routes are skipped."""
        config = {
            'routes': [
                {
                    'prefix': 'ml-datasets/team-fraud/',
                    'pipeline': 'fraud-disabled',
                    'enabled': False  # Disabled
                },
                {
                    'prefix': 'ml-datasets/',
                    'pipeline': 'default-pipeline',
                    'enabled': True
                }
            ]
        }

        route = find_route('s3://ml-datasets/team-fraud/data.csv', config)

        # Should skip disabled route and match default
        assert route is not None
        assert route['pipeline'] == 'default-pipeline'

    def test_find_route_no_match(self):
        """Test when no route matches."""
        config = {
            'routes': [
                {
                    'prefix': 'ml-datasets/team-fraud/',
                    'pipeline': 'fraud-detection',
                    'enabled': True
                }
            ]
        }

        route = find_route('s3://other-bucket/file.csv', config)

        assert route is None

    def test_find_route_invalid_s3_uri(self):
        """Test with invalid S3 URI format."""
        config = {
            'routes': [
                {
                    'prefix': 'ml-datasets/',
                    'pipeline': 'default',
                    'enabled': True
                }
            ]
        }

        route = find_route('http://not-s3-uri.com/file.csv', config)

        assert route is None

    def test_find_route_empty_routes(self):
        """Test with empty routes list."""
        config = {'routes': []}

        route = find_route('s3://bucket/file.csv', config)

        assert route is None


class TestParseS3Uri:
    """Tests for parse_s3_uri() function."""

    def test_parse_valid_uri(self):
        """Test parsing valid S3 URI."""
        bucket, key = parse_s3_uri('s3://ml-datasets/team-fraud/data.csv')

        assert bucket == 'ml-datasets'
        assert key == 'team-fraud/data.csv'

    def test_parse_uri_with_nested_path(self):
        """Test parsing URI with nested directory structure."""
        bucket, key = parse_s3_uri('s3://my-bucket/path/to/deep/file.csv')

        assert bucket == 'my-bucket'
        assert key == 'path/to/deep/file.csv'

    def test_parse_uri_bucket_only(self):
        """Test parsing URI with just bucket (no key)."""
        bucket, key = parse_s3_uri('s3://my-bucket')

        assert bucket == 'my-bucket'
        assert key == ''

    def test_parse_uri_bucket_with_slash(self):
        """Test parsing URI with bucket and trailing slash."""
        bucket, key = parse_s3_uri('s3://my-bucket/')

        assert bucket == 'my-bucket'
        assert key == ''

    def test_parse_invalid_uri_format(self):
        """Test error with invalid S3 URI format."""
        with pytest.raises(ValueError, match="Invalid S3 URI format"):
            parse_s3_uri('http://not-s3.com/file.csv')

    def test_parse_invalid_uri_no_scheme(self):
        """Test error with URI missing s3:// scheme."""
        with pytest.raises(ValueError, match="Invalid S3 URI format"):
            parse_s3_uri('bucket/file.csv')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
