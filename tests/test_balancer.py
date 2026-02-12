"""
Tests for balancer.py
"""
import unittest
from balancer import Balancer
from config import Config
import tempfile
import json
import os


class TestBalancer(unittest.TestCase):
    def setUp(self):
        # Create a temporary config
        self.config_dir = tempfile.mkdtemp()
        self.config_file = os.path.join(self.config_dir, 'config.json')
        
        config_data = {
            "remotes": ["test1:", "test2:", "test3:"],
            "chunk_size": 104857600,
            "data_prefix": "rclonepool_data",
            "manifest_prefix": "rclonepool_manifests",
            "use_crypt": False,
            "temp_dir": "/tmp/rclonepool",
            "rclone_binary": "rclone",
            "rclone_flags": [],
            "webdav_port": 8080,
            "webdav_host": "0.0.0.0"
        }
        
        with open(self.config_file, 'w') as f:
            json.dump(config_data, f)
        
        self.config = Config(self.config_file)
        
        # Mock RcloneBackend
        self.mock_backend = MockRcloneBackend()
        self.balancer = Balancer(self.config, self.mock_backend)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.config_dir, ignore_errors=True)

    def test_get_least_used_remote(self):
        """Test getting the remote with least usage"""
        # Manually set usage
        self.balancer._usage = {
            'test1:': 1000000000,  # 1GB
            'test2:': 500000000,   # 500MB (least)
            'test3:': 2000000000   # 2GB
        }
        
        least_used = self.balancer.get_least_used_remote()
        self.assertEqual(least_used, 'test2:')

    def test_record_usage(self):
        """Test recording usage updates"""
        initial_usage = self.balancer._usage.get('test1:', 0)
        self.balancer.record_usage('test1:', 100000000)  # 100MB
        
        new_usage = self.balancer._usage.get('test1:', 0)
        self.assertEqual(new_usage, initial_usage + 100000000)

    def test_get_usage_report(self):
        """Test getting usage report"""
        report = self.balancer.get_usage_report()
        
        # Should have entries for all remotes
        self.assertEqual(len(report), 3)
        
        # Check structure
        for entry in report:
            self.assertIn('remote', entry)
            self.assertIn('used', entry)
            self.assertIn('total', entry)
            self.assertIn('free', entry)
            self.assertIn('percent', entry)


class MockRcloneBackend:
    """Mock backend for testing"""
    def get_space(self, remote):
        # Return mock space data
        return {
            'used': 1000000000,
            'total': 20000000000,
            'free': 19000000000
        }


if __name__ == '__main__':
    unittest.main()
