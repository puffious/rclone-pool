"""
Balancer — decides which remote gets the next chunk.
Uses least-used-first strategy.
"""

# rclonepool/balancer.py

import logging
from typing import Dict

log = logging.getLogger('rclonepool')


class Balancer:
    def __init__(self, config, backend):
        self.config = config
        self.backend = backend
        self._usage_cache: Dict[str, int] = {}
        self._initialized = False

    def _init_usage(self):
        """Fetch current usage from all remotes."""
        if self._initialized:
            return

        for remote in self.config.remotes:
            used, free, total = self.backend.get_space(remote)
            self._usage_cache[remote] = used
            log.info(f"  {remote}: {used:,} bytes used, {free:,} bytes free")

        self._initialized = True

    def get_least_used_remote(self) -> str:
        """Return the remote with the least used space."""
        self._init_usage()

        if not self._usage_cache:
            # Fallback: round-robin if we can't get usage
            return self.config.remotes[0]

        least_used = min(self._usage_cache, key=self._usage_cache.get)
        log.debug(f"  Least used remote: {least_used} ({self._usage_cache[least_used]:,} bytes)")
        return least_used

    def record_usage(self, remote: str, bytes_added: int):
        """Update our cached usage after uploading a chunk."""
        if remote in self._usage_cache:
            self._usage_cache[remote] += bytes_added

    def get_usage_report(self) -> Dict[str, dict]:
        """Get a report of all remote usage."""
        self._init_usage()
        report = {}
        for remote in self.config.remotes:
            used, free, total = self.backend.get_space(remote)
            report[remote] = {
                'used': used,
                'free': free,
                'total': total,
                'percent': (used / total * 100) if total > 0 else 0
            }
        return report