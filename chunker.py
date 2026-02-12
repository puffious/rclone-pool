"""
File chunking — splits files into chunks using streaming (minimal RAM/disk usage).
"""

# rclonepool/chunker.py

import os
import logging
from typing import Generator, Tuple

log = logging.getLogger('rclonepool')


class Chunker:
    def __init__(self, config):
        self.config = config

    def split_file_streaming(self, file_path: str, chunk_size: int) -> Generator[Tuple[int, bytes, int, int], None, None]:
        """
        Stream a file in chunks. Yields (chunk_index, chunk_data, offset, length).
        
        Each chunk is held in memory only while being processed.
        Memory usage = chunk_size (100MB default).
        """
        offset = 0
        chunk_index = 0

        with open(file_path, 'rb') as f:
            while True:
                data = f.read(chunk_size)
                if not data:
                    break

                yield (chunk_index, data, offset, len(data))

                offset += len(data)
                chunk_index += 1

    def get_chunk_count(self, file_size: int, chunk_size: int) -> int:
        """Calculate number of chunks for a given file size."""
        return (file_size + chunk_size - 1) // chunk_size

    def reassemble_chunks(self, chunks: list, output_path: str):
        """
        Reassemble chunks into a file.
        chunks: list of (index, data) tuples (must be sorted by index).
        """
        with open(output_path, 'wb') as f:
            for index, data in sorted(chunks, key=lambda x: x[0]):
                f.write(data)