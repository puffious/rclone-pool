"""
Performance enhancements for rclonepool.
Part of v0.3 Performance features.

Provides:
- Parallel chunk uploads/downloads
- Progress bars for CLI operations
- Prefetching for sequential reads
- Connection pooling via rclone rcd
"""

import os
import time
import logging
import threading
import queue
from typing import List, Tuple, Optional, Callable, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

log = logging.getLogger("rclonepool")


@dataclass
class ProgressInfo:
    """Progress information for an operation."""

    total_bytes: int
    completed_bytes: int
    total_items: int
    completed_items: int
    start_time: float
    current_item: str = ""

    @property
    def percent(self) -> float:
        """Get completion percentage."""
        if self.total_bytes == 0:
            return 0.0
        return (self.completed_bytes / self.total_bytes) * 100

    @property
    def elapsed_time(self) -> float:
        """Get elapsed time in seconds."""
        return time.time() - self.start_time

    @property
    def speed_mbps(self) -> float:
        """Get current speed in MB/s."""
        elapsed = self.elapsed_time
        if elapsed == 0:
            return 0.0
        return (self.completed_bytes / (1024 * 1024)) / elapsed

    @property
    def eta_seconds(self) -> float:
        """Get estimated time remaining in seconds."""
        if self.completed_bytes == 0:
            return 0.0
        elapsed = self.elapsed_time
        rate = self.completed_bytes / elapsed
        remaining_bytes = self.total_bytes - self.completed_bytes
        return remaining_bytes / rate if rate > 0 else 0.0


class ProgressTracker:
    """Tracks and displays progress for operations."""

    def __init__(self, total_bytes: int, total_items: int, show_progress: bool = True):
        """
        Initialize progress tracker.

        Args:
            total_bytes: Total bytes to process
            total_items: Total items to process
            show_progress: Whether to display progress
        """
        self.info = ProgressInfo(
            total_bytes=total_bytes,
            completed_bytes=0,
            total_items=total_items,
            completed_items=0,
            start_time=time.time(),
        )
        self.show_progress = show_progress
        self._lock = threading.Lock()
        self._last_update = 0

    def update(
        self, bytes_delta: int = 0, items_delta: int = 0, current_item: str = ""
    ):
        """
        Update progress.

        Args:
            bytes_delta: Bytes completed since last update
            items_delta: Items completed since last update
            current_item: Name of current item being processed
        """
        with self._lock:
            self.info.completed_bytes += bytes_delta
            self.info.completed_items += items_delta
            if current_item:
                self.info.current_item = current_item

            # Throttle display updates to once per second
            now = time.time()
            if self.show_progress and (now - self._last_update) >= 1.0:
                self._display()
                self._last_update = now

    def finish(self):
        """Mark operation as complete and display final stats."""
        with self._lock:
            self.info.completed_bytes = self.info.total_bytes
            self.info.completed_items = self.info.total_items
            if self.show_progress:
                self._display()
                print()  # New line after progress

    def _display(self):
        """Display progress bar."""
        percent = self.info.percent
        speed = self.info.speed_mbps
        eta = self.info.eta_seconds

        # Create progress bar
        bar_width = 40
        filled = int(bar_width * percent / 100)
        bar = "█" * filled + "░" * (bar_width - filled)

        # Format output
        mb_completed = self.info.completed_bytes / (1024 * 1024)
        mb_total = self.info.total_bytes / (1024 * 1024)

        eta_str = self._format_time(eta)
        elapsed_str = self._format_time(self.info.elapsed_time)

        output = (
            f"\r{bar} {percent:5.1f}% | "
            f"{mb_completed:7.1f}/{mb_total:7.1f} MB | "
            f"{speed:6.2f} MB/s | "
            f"ETA: {eta_str} | "
            f"Elapsed: {elapsed_str} | "
            f"{self.info.completed_items}/{self.info.total_items} items"
        )

        print(output, end="", flush=True)

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Format seconds as HH:MM:SS."""
        if seconds < 0:
            return "??:??:??"
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"


class ParallelUploader:
    """Handles parallel chunk uploads."""

    def __init__(self, backend, max_workers: int = 4):
        """
        Initialize parallel uploader.

        Args:
            backend: RcloneBackend instance
            max_workers: Maximum number of parallel uploads
        """
        self.backend = backend
        self.max_workers = max_workers

    def upload_chunks(
        self,
        chunks: List[Tuple[int, bytes, str, str]],
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> List[Tuple[int, bool, Optional[str]]]:
        """
        Upload multiple chunks in parallel.

        Args:
            chunks: List of (index, data, remote, path) tuples
            progress_callback: Optional callback(chunk_index, bytes_uploaded)

        Returns:
            List of (index, success, error_message) tuples
        """
        results = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all upload tasks
            future_to_chunk = {}
            for chunk_index, data, remote, path in chunks:
                future = executor.submit(
                    self._upload_chunk, chunk_index, data, remote, path
                )
                future_to_chunk[future] = (chunk_index, len(data))

            # Collect results as they complete
            for future in as_completed(future_to_chunk):
                chunk_index, chunk_size = future_to_chunk[future]
                try:
                    success, error = future.result()
                    results.append((chunk_index, success, error))

                    if progress_callback and success:
                        progress_callback(chunk_index, chunk_size)

                except Exception as e:
                    log.error(f"Exception uploading chunk {chunk_index}: {e}")
                    results.append((chunk_index, False, str(e)))

        return results

    def _upload_chunk(
        self, chunk_index: int, data: bytes, remote: str, path: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Upload a single chunk.

        Args:
            chunk_index: Chunk index
            data: Chunk data
            remote: Target remote
            path: Remote path

        Returns:
            (success, error_message)
        """
        try:
            success = self.backend.upload_bytes(data, remote, path)
            if success:
                log.debug(f"Chunk {chunk_index} uploaded successfully")
                return (True, None)
            else:
                return (False, "Upload failed")
        except Exception as e:
            log.error(f"Error uploading chunk {chunk_index}: {e}")
            return (False, str(e))


class ParallelDownloader:
    """Handles parallel chunk downloads."""

    def __init__(self, backend, max_workers: int = 4):
        """
        Initialize parallel downloader.

        Args:
            backend: RcloneBackend instance
            max_workers: Maximum number of parallel downloads
        """
        self.backend = backend
        self.max_workers = max_workers

    def download_chunks(
        self,
        chunks: List[Tuple[int, str, str]],
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> List[Tuple[int, Optional[bytes], Optional[str]]]:
        """
        Download multiple chunks in parallel.

        Args:
            chunks: List of (index, remote, path) tuples
            progress_callback: Optional callback(chunk_index, bytes_downloaded)

        Returns:
            List of (index, data, error_message) tuples
        """
        results = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all download tasks
            future_to_chunk = {}
            for chunk_index, remote, path in chunks:
                future = executor.submit(
                    self._download_chunk, chunk_index, remote, path
                )
                future_to_chunk[future] = chunk_index

            # Collect results as they complete
            for future in as_completed(future_to_chunk):
                chunk_index = future_to_chunk[future]
                try:
                    data, error = future.result()
                    results.append((chunk_index, data, error))

                    if progress_callback and data:
                        progress_callback(chunk_index, len(data))

                except Exception as e:
                    log.error(f"Exception downloading chunk {chunk_index}: {e}")
                    results.append((chunk_index, None, str(e)))

        return results

    def _download_chunk(
        self, chunk_index: int, remote: str, path: str
    ) -> Tuple[Optional[bytes], Optional[str]]:
        """
        Download a single chunk.

        Args:
            chunk_index: Chunk index
            remote: Source remote
            path: Remote path

        Returns:
            (data, error_message)
        """
        try:
            data = self.backend.download_bytes(remote, path, suppress_errors=True)
            if data:
                log.debug(f"Chunk {chunk_index} downloaded successfully")
                return (data, None)
            else:
                return (None, "Download failed")
        except Exception as e:
            log.error(f"Error downloading chunk {chunk_index}: {e}")
            return (None, str(e))


class ChunkPrefetcher:
    """Prefetches chunks for sequential streaming (v0.3)."""

    def __init__(self, backend, cache, prefetch_count: int = 2):
        """
        Initialize chunk prefetcher.

        Args:
            backend: RcloneBackend instance
            cache: ChunkCache instance
            prefetch_count: Number of chunks to prefetch ahead
        """
        self.backend = backend
        self.cache = cache
        self.prefetch_count = prefetch_count
        self._prefetch_queue = queue.Queue()
        self._stop_event = threading.Event()
        self._worker_thread = None

    def start(self):
        """Start prefetch worker thread."""
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._stop_event.clear()
            self._worker_thread = threading.Thread(
                target=self._prefetch_worker, daemon=True
            )
            self._worker_thread.start()
            log.debug("Prefetch worker started")

    def stop(self):
        """Stop prefetch worker thread."""
        self._stop_event.set()
        if self._worker_thread:
            self._worker_thread.join(timeout=5.0)
            log.debug("Prefetch worker stopped")

    def request_prefetch(self, chunks: List[Tuple[str, str, str]]):
        """
        Request prefetch of chunks.

        Args:
            chunks: List of (cache_key, remote, path) tuples
        """
        for chunk_info in chunks:
            try:
                self._prefetch_queue.put_nowait(chunk_info)
            except queue.Full:
                log.debug("Prefetch queue full, skipping")
                break

    def _prefetch_worker(self):
        """Worker thread that prefetches chunks."""
        while not self._stop_event.is_set():
            try:
                # Get next chunk to prefetch (with timeout to check stop event)
                cache_key, remote, path = self._prefetch_queue.get(timeout=1.0)

                # Check if already cached
                if self.cache.get(cache_key) is not None:
                    log.debug(f"Chunk {cache_key} already cached, skipping prefetch")
                    continue

                # Download and cache
                log.debug(f"Prefetching chunk {cache_key}")
                data = self.backend.download_bytes(remote, path, suppress_errors=True)
                if data:
                    self.cache.put(cache_key, data)
                    log.debug(f"Prefetched and cached chunk {cache_key}")

            except queue.Empty:
                continue
            except Exception as e:
                log.warning(f"Error in prefetch worker: {e}")


class RcloneDaemon:
    """Manages rclone rcd (daemon mode) for connection pooling (v0.3)."""

    def __init__(self, config, port: int = 5572):
        """
        Initialize rclone daemon manager.

        Args:
            config: RclonePool configuration
            port: Port for rclone rcd
        """
        self.config = config
        self.port = port
        self._process = None
        self._base_url = f"http://localhost:{port}"

    def start(self):
        """Start rclone daemon."""
        import subprocess

        if self._process is not None:
            log.warning("Rclone daemon already running")
            return

        cmd = [
            self.config.rclone_binary,
            "rcd",
            "--rc-addr",
            f"localhost:{self.port}",
            "--rc-no-auth",
        ]

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            # Give it time to start
            time.sleep(2)
            log.info(f"Rclone daemon started on port {self.port}")
        except Exception as e:
            log.error(f"Failed to start rclone daemon: {e}")
            self._process = None

    def stop(self):
        """Stop rclone daemon."""
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None
            log.info("Rclone daemon stopped")

    def is_running(self) -> bool:
        """Check if daemon is running."""
        if self._process is None:
            return False
        return self._process.poll() is None

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
        return False
