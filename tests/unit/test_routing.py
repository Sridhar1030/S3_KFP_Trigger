#!/usr/bin/env python3
"""
Unit tests for multi-route scenarios in trigger_pipeline.py

Tests longest-prefix-match routing logic, overlapping prefixes,
and route validation.
"""

import pytest
import sys
import os

# Add scripts directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'scripts'))

from trigger_pipeline import (
    find_route,
    validate_route,
    validate_config_schema,
    parse_s3_uri
)


class TestFindRoute:
    """Test find_route() with multi-route scenarios."""

    def test_exact_prefix_match(self):
        """Test exact prefix matching."""
        config = {
            'routes': [
                {
                    'prefix': 'ml-datasets/team-fraud/',
                    'pipeline': 'fraud-detection-v2',
                    'namespace': 'fraud-team'
                }
            ]
        }

        route = find_route('s3://ml-datasets/team-fraud/data.csv', config)
        assert route is not None
        assert route['pipeline'] == 'fraud-detection-v2'
        assert route['namespace'] == 'fraud-team'

    def test_longest_prefix_match(self):
        """Test longest-prefix-match algorithm with overlapping prefixes."""
        config = {
            'routes': [
                {
                    'prefix': 'ml-datasets/',
                    'pipeline': 'default-pipeline',
                    'namespace': 'default'
                },
                {
                    'prefix': 'ml-datasets/team-fraud/',
                    'pipeline': 'fraud-detection-v2',
                    'namespace': 'fraud-team'
                },
                {
                    'prefix': 'ml-datasets/team-fraud/production/',
                    'pipeline': 'fraud-production-v3',
                    'namespace': 'fraud-prod'
                }
            ]
        }

        # Should match most specific route
        route = find_route('s3://ml-datasets/team-fraud/production/data.csv', config)
        assert route is not None
        assert route['pipeline'] == 'fraud-production-v3'
        assert route['namespace'] == 'fraud-prod'

        # Should match intermediate route
        route = find_route('s3://ml-datasets/team-fraud/staging/data.csv', config)
        assert route is not None
        assert route['pipeline'] == 'fraud-detection-v2'
        assert route['namespace'] == 'fraud-team'

        # Should match default route
        route = find_route('s3://ml-datasets/team-recommender/data.csv', config)
        assert route is not None
        assert route['pipeline'] == 'default-pipeline'
        assert route['namespace'] == 'default'

    def test_multiple_teams_routing(self):
        """Test routing with multiple team-specific routes."""
        config = {
            'routes': [
                {
                    'prefix': 'ml-datasets/team-fraud/',
                    'pipeline': 'fraud-detection-v2',
                    'namespace': 'fraud-team'
                },
                {
                    'prefix': 'ml-datasets/team-recommender/',
                    'pipeline': 'recommender-training-v1',
                    'namespace': 'recommender-team'
                },
                {
                    'prefix': 'ml-datasets/team-nlp/',
                    'pipeline': 'nlp-model-v4',
                    'namespace': 'nlp-team'
                }
            ]
        }

        # Test each team routes to correct pipeline
        route = find_route('s3://ml-datasets/team-fraud/test.csv', config)
        assert route['pipeline'] == 'fraud-detection-v2'

        route = find_route('s3://ml-datasets/team-recommender/test.csv', config)
        assert route['pipeline'] == 'recommender-training-v1'

        route = find_route('s3://ml-datasets/team-nlp/test.csv', config)
        assert route['pipeline'] == 'nlp-model-v4'

    def test_no_match_unmapped_path(self):
        """Test no match for unmapped bucket path."""
        config = {
            'routes': [
                {
                    'prefix': 'ml-datasets/team-fraud/',
                    'pipeline': 'fraud-detection-v2',
                    'namespace': 'fraud-team'
                }
            ]
        }

        route = find_route('s3://ml-datasets/team-unknown/data.csv', config)
        assert route is None

        route = find_route('s3://different-bucket/data.csv', config)
        assert route is None

    def test_disabled_route_ignored(self):
        """Test that disabled routes are not matched."""
        config = {
            'routes': [
                {
                    'prefix': 'ml-datasets/team-fraud/',
                    'pipeline': 'fraud-detection-v2',
                    'namespace': 'fraud-team',
                    'enabled': False
                },
                {
                    'prefix': 'ml-datasets/',
                    'pipeline': 'default-pipeline',
                    'namespace': 'default',
                    'enabled': True
                }
            ]
        }

        # Should skip disabled route and match default
        route = find_route('s3://ml-datasets/team-fraud/data.csv', config)
        assert route is not None
        assert route['pipeline'] == 'default-pipeline'

    def test_invalid_s3_uri_returns_none(self):
        """Test that invalid S3 URI returns None."""
        config = {
            'routes': [
                {
                    'prefix': 'ml-datasets/',
                    'pipeline': 'default-pipeline',
                    'namespace': 'default'
                }
            ]
        }

        route = find_route('http://ml-datasets/data.csv', config)
        assert route is None

        route = find_route('gs://ml-datasets/data.csv', config)
        assert route is None

    def test_route_sorting_by_length(self):
        """Test that routes are correctly sorted by prefix length (longest first)."""
        config = {
            'routes': [
                {'prefix': 'a/', 'pipeline': 'p1', 'namespace': 'n1'},
                {'prefix': 'a/b/', 'pipeline': 'p2', 'namespace': 'n2'},
                {'prefix': 'a/b/c/', 'pipeline': 'p3', 'namespace': 'n3'},
                {'prefix': 'a/b/c/d/', 'pipeline': 'p4', 'namespace': 'n4'}
            ]
        }

        # Should match longest prefix
        route = find_route('s3://a/b/c/d/file.csv', config)
        assert route['pipeline'] == 'p4'

        route = find_route('s3://a/b/c/file.csv', config)
        assert route['pipeline'] == 'p3'

        route = find_route('s3://a/b/file.csv', config)
        assert route['pipeline'] == 'p2'

        route = find_route('s3://a/file.csv', config)
        assert route['pipeline'] == 'p1'


class TestValidateRoute:
    """Test validate_route() function."""

    def test_valid_route(self):
        """Test validation of valid route."""
        route = {
            'prefix': 'ml-datasets/team-fraud/',
            'pipeline': 'fraud-detection-v2',
            'namespace': 'fraud-team'
        }

        valid, error = validate_route(route)
        assert valid is True
        assert error == ""

    def test_missing_prefix(self):
        """Test validation fails when prefix is missing."""
        route = {
            'pipeline': 'fraud-detection-v2',
            'namespace': 'fraud-team'
        }

        valid, error = validate_route(route)
        assert valid is False
        assert 'prefix' in error.lower()

    def test_missing_pipeline(self):
        """Test validation fails when pipeline is missing."""
        route = {
            'prefix': 'ml-datasets/team-fraud/',
            'namespace': 'fraud-team'
        }

        valid, error = validate_route(route)
        assert valid is False
        assert 'pipeline' in error.lower()

    def test_missing_namespace(self):
        """Test validation fails when namespace is missing."""
        route = {
            'prefix': 'ml-datasets/team-fraud/',
            'pipeline': 'fraud-detection-v2'
        }

        valid, error = validate_route(route)
        assert valid is False
        assert 'namespace' in error.lower()

    def test_prefix_without_trailing_slash(self):
        """Test validation fails when prefix doesn't end with /."""
        route = {
            'prefix': 'ml-datasets/team-fraud',  # Missing trailing /
            'pipeline': 'fraud-detection-v2',
            'namespace': 'fraud-team'
        }

        valid, error = validate_route(route)
        assert valid is False
        assert '/' in error

    def test_invalid_enabled_type(self):
        """Test validation fails when enabled field is not boolean."""
        route = {
            'prefix': 'ml-datasets/team-fraud/',
            'pipeline': 'fraud-detection-v2',
            'namespace': 'fraud-team',
            'enabled': 'true'  # Should be boolean
        }

        valid, error = validate_route(route)
        assert valid is False
        assert 'boolean' in error.lower()

    def test_invalid_parameters_type(self):
        """Test validation fails when parameters field is not dict."""
        route = {
            'prefix': 'ml-datasets/team-fraud/',
            'pipeline': 'fraud-detection-v2',
            'namespace': 'fraud-team',
            'parameters': 'model_type=xgboost'  # Should be dict
        }

        valid, error = validate_route(route)
        assert valid is False
        assert 'dict' in error.lower()

    def test_route_with_optional_fields(self):
        """Test validation passes with optional fields."""
        route = {
            'prefix': 'ml-datasets/team-fraud/',
            'pipeline': 'fraud-detection-v2',
            'namespace': 'fraud-team',
            'enabled': True,
            'parameters': {'model_type': 'xgboost', 'epochs': 100}
        }

        valid, error = validate_route(route)
        assert valid is True
        assert error == ""


class TestValidateConfigSchema:
    """Test validate_config_schema() function."""

    def test_valid_config(self):
        """Test validation of valid configuration."""
        config = {
            'routes': [
                {
                    'prefix': 'ml-datasets/team-fraud/',
                    'pipeline': 'fraud-detection-v2',
                    'namespace': 'fraud-team'
                },
                {
                    'prefix': 'ml-datasets/',
                    'pipeline': 'default-pipeline',
                    'namespace': 'default'
                }
            ]
        }

        # Should not raise exception
        validate_config_schema(config)

    def test_config_not_dict(self):
        """Test validation fails when config is not a dictionary."""
        with pytest.raises(ValueError, match='must be a dictionary'):
            validate_config_schema([{'prefix': 'test/', 'pipeline': 'p', 'namespace': 'n'}])

    def test_missing_routes_key(self):
        """Test validation fails when routes key is missing."""
        config = {'pipelines': []}

        with pytest.raises(ValueError, match='routes'):
            validate_config_schema(config)

    def test_routes_not_list(self):
        """Test validation fails when routes is not a list."""
        config = {'routes': 'not a list'}

        with pytest.raises(ValueError, match='must be a list'):
            validate_config_schema(config)

    def test_empty_routes_list(self):
        """Test validation fails when routes list is empty."""
        config = {'routes': []}

        with pytest.raises(ValueError, match='cannot be empty'):
            validate_config_schema(config)

    def test_route_not_dict(self):
        """Test validation fails when route is not a dictionary."""
        config = {'routes': ['not a dict']}

        with pytest.raises(ValueError, match='must be a dictionary'):
            validate_config_schema(config)

    def test_invalid_route_in_list(self):
        """Test validation fails when one route is invalid."""
        config = {
            'routes': [
                {
                    'prefix': 'ml-datasets/',
                    'pipeline': 'default-pipeline',
                    'namespace': 'default'
                },
                {
                    'prefix': 'ml-datasets/team-fraud',  # Missing trailing /
                    'pipeline': 'fraud-detection-v2',
                    'namespace': 'fraud-team'
                }
            ]
        }

        with pytest.raises(ValueError, match='Route 1 validation failed'):
            validate_config_schema(config)


class TestParseS3Uri:
    """Test parse_s3_uri() function."""

    def test_parse_valid_uri(self):
        """Test parsing valid S3 URI."""
        bucket, key = parse_s3_uri('s3://ml-datasets/team-fraud/data.csv')
        assert bucket == 'ml-datasets'
        assert key == 'team-fraud/data.csv'

    def test_parse_uri_with_nested_path(self):
        """Test parsing URI with deeply nested path."""
        bucket, key = parse_s3_uri('s3://my-bucket/path/to/nested/file.csv')
        assert bucket == 'my-bucket'
        assert key == 'path/to/nested/file.csv'

    def test_parse_uri_with_bucket_only(self):
        """Test parsing URI with bucket but no key."""
        bucket, key = parse_s3_uri('s3://my-bucket')
        assert bucket == 'my-bucket'
        assert key == ''

    def test_parse_uri_with_bucket_and_slash(self):
        """Test parsing URI with bucket and trailing slash."""
        bucket, key = parse_s3_uri('s3://my-bucket/')
        assert bucket == 'my-bucket'
        assert key == ''

    def test_parse_invalid_uri_format(self):
        """Test parsing fails for invalid URI format."""
        with pytest.raises(ValueError, match='Invalid S3 URI format'):
            parse_s3_uri('http://my-bucket/file.csv')

        with pytest.raises(ValueError, match='Invalid S3 URI format'):
            parse_s3_uri('gs://my-bucket/file.csv')

        with pytest.raises(ValueError, match='Invalid S3 URI format'):
            parse_s3_uri('/local/path/file.csv')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
