"""
Rclone backend — wraps rclone CLI calls for upload, download, list, delete.
Handles temp file management using RAM (tmpfs).
"""

# rclonepool/rclone_backend.py

import subprocess
import os
import tempfile
import shutil
import logging
from typing import Optional, Tuple, List

log = logging.getLogger('rclonepool')


class RcloneBackend:
    def __init__(self, config):
        self.config = config
        self.rclone = config.rclone_binary
        self.flags = config.rclone_flags
        self._ensure_temp_dir()

    def _ensure_temp_dir(self):
        """Ensure temp directory exists."""
        os.makedirs(self.config.temp_dir, exist_ok=True)

    def _run(self, args: list, capture_output=True, input_data=None) -> subprocess.CompletedProcess:
        """Run an rclone command."""
        cmd = [self.rclone] + args
        log.debug(f"  Running: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=capture_output,
                input=input_data,
                timeout=600  # 10 minute timeout
            )
            if result.returncode != 0:
                stderr = result.stderr.decode('utf-8', errors='replace') if result.stderr else ''
                log.error(f"  rclone error (code {result.returncode}): {stderr[:500]}")
            return result
        except subprocess.TimeoutExpired:
            log.error(f"  rclone command timed out: {' '.join(cmd[:5])}...")
            raise
        except FileNotFoundError:
            log.error(f"  rclone binary not found: {self.rclone}")
            log.error(f"  Install rclone: https://rclone.org/install/")
            raise

    def upload_file(self, local_path: str, remote: str, remote_path: str) -> bool:
        """Upload a local file to a remote."""
        # rclone copyto localfile remote:path
        dest = f"{remote}{remote_path}"
        result = self._run(['copyto', local_path, dest] + self.flags)
        return result.returncode == 0

    def upload_bytes(self, data: bytes, remote: str, remote_path: str) -> bool:
        """Upload bytes to a remote. Uses temp file in RAM (tmpfs)."""
        # Write to tmpfs to avoid SSD writes
        temp_path = os.path.join(self.config.temp_dir, f"chunk_{os.getpid()}_{id(data)}.tmp")
        try:
            with open(temp_path, 'wb') as f:
                f.write(data)

            success = self.upload_file(temp_path, remote, remote_path)
            return success
        finally:
            # Clean up temp file
            try:
                os.remove(temp_path)
            except OSError:
                pass

    def download_bytes(self, remote: str, remote_path: str) -> Optional[bytes]:
        """Download a file from remote and return as bytes."""
        temp_path = os.path.join(self.config.temp_dir, f"dl_{os.getpid()}_{hash(remote_path) & 0xFFFFFFFF}.tmp")
        try:
            src = f"{remote}{remote_path}"
            result = self._run(['copyto', src, temp_path] + self.flags)

            if result.returncode != 0:
                return None

            if not os.path.exists(temp_path):
                return None

            with open(temp_path, 'rb') as f:
                return f.read()
        finally:
            try:
                os.remove(temp_path)
            except OSError:
                pass

    def download_byte_range(self, remote: str, remote_path: str,
                            offset: int, length: int) -> Optional[bytes]:
        """
        Download a byte range from a remote file.
        
        rclone doesn't natively support byte ranges in copyto,
        so we download the full chunk and slice. For better performance,
        we cache chunks.
        
        TODO: For truly large chunks, consider using rclone cat with --offset and --count.
        """
        # Use rclone cat which supports --offset and --count
        src = f"{remote}{remote_path}"
        result = self._run([
            'cat', src,
            '--offset', str(offset),
            '--count', str(length)
        ])

        if result.returncode != 0:
            return None

        return result.stdout

    def download_file(self, remote: str, remote_path: str, local_path: str) -> bool:
        """Download a file from remote to a local path."""
        src = f"{remote}{remote_path}"
        result = self._run(['copyto', src, local_path] + self.flags)
        return result.returncode == 0

    def delete_file(self, remote: str, remote_path: str) -> bool:
        """Delete a file from remote."""
        target = f"{remote}{remote_path}"
        result = self._run(['deletefile', target])
        return result.returncode == 0

    def list_files(self, remote: str, path: str) -> Optional[List[str]]:
        """List files in a remote path. Returns list of filenames."""
        target = f"{remote}{path}"
        result = self._run(['lsf', target, '--files-only'])

        if result.returncode != 0:
            return None

        stdout = result.stdout.decode('utf-8', errors='replace')
        files = [line.strip() for line in stdout.strip().split('\n') if line.strip()]
        return files

    def list_dirs(self, remote: str, path: str) -> Optional[List[str]]:
        """List directories in a remote path."""
        target = f"{remote}{path}"
        result = self._run(['lsf', target, '--dirs-only'])

        if result.returncode != 0:
            return None

        stdout = result.stdout.decode('utf-8', errors='replace')
        dirs = [line.strip().rstrip('/') for line in stdout.strip().split('\n') if line.strip()]
        return dirs

    def get_space(self, remote: str) -> Tuple[int, int, int]:
        """
        Get space usage for a remote. Returns (used, free, total) in bytes.
        Falls back to rclone about if available.
        """
        result = self._run(['about', remote, '--json'])

        if result.returncode != 0:
            log.warning(f"  Could not get space info for {remote}")
            return (0, 0, 0)

        try:
            import json
            info = json.loads(result.stdout.decode('utf-8'))
            used = info.get('used', 0) or 0
            free = info.get('free', 0) or 0
            total = info.get('total', 0) or 0

            # Some remotes don't report total but report used and free
            if total == 0 and (used > 0 or free > 0):
                total = used + free

            return (used, free, total)
        except (json.JSONDecodeError, KeyError) as e:
            log.warning(f"  Could not parse space info for {remote}: {e}")
            return (0, 0, 0)

    def check_remote_exists(self, remote: str) -> bool:
        """Check if a remote is configured and accessible."""
        result = self._run(['lsd', remote], capture_output=True)
        return result.returncode == 0