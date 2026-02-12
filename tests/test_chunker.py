"""
Tests for chunker.py
"""
import unittest
import tempfile
import os
from chunker import Chunker


class TestChunker(unittest.TestCase):
    def setUp(self):
        self.chunker = Chunker()
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_chunk_count_small_file(self):
        """Test chunk count for file smaller than chunk size"""
        chunk_size = 100 * 1024 * 1024  # 100MB
        file_size = 50 * 1024 * 1024    # 50MB
        count = self.chunker.get_chunk_count(file_size, chunk_size)
        self.assertEqual(count, 1)

    def test_get_chunk_count_exact_size(self):
        """Test chunk count for file exactly chunk size"""
        chunk_size = 100 * 1024 * 1024
        file_size = 100 * 1024 * 1024
        count = self.chunker.get_chunk_count(file_size, chunk_size)
        self.assertEqual(count, 1)

    def test_get_chunk_count_multiple_chunks(self):
        """Test chunk count for file requiring multiple chunks"""
        chunk_size = 100 * 1024 * 1024
        file_size = 250 * 1024 * 1024   # 250MB = 3 chunks
        count = self.chunker.get_chunk_count(file_size, chunk_size)
        self.assertEqual(count, 3)

    def test_split_file_streaming(self):
        """Test streaming file splitting"""
        # Create a test file
        test_file = os.path.join(self.temp_dir, 'test.bin')
        test_data = b'A' * 1024 * 1024  # 1MB
        with open(test_file, 'wb') as f:
            f.write(test_data)
        
        chunk_size = 512 * 1024  # 512KB
        chunks = list(self.chunker.split_file_streaming(test_file, chunk_size))
        
        # Should have 2 chunks (1MB / 512KB = 2)
        self.assertEqual(len(chunks), 2)
        
        # Verify first chunk
        index0, data0, offset0, length0 = chunks[0]
        self.assertEqual(index0, 0)
        self.assertEqual(offset0, 0)
        self.assertEqual(length0, chunk_size)
        self.assertEqual(len(data0), chunk_size)
        
        # Verify second chunk
        index1, data1, offset1, length1 = chunks[1]
        self.assertEqual(index1, 1)
        self.assertEqual(offset1, chunk_size)
        self.assertEqual(length1, chunk_size)
        self.assertEqual(len(data1), chunk_size)

    def test_split_file_partial_last_chunk(self):
        """Test splitting where last chunk is partial"""
        test_file = os.path.join(self.temp_dir, 'test.bin')
        test_data = b'B' * (1024 * 1024 + 100)  # 1MB + 100 bytes
        with open(test_file, 'wb') as f:
            f.write(test_data)
        
        chunk_size = 512 * 1024  # 512KB
        chunks = list(self.chunker.split_file_streaming(test_file, chunk_size))
        
        # Should have 3 chunks
        self.assertEqual(len(chunks), 3)
        
        # Last chunk should be smaller
        last_index, last_data, last_offset, last_length = chunks[-1]
        self.assertEqual(last_index, 2)
        self.assertEqual(last_length, 100)
        self.assertEqual(len(last_data), 100)

    def test_reassemble_chunks(self):
        """Test reassembling chunks back into original file"""
        # Create test file
        test_file = os.path.join(self.temp_dir, 'test.bin')
        test_data = b'Test data for reassembly ' * 10000
        with open(test_file, 'wb') as f:
            f.write(test_data)
        
        # Split into chunks
        chunk_size = 50 * 1024
        chunks_data = []
        for _, data, _, _ in self.chunker.split_file_streaming(test_file, chunk_size):
            chunks_data.append(data)
        
        # Reassemble
        output_file = os.path.join(self.temp_dir, 'reassembled.bin')
        self.chunker.reassemble_chunks(chunks_data, output_file)
        
        # Verify
        with open(output_file, 'rb') as f:
            reassembled_data = f.read()
        
        self.assertEqual(test_data, reassembled_data)


if __name__ == '__main__':
    unittest.main()
