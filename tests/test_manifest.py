"""
Tests for manifest.py
"""
import unittest
import tempfile
import json
import os
from manifest import ManifestManager
from config import Config


class TestManifestManager(unittest.TestCase):
    def setUp(self):
        self.config_dir = tempfile.mkdtemp()
        self.config_file = os.path.join(self.config_dir, 'config.json')
        
        config_data = {
            "remotes": ["test1:", "test2:"],
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
        self.mock_backend = MockBackend()
        self.mgr = ManifestManager(self.config, self.mock_backend)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.config_dir, ignore_errors=True)

    def test_create_manifest(self):
        """Test manifest creation"""
        chunks = [
            {'index': 0, 'remote': 'test1:', 'path': 'data/test.chunk.000', 'size': 100, 'offset': 0}
        ]
        
        manifest = self.mgr.create_manifest(
            file_name='test.txt',
            remote_dir='/documents',
            file_size=100,
            chunk_size=104857600,
            chunks=chunks
        )
        
        self.assertEqual(manifest['file_name'], 'test.txt')
        self.assertEqual(manifest['remote_dir'], '/documents')
        self.assertEqual(manifest['file_path'], '/documents/test.txt')
        self.assertEqual(manifest['file_size'], 100)
        self.assertEqual(manifest['chunk_count'], 1)
        self.assertEqual(len(manifest['chunks']), 1)
        self.assertIn('created_at', manifest)
        self.assertIn('checksum', manifest)

    def test_manifest_remote_path(self):
        """Test manifest path generation"""
        path1 = self.mgr._manifest_remote_path('/movies/film.mkv')
        self.assertTrue(path1.endswith('.manifest.json'))
        self.assertIn('rclonepool_manifests', path1)
        
        path2 = self.mgr._manifest_remote_path('/documents/folder/file.txt')
        self.assertTrue(path2.endswith('.manifest.json'))

    def test_manifest_cache(self):
        """Test manifest caching"""
        chunks = [
            {'index': 0, 'remote': 'test1:', 'path': 'data/test.chunk.000', 'size': 100, 'offset': 0}
        ]
        
        manifest = self.mgr.create_manifest(
            file_name='cached.txt',
            remote_dir='/',
            file_size=100,
            chunk_size=104857600,
            chunks=chunks
        )
        
        # Save manifest (which caches it)
        self.mgr.save_manifest(manifest)
        
        # Should be in cache
        self.assertIn('/cached.txt', self.mgr._manifest_cache)


class MockBackend:
    """Mock backend for testing"""
    def __init__(self):
        self.manifests = {}
    
    def upload_bytes(self, data, remote, remote_path):
        self.manifests[remote_path] = data
        return True
    
    def download_bytes(self, remote, remote_path, suppress_errors=False):
        return self.manifests.get(remote_path)
    
    def list_files(self, remote, prefix):
        return []


if __name__ == '__main__':
    unittest.main()
