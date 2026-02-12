"""
Manifest management — tracks which chunks belong to which files and where they live.
Manifests are stored on ALL remotes for redundancy.
"""

# rclonepool/manifest.py

import json
import hashlib
import time
import os
import logging
from typing import Optional, List

log = logging.getLogger('rclonepool')


class ManifestManager:
    def __init__(self, config, backend):
        self.config = config
        self.backend = backend
        self._manifest_cache = {}

    def create_manifest(self, file_name: str, remote_dir: str, file_size: int,
                        chunk_size: int, chunks: list) -> dict:
        """Create a manifest dict for a file."""
        manifest = {
            'version': 1,
            'file_name': file_name,
            'remote_dir': remote_dir.rstrip('/') or '/',
            'file_path': f"{remote_dir.rstrip('/')}/{file_name}",
            'file_size': file_size,
            'chunk_size': chunk_size,
            'chunk_count': len(chunks),
            'chunks': chunks,
            'created_at': time.time(),
            'checksum': hashlib.sha256(
                f"{file_name}:{file_size}:{len(chunks)}".encode()
            ).hexdigest()[:16]
        }
        return manifest

    def _manifest_remote_path(self, file_path: str) -> str:
        """Get the remote path for storing a manifest."""
        safe_name = file_path.replace('/', '_').strip('_')
        if not safe_name:
            safe_name = 'root'
        return f"{self.config.manifest_prefix}/{safe_name}.manifest.json"

    def save_manifest(self, manifest: dict):
        """Save manifest to ALL remotes for redundancy."""
        file_path = manifest['file_path']
        manifest_remote_path = self._manifest_remote_path(file_path)
        manifest_json = json.dumps(manifest, indent=2)

        log.info(f"  Saving manifest to all remotes...")
        for remote in self.config.remotes:
            success = self.backend.upload_bytes(
                manifest_json.encode('utf-8'),
                remote,
                manifest_remote_path
            )
            if not success:
                log.warning(f"  Failed to save manifest to {remote}")
            else:
                log.debug(f"  Manifest saved to {remote}")

        # Also cache it locally
        self._manifest_cache[file_path] = manifest

    def load_manifest_for_file(self, file_path: str) -> Optional[dict]:
        """Load manifest for a file. Tries cache first, then remotes."""
        # Normalize path
        file_path = file_path.strip('/')
        if not file_path.startswith('/'):
            file_path = '/' + file_path

        # Check cache
        if file_path in self._manifest_cache:
            return self._manifest_cache[file_path]

        manifest_remote_path = self._manifest_remote_path(file_path)

        # Try each remote until we find it
        for remote in self.config.remotes:
            try:
                data = self.backend.download_bytes(remote, manifest_remote_path, suppress_errors=True)
                if data:
                    manifest = json.loads(data.decode('utf-8'))
                    self._manifest_cache[file_path] = manifest
                    log.debug(f"  Loaded manifest from {remote}")
                    return manifest
            except Exception as e:
                log.debug(f"  Could not load manifest from {remote}: {e}")
                continue

        log.warning(f"  No manifest found for {file_path}")
        return None

    def list_manifests(self, remote_dir: str = '/', recursive: bool = False) -> List[dict]:
        """List all manifests, optionally filtered by directory.
        
        Args:
            remote_dir: Directory to filter by
            recursive: If True, include files in subdirectories as well
        """
        remote_dir = remote_dir.rstrip('/') or '/'
        manifests = []
        seen_files = set()

        for remote in self.config.remotes:
            try:
                files = self.backend.list_files(remote, self.config.manifest_prefix)

                # Handle None (error) or empty list (no manifests yet)
                if not files:
                    continue

                for f in files:
                    if not f.endswith('.manifest.json'):
                        continue
                    if f in seen_files:
                        continue
                    seen_files.add(f)

                    manifest_path = f"{self.config.manifest_prefix}/{f}"
                    data = self.backend.download_bytes(remote, manifest_path, suppress_errors=True)
                    if data:
                        try:
                            manifest = json.loads(data.decode('utf-8'))
                            manifest_dir = manifest.get('remote_dir', '/')
                            
                            # Filter logic
                            if remote_dir == '/':
                                # At root, include if exact match or if recursive
                                if manifest_dir == '/' or recursive:
                                    manifests.append(manifest)
                                    self._manifest_cache[manifest['file_path']] = manifest
                            else:
                                # In a subdirectory
                                if recursive:
                                    # Include if in this dir or any subdirectory
                                    if manifest_dir == remote_dir or manifest_dir.startswith(remote_dir.rstrip('/') + '/'):
                                        manifests.append(manifest)
                                        self._manifest_cache[manifest['file_path']] = manifest
                                else:
                                    # Include only if exact match
                                    if manifest_dir == remote_dir:
                                        manifests.append(manifest)
                                        self._manifest_cache[manifest['file_path']] = manifest
                        except json.JSONDecodeError:
                            log.warning(f"  Corrupt manifest: {manifest_path} on {remote}")
                            continue

                if manifests:
                    break
            except Exception as e:
                log.debug(f"  Could not list manifests from {remote}: {e}")
                continue

        return manifests

    def delete_manifest(self, file_path: str):
        """Delete manifest from all remotes."""
        file_path = file_path.strip('/')
        if not file_path.startswith('/'):
            file_path = '/' + file_path

        manifest_remote_path = self._manifest_remote_path(file_path)

        for remote in self.config.remotes:
            try:
                self.backend.delete_file(remote, manifest_remote_path)
                log.debug(f"  Manifest deleted from {remote}")
            except Exception as e:
                log.debug(f"  Could not delete manifest from {remote}: {e}")

        # Remove from cache
        self._manifest_cache.pop(file_path, None)

    def rebuild_cache(self):
        """Rebuild local manifest cache from remotes."""
        log.info("Rebuilding manifest cache from remotes...")
        self._manifest_cache.clear()
        manifests = self.list_manifests('/')
        log.info(f"  Found {len(manifests)} manifests")
        return manifests