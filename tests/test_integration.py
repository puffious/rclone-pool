"""
Integration tests for rclonepool.
Tests the full workflow with local file system remotes.
"""
import unittest
import tempfile
import shutil
import os
import json
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from rclonepool import RclonePool


class TestRclonePoolIntegration(unittest.TestCase):
    """Integration tests using local file system as remotes"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test environment once for all tests"""
        cls.test_dir = tempfile.mkdtemp(prefix='rclonepool_test_')
        cls.config_dir = os.path.join(cls.test_dir, 'config')
        cls.remote_dir = os.path.join(cls.test_dir, 'remotes')
        cls.temp_dir = os.path.join(cls.test_dir, 'temp')
        cls.data_dir = os.path.join(cls.test_dir, 'data')
        
        os.makedirs(cls.config_dir)
        os.makedirs(cls.temp_dir)
        os.makedirs(cls.data_dir)
        
        # Create fake remotes
        cls.remote1 = os.path.join(cls.remote_dir, 'remote1')
        cls.remote2 = os.path.join(cls.remote_dir, 'remote2')
        os.makedirs(cls.remote1)
        os.makedirs(cls.remote2)
        
        # Create rclone config for local remotes
        rclone_config = os.path.join(cls.config_dir, 'rclone.conf')
        with open(rclone_config, 'w') as f:
            f.write(f"""[local1]
type = local
nounc = true

[local2]
type = local
nounc = true
""")
        
        # Set rclone config env var
        os.environ['RCLONE_CONFIG'] = rclone_config
        
        # Create rclonepool config
        cls.config_file = os.path.join(cls.config_dir, 'config.json')
        config_data = {
            "remotes": [f"local1:{cls.remote1}/", f"local2:{cls.remote2}/"],
            "chunk_size": 1024 * 100,  # 100KB for testing
            "data_prefix": "rclonepool_data",
            "manifest_prefix": "rclonepool_manifests",
            "use_crypt": False,
            "temp_dir": cls.temp_dir,
            "rclone_binary": "rclone",
            "rclone_flags": [],
            "webdav_port": 8080,
            "webdav_host": "127.0.0.1"
        }
        
        with open(cls.config_file, 'w') as f:
            json.dump(config_data, f)

    @classmethod
    def tearDownClass(cls):
        """Clean up test environment"""
        if 'RCLONE_CONFIG' in os.environ:
            del os.environ['RCLONE_CONFIG']
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        """Set up before each test"""
        # Check if rclone is available
        import subprocess
        try:
            subprocess.run(['rclone', 'version'], 
                         capture_output=True, 
                         timeout=5,
                         check=True)
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            self.skipTest("rclone not available")
        
        self.pool = RclonePool(self.config_file)

    def test_upload_small_file(self):
        """Test uploading a file smaller than chunk size"""
        # Create test file
        test_file = os.path.join(self.data_dir, 'small.txt')
        test_data = b'Small test file content'
        with open(test_file, 'wb') as f:
            f.write(test_data)
        
        # Upload
        success = self.pool.upload(test_file, '/test/small.txt')
        self.assertTrue(success)
        
        # Verify manifest exists
        manifest = self.pool.manifest_mgr.load_manifest_for_file('/test/small.txt')
        self.assertIsNotNone(manifest)
        self.assertEqual(manifest['file_size'], len(test_data))
        self.assertEqual(manifest['chunk_count'], 1)

    def test_upload_download_roundtrip(self):
        """Test uploading and downloading a file"""
        # Create test file
        test_file = os.path.join(self.data_dir, 'roundtrip.bin')
        test_data = b'X' * 50000  # 50KB
        with open(test_file, 'wb') as f:
            f.write(test_data)
        
        # Upload
        success = self.pool.upload(test_file, '/roundtrip.bin')
        self.assertTrue(success)
        
        # Download
        output_file = os.path.join(self.data_dir, 'downloaded.bin')
        success = self.pool.download('/roundtrip.bin', output_file)
        self.assertTrue(success)
        
        # Verify content matches
        with open(output_file, 'rb') as f:
            downloaded_data = f.read()
        
        self.assertEqual(test_data, downloaded_data)

    def test_list_files(self):
        """Test listing files"""
        # Upload a couple files
        for i in range(2):
            test_file = os.path.join(self.data_dir, f'file{i}.txt')
            with open(test_file, 'wb') as f:
                f.write(f'File {i}'.encode())
            self.pool.upload(test_file, f'/list_test/file{i}.txt')
        
        # List files
        files = self.pool.ls('/list_test')
        self.assertEqual(len(files), 2)

    def test_delete_file(self):
        """Test deleting a file"""
        # Upload file
        test_file = os.path.join(self.data_dir, 'deleteme.txt')
        with open(test_file, 'wb') as f:
            f.write(b'Delete this')
        
        self.pool.upload(test_file, '/deleteme.txt')
        
        # Verify it exists
        manifest = self.pool.manifest_mgr.load_manifest_for_file('/deleteme.txt')
        self.assertIsNotNone(manifest)
        
        # Delete
        success = self.pool.delete('/deleteme.txt')
        self.assertTrue(success)
        
        # Verify it's gone
        manifest = self.pool.manifest_mgr.load_manifest_for_file('/deleteme.txt')
        self.assertIsNone(manifest)


if __name__ == '__main__':
    # Run with verbose output
    unittest.main(verbosity=2)
