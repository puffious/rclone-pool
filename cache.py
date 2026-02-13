"""
Persistent manifest cache for rclonepool.
Part of v0.2 Robustness features.

Provides disk-based caching of manifests to speed up operations
and reduce remote API calls.
"""

import json
import os
import time
import logging
from typing import Optional, Dict, List
from pathlib import Path

log = logging.getLogger("rclonepool")


class ManifestCache:
    """Persistent cache for file manifests."""

    def __init__(self, cache_dir: str = None):
        """
        Initialize manifest cache.

        Args:
            cache_dir: Directory to store cache files. Defaults to ~/.cache/rclonepool
        """
        if cache_dir is None:
            cache_dir = os.path.expanduser("~/.cache/rclonepool")

        self.cache_dir = cache_dir
        self.cache_file = os.path.join(cache_dir, "manifest_cache.json")
        self._cache: Dict[str, dict] = {}
        self._dirty = False
        self._load()

    def _load(self):
        """Load cache from disk."""
        if not os.path.exists(self.cache_file):
            log.debug("No cache file found, starting with empty cache")
            return

        try:
            with open(self.cache_file, "r") as f:
                data = json.load(f)
                self._cache = data.get("manifests", {})
                cache_time = data.get("updated_at", 0)
                log.info(
                    f"Loaded {len(self._cache)} manifests from cache (updated: {time.ctime(cache_time)})"
                )
        except (json.JSONDecodeError, IOError) as e:
            log.warning(f"Failed to load cache: {e}, starting fresh")
            self._cache = {}

    def save(self, force: bool = False):
        """
        Save cache to disk.

        Args:
            force: Save even if cache hasn't been modified
        """
        if not self._dirty and not force:
            return

        try:
            os.makedirs(self.cache_dir, exist_ok=True)

            data = {"version": 1, "updated_at": time.time(), "manifests": self._cache}

            # Write to temp file first, then rename (atomic operation)
            temp_file = self.cache_file + ".tmp"
            with open(temp_file, "w") as f:
                json.dump(data, f, indent=2)

            os.replace(temp_file, self.cache_file)
            self._dirty = False
            log.debug(f"Saved {len(self._cache)} manifests to cache")
        except IOError as e:
            log.warning(f"Failed to save cache: {e}")

    def get(self, file_path: str) -> Optional[dict]:
        """
        Get a manifest from cache.

        Args:
            file_path: Remote file path

        Returns:
            Manifest dict or None if not in cache
        """
        normalized_path = self._normalize_path(file_path)
        return self._cache.get(normalized_path)

    def put(self, file_path: str, manifest: dict):
        """
        Add or update a manifest in cache.

        Args:
            file_path: Remote file path
            manifest: Manifest dict
        """
        normalized_path = self._normalize_path(file_path)
        self._cache[normalized_path] = manifest
        self._dirty = True

    def delete(self, file_path: str):
        """
        Remove a manifest from cache.

        Args:
            file_path: Remote file path
        """
        normalized_path = self._normalize_path(file_path)
        if normalized_path in self._cache:
            del self._cache[normalized_path]
            self._dirty = True

    def list_all(self) -> List[dict]:
        """
        Get all manifests from cache.

        Returns:
            List of all cached manifests
        """
        return list(self._cache.values())

    def list_by_directory(self, remote_dir: str, recursive: bool = False) -> List[dict]:
        """
        List manifests in a specific directory.

        Args:
            remote_dir: Directory path
            recursive: Include subdirectories

        Returns:
            List of manifests in the directory
        """
        remote_dir = self._normalize_path(remote_dir)
        if not remote_dir.endswith("/"):
            remote_dir += "/"

        results = []
        for manifest in self._cache.values():
            manifest_dir = manifest.get("remote_dir", "/")
            if not manifest_dir.endswith("/"):
                manifest_dir += "/"

            if recursive:
                if manifest_dir.startswith(remote_dir) or remote_dir == "/":
                    results.append(manifest)
            else:
                if manifest_dir == remote_dir:
                    results.append(manifest)

        return results

    def clear(self):
        """Clear all cached manifests."""
        self._cache.clear()
        self._dirty = True
        log.info("Cache cleared")

    def invalidate(self, file_path: str):
        """
        Invalidate (remove) a specific manifest from cache.
        Alias for delete() for semantic clarity.

        Args:
            file_path: Remote file path
        """
        self.delete(file_path)

    def get_stats(self) -> dict:
        """
        Get cache statistics.

        Returns:
            Dict with cache stats
        """
        total_size = 0
        total_chunks = 0
        remotes_used = set()

        for manifest in self._cache.values():
            total_size += manifest.get("file_size", 0)
            total_chunks += manifest.get("chunk_count", 0)
            for chunk in manifest.get("chunks", []):
                remotes_used.add(chunk.get("remote", ""))

        return {
            "manifest_count": len(self._cache),
            "total_file_size": total_size,
            "total_chunks": total_chunks,
            "remotes_used": len(remotes_used),
            "cache_file": self.cache_file,
            "cache_exists": os.path.exists(self.cache_file),
        }

    def _normalize_path(self, path: str) -> str:
        """
        Normalize a file path for consistent cache keys.

        Args:
            path: File path

        Returns:
            Normalized path
        """
        path = path.strip()
        if not path.startswith("/"):
            path = "/" + path
        return path

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - auto-save on exit."""
        self.save()
        return False


class ChunkCache:
    """LRU cache for chunk data in memory/tmpfs (v0.3 Performance)."""

    def __init__(
        self, max_size_mb: int = 500, cache_dir: str = "/dev/shm/rclonepool_cache"
    ):
        """
        Initialize chunk cache.

        Args:
            max_size_mb: Maximum cache size in MB
            cache_dir: Directory for cached chunks (should be tmpfs)
        """
        self.max_size = max_size_mb * 1024 * 1024
        self.cache_dir = cache_dir
        self.current_size = 0
        self._cache: Dict[str, dict] = {}  # key -> {path, size, last_access}

        os.makedirs(cache_dir, exist_ok=True)
        log.info(f"Chunk cache initialized: {max_size_mb}MB max, dir={cache_dir}")

    def get(self, cache_key: str) -> Optional[bytes]:
        """
        Get chunk data from cache.

        Args:
            cache_key: Unique key for the chunk

        Returns:
            Chunk data or None if not cached
        """
        if cache_key not in self._cache:
            return None

        entry = self._cache[cache_key]
        cache_path = entry["path"]

        if not os.path.exists(cache_path):
            # Cache file was deleted externally
            del self._cache[cache_key]
            return None

        try:
            with open(cache_path, "rb") as f:
                data = f.read()

            # Update access time
            entry["last_access"] = time.time()
            log.debug(f"Cache hit: {cache_key}")
            return data
        except IOError as e:
            log.warning(f"Failed to read cached chunk {cache_key}: {e}")
            self._remove_entry(cache_key)
            return None

    def put(self, cache_key: str, data: bytes):
        """
        Add chunk data to cache.

        Args:
            cache_key: Unique key for the chunk
            data: Chunk data
        """
        data_size = len(data)

        # Evict if necessary
        while self.current_size + data_size > self.max_size and self._cache:
            self._evict_lru()

        # Don't cache if single chunk is larger than max size
        if data_size > self.max_size:
            log.debug(f"Chunk {cache_key} too large to cache ({data_size} bytes)")
            return

        cache_path = os.path.join(self.cache_dir, f"{cache_key}.chunk")

        try:
            with open(cache_path, "wb") as f:
                f.write(data)

            self._cache[cache_key] = {
                "path": cache_path,
                "size": data_size,
                "last_access": time.time(),
            }
            self.current_size += data_size
            log.debug(f"Cached chunk {cache_key} ({data_size} bytes)")
        except IOError as e:
            log.warning(f"Failed to cache chunk {cache_key}: {e}")

    def _evict_lru(self):
        """Evict least recently used chunk."""
        if not self._cache:
            return

        # Find LRU entry
        lru_key = min(self._cache.keys(), key=lambda k: self._cache[k]["last_access"])
        self._remove_entry(lru_key)
        log.debug(f"Evicted LRU chunk: {lru_key}")

    def _remove_entry(self, cache_key: str):
        """Remove a cache entry."""
        if cache_key not in self._cache:
            return

        entry = self._cache[cache_key]
        cache_path = entry["path"]

        try:
            if os.path.exists(cache_path):
                os.remove(cache_path)
        except OSError as e:
            log.warning(f"Failed to remove cached chunk file {cache_path}: {e}")

        self.current_size -= entry["size"]
        del self._cache[cache_key]

    def clear(self):
        """Clear all cached chunks."""
        for cache_key in list(self._cache.keys()):
            self._remove_entry(cache_key)
        log.info("Chunk cache cleared")

    def get_stats(self) -> dict:
        """Get cache statistics."""
        return {
            "cached_chunks": len(self._cache),
            "current_size_mb": self.current_size / (1024 * 1024),
            "max_size_mb": self.max_size / (1024 * 1024),
            "utilization_percent": (self.current_size / self.max_size * 100)
            if self.max_size > 0
            else 0,
        }

    def __del__(self):
        """Cleanup on deletion."""
        self.clear()
