"""
Tests for config.py
"""
import unittest
import tempfile
import json
import os
from config import Config


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.config_dir = tempfile.mkdtemp()
        self.config_file = os.path.join(self.config_dir, 'config.json')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.config_dir, ignore_errors=True)

    def test_load_valid_config(self):
        """Test loading a valid config file"""
        config_data = {
            "remotes": ["mega1:", "mega2:"],
            "chunk_size": 104857600,
            "data_prefix": "rclonepool_data",
            "manifest_prefix": "rclonepool_manifests",
            "use_crypt": True,
            "crypt_remotes": ["crypt-mega1:", "crypt-mega2:"],
            "temp_dir": "/dev/shm/rclonepool",
            "rclone_binary": "rclone",
            "rclone_flags": ["--fast-list"],
            "webdav_port": 8080,
            "webdav_host": "0.0.0.0"
        }
        
        with open(self.config_file, 'w') as f:
            json.dump(config_data, f)
        
        config = Config(self.config_file)
        
        self.assertEqual(len(config.remotes), 2)
        self.assertEqual(config.chunk_size, 104857600)
        self.assertEqual(config.data_prefix, "rclonepool_data")
        self.assertEqual(config.manifest_prefix, "rclonepool_manifests")
        self.assertTrue(config.use_crypt)
        self.assertEqual(len(config.crypt_remotes), 2)
        self.assertEqual(config.webdav_port, 8080)

    def test_config_defaults(self):
        """Test config with missing optional fields uses defaults"""
        config_data = {
            "remotes": ["test1:"],
            "chunk_size": 104857600
        }
        
        with open(self.config_file, 'w') as f:
            json.dump(config_data, f)
        
        config = Config(self.config_file)
        
        # Check defaults
        self.assertEqual(config.data_prefix, "rclonepool_data")
        self.assertEqual(config.manifest_prefix, "rclonepool_manifests")
        self.assertFalse(config.use_crypt)
        self.assertEqual(config.webdav_port, 8080)
        self.assertEqual(config.webdav_host, "0.0.0.0")

    def test_crypt_remotes_used_when_enabled(self):
        """Test that crypt remotes are used when use_crypt is True"""
        config_data = {
            "remotes": ["mega1:", "mega2:"],
            "chunk_size": 104857600,
            "use_crypt": True,
            "crypt_remotes": ["crypt-mega1:", "crypt-mega2:"]
        }
        
        with open(self.config_file, 'w') as f:
            json.dump(config_data, f)
        
        config = Config(self.config_file)
        
        # When use_crypt is True and crypt_remotes exist, remotes should be crypt_remotes
        self.assertEqual(config.remotes, ["crypt-mega1:", "crypt-mega2:"])

    def test_base_remotes_used_when_crypt_disabled(self):
        """Test that base remotes are used when use_crypt is False"""
        config_data = {
            "remotes": ["mega1:", "mega2:"],
            "chunk_size": 104857600,
            "use_crypt": False,
            "crypt_remotes": ["crypt-mega1:", "crypt-mega2:"]
        }
        
        with open(self.config_file, 'w') as f:
            json.dump(config_data, f)
        
        config = Config(self.config_file)
        
        # When use_crypt is False, use base remotes
        self.assertEqual(config.remotes, ["mega1:", "mega2:"])


if __name__ == '__main__':
    unittest.main()
