"""
Redundancy features for rclonepool.
Part of v0.5 Redundancy features.

Provides:
- Reed-Solomon parity chunks
- Chunk replication (store each chunk on N remotes)
- Rebuild functionality to reconstruct lost chunks
- Health monitoring
"""

import os
import logging
import hashlib
from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass
from enum import Enum

log = logging.getLogger("rclonepool")


class RedundancyMode(Enum):
    """Redundancy mode."""

    NONE = "none"
    REPLICATION = "replication"
    PARITY = "parity"
    HYBRID = "hybrid"  # Both replication and parity


@dataclass
class ParityConfig:
    """Configuration for Reed-Solomon parity."""

    data_shards: int = 3
    parity_shards: int = 1

    @property
    def total_shards(self) -> int:
        """Get total number of shards."""
        return self.data_shards + self.parity_shards

    @property
    def tolerance(self) -> int:
        """Get number of shards that can be lost."""
        return self.parity_shards


@dataclass
class HealthStatus:
    """Health status for a file."""

    file_path: str
    total_chunks: int
    healthy_chunks: int
    degraded_chunks: int
    missing_chunks: int
    parity_chunks: int
    parity_healthy: int
    is_recoverable: bool
    warnings: List[str]


class ReedSolomonEncoder:
    """Reed-Solomon encoder/decoder for parity chunks."""

    def __init__(self, data_shards: int, parity_shards: int):
        """
        Initialize Reed-Solomon encoder.

        Args:
            data_shards: Number of data shards
            parity_shards: Number of parity shards
        """
        self.data_shards = data_shards
        self.parity_shards = parity_shards
        self.total_shards = data_shards + parity_shards

        # Note: This is a simplified implementation
        # For production, use a library like pyeclib or zfec
        log.warning(
            "Using simplified parity implementation. "
            "For production, integrate pyeclib or zfec library."
        )

    def encode(self, data_chunks: List[bytes]) -> List[bytes]:
        """
        Encode data chunks to create parity chunks.

        Args:
            data_chunks: List of data chunks

        Returns:
            List of parity chunks
        """
        if len(data_chunks) != self.data_shards:
            raise ValueError(
                f"Expected {self.data_shards} data chunks, got {len(data_chunks)}"
            )

        # Simplified XOR-based parity (for demo purposes)
        # In production, use proper Reed-Solomon codes
        parity_chunks = []

        for parity_idx in range(self.parity_shards):
            # XOR all data chunks together
            max_len = max(len(chunk) for chunk in data_chunks)
            parity = bytearray(max_len)

            for chunk in data_chunks:
                for i, byte in enumerate(chunk):
                    parity[i] ^= byte

            parity_chunks.append(bytes(parity))

        return parity_chunks

    def decode(
        self, available_chunks: List[Optional[bytes]], chunk_indices: List[int]
    ) -> List[bytes]:
        """
        Decode/reconstruct missing chunks from available chunks.

        Args:
            available_chunks: List of available chunks (None for missing)
            chunk_indices: Indices of chunks (0-based, data chunks first)

        Returns:
            List of reconstructed chunks
        """
        # Simplified reconstruction (XOR-based)
        # In production, use proper Reed-Solomon decoding

        missing_count = sum(1 for c in available_chunks if c is None)

        if missing_count > self.parity_shards:
            raise ValueError(
                f"Cannot recover: {missing_count} chunks missing, "
                f"but only {self.parity_shards} parity chunks available"
            )

        reconstructed = list(available_chunks)

        # Find the missing chunk index
        for i, chunk in enumerate(available_chunks):
            if chunk is None:
                # XOR all other chunks to reconstruct
                max_len = max(len(c) for c in available_chunks if c is not None)
                result = bytearray(max_len)

                for j, other_chunk in enumerate(available_chunks):
                    if i != j and other_chunk is not None:
                        for k, byte in enumerate(other_chunk):
                            result[k] ^= byte

                reconstructed[i] = bytes(result)

        return reconstructed


class RedundancyManager:
    """Manages redundancy for files."""

    def __init__(self, config, backend, manifest_mgr):
        """
        Initialize redundancy manager.

        Args:
            config: RclonePool configuration
            backend: RcloneBackend instance
            manifest_mgr: ManifestManager instance
        """
        self.config = config
        self.backend = backend
        self.manifest_mgr = manifest_mgr
        self.mode = RedundancyMode.NONE
        self.replication_factor = 1
        self.parity_config = ParityConfig()
        self.encoder = None

    def set_mode(self, mode: RedundancyMode):
        """
        Set redundancy mode.

        Args:
            mode: Redundancy mode to use
        """
        self.mode = mode
        log.info(f"Redundancy mode set to: {mode.value}")

        if mode in (RedundancyMode.PARITY, RedundancyMode.HYBRID):
            self.encoder = ReedSolomonEncoder(
                self.parity_config.data_shards, self.parity_config.parity_shards
            )

    def set_replication_factor(self, factor: int):
        """
        Set replication factor.

        Args:
            factor: Number of copies to maintain
        """
        if factor < 1:
            raise ValueError("Replication factor must be >= 1")

        if factor > len(self.config.remotes):
            log.warning(
                f"Replication factor {factor} exceeds number of remotes "
                f"{len(self.config.remotes)}"
            )

        self.replication_factor = factor
        log.info(f"Replication factor set to: {factor}")

    def set_parity_config(self, data_shards: int, parity_shards: int):
        """
        Set parity configuration.

        Args:
            data_shards: Number of data shards
            parity_shards: Number of parity shards
        """
        self.parity_config = ParityConfig(data_shards, parity_shards)

        if self.mode in (RedundancyMode.PARITY, RedundancyMode.HYBRID):
            self.encoder = ReedSolomonEncoder(data_shards, parity_shards)

        log.info(
            f"Parity config set to: {data_shards} data + {parity_shards} parity "
            f"(can lose {parity_shards} chunks)"
        )

    def create_parity_chunks(
        self, data_chunks: List[bytes], file_name: str
    ) -> List[dict]:
        """
        Create parity chunks for data chunks.

        Args:
            data_chunks: List of data chunk bytes
            file_name: Name of file

        Returns:
            List of parity chunk metadata
        """
        if not self.encoder:
            raise ValueError("Parity encoder not initialized")

        log.info(
            f"Creating {self.parity_config.parity_shards} parity chunks "
            f"for {len(data_chunks)} data chunks"
        )

        parity_chunks = self.encoder.encode(data_chunks)
        parity_metadata = []

        # Upload parity chunks
        for parity_idx, parity_data in enumerate(parity_chunks):
            # Select remote for parity chunk (different from data chunks if possible)
            target_remote = self._select_parity_remote()

            chunk_id = f"{file_name}.parity.{parity_idx:03d}"
            chunk_path = f"{self.config.data_prefix}/{chunk_id}"

            success = self.backend.upload_bytes(parity_data, target_remote, chunk_path)

            if success:
                parity_metadata.append(
                    {
                        "index": parity_idx,
                        "remote": target_remote,
                        "path": chunk_path,
                        "size": len(parity_data),
                        "type": "parity",
                    }
                )
                log.info(f"  Parity chunk {parity_idx} uploaded to {target_remote}")
            else:
                log.error(f"  Failed to upload parity chunk {parity_idx}")

        return parity_metadata

    def replicate_chunk(
        self, chunk_data: bytes, chunk_id: str, primary_remote: str
    ) -> List[dict]:
        """
        Replicate a chunk to additional remotes.

        Args:
            chunk_data: Chunk data
            chunk_id: Chunk identifier
            primary_remote: Primary remote (already uploaded)

        Returns:
            List of replica metadata
        """
        replicas = []
        chunk_path = f"{self.config.data_prefix}/{chunk_id}"

        # Select additional remotes for replicas
        available_remotes = [r for r in self.config.remotes if r != primary_remote]
        replica_count = min(self.replication_factor - 1, len(available_remotes))

        if replica_count <= 0:
            return replicas

        log.info(f"Creating {replica_count} replicas for chunk {chunk_id}")

        for i in range(replica_count):
            target_remote = available_remotes[i]

            success = self.backend.upload_bytes(chunk_data, target_remote, chunk_path)

            if success:
                replicas.append(
                    {"remote": target_remote, "path": chunk_path, "type": "replica"}
                )
                log.info(f"  Replica uploaded to {target_remote}")
            else:
                log.error(f"  Failed to upload replica to {target_remote}")

        return replicas

    def check_health(self, file_path: str) -> HealthStatus:
        """
        Check health status of a file.

        Args:
            file_path: Remote file path

        Returns:
            HealthStatus object
        """
        log.info(f"Checking health of {file_path}...")

        manifest = self.manifest_mgr.load_manifest_for_file(file_path)
        if not manifest:
            return HealthStatus(
                file_path=file_path,
                total_chunks=0,
                healthy_chunks=0,
                degraded_chunks=0,
                missing_chunks=0,
                parity_chunks=0,
                parity_healthy=0,
                is_recoverable=False,
                warnings=["Manifest not found"],
            )

        chunks = manifest.get("chunks", [])
        parity_chunks = manifest.get("parity_chunks", [])

        healthy_chunks = 0
        degraded_chunks = 0
        missing_chunks = 0
        parity_healthy = 0
        warnings = []

        # Check data chunks
        for chunk in chunks:
            remote = chunk.get("remote")
            path = chunk.get("path")

            # Check if chunk exists
            exists = self._check_chunk_exists(remote, path)

            if exists:
                # Check replicas if in replication mode
                replicas = chunk.get("replicas", [])
                healthy_replica_count = sum(
                    1
                    for r in replicas
                    if self._check_chunk_exists(r["remote"], r["path"])
                )

                if healthy_replica_count + 1 >= self.replication_factor:
                    healthy_chunks += 1
                elif healthy_replica_count > 0:
                    degraded_chunks += 1
                    warnings.append(
                        f"Chunk {chunk['index']} has degraded replication "
                        f"({healthy_replica_count + 1}/{self.replication_factor})"
                    )
                else:
                    healthy_chunks += 1
            else:
                # Primary copy missing
                replicas = chunk.get("replicas", [])
                healthy_replica_count = sum(
                    1
                    for r in replicas
                    if self._check_chunk_exists(r["remote"], r["path"])
                )

                if healthy_replica_count > 0:
                    degraded_chunks += 1
                    warnings.append(
                        f"Chunk {chunk['index']} primary copy missing, "
                        f"but {healthy_replica_count} replica(s) available"
                    )
                else:
                    missing_chunks += 1
                    warnings.append(f"Chunk {chunk['index']} completely missing")

        # Check parity chunks
        for parity_chunk in parity_chunks:
            remote = parity_chunk.get("remote")
            path = parity_chunk.get("path")

            if self._check_chunk_exists(remote, path):
                parity_healthy += 1

        # Determine if recoverable
        is_recoverable = True
        if self.mode in (RedundancyMode.PARITY, RedundancyMode.HYBRID):
            # Can recover if missing chunks <= parity chunks
            is_recoverable = missing_chunks <= parity_healthy
        elif self.mode == RedundancyMode.REPLICATION:
            # Can recover if no chunks are completely missing
            is_recoverable = missing_chunks == 0
        else:
            # No redundancy
            is_recoverable = missing_chunks == 0

        status = HealthStatus(
            file_path=file_path,
            total_chunks=len(chunks),
            healthy_chunks=healthy_chunks,
            degraded_chunks=degraded_chunks,
            missing_chunks=missing_chunks,
            parity_chunks=len(parity_chunks),
            parity_healthy=parity_healthy,
            is_recoverable=is_recoverable,
            warnings=warnings,
        )

        log.info(
            f"  Health: {healthy_chunks}/{len(chunks)} healthy, "
            f"{degraded_chunks} degraded, {missing_chunks} missing"
        )
        log.info(f"  Recoverable: {is_recoverable}")

        return status

    def rebuild_file(self, file_path: str) -> bool:
        """
        Rebuild a file by reconstructing missing chunks.

        Args:
            file_path: Remote file path

        Returns:
            True if rebuild succeeded
        """
        log.info(f"Rebuilding {file_path}...")

        health = self.check_health(file_path)

        if not health.is_recoverable:
            log.error("File is not recoverable - too many chunks missing")
            return False

        if health.missing_chunks == 0 and health.degraded_chunks == 0:
            log.info("File is healthy, no rebuild needed")
            return True

        manifest = self.manifest_mgr.load_manifest_for_file(file_path)
        chunks = manifest.get("chunks", [])
        parity_chunks = manifest.get("parity_chunks", [])

        rebuilt_chunks = 0

        # Rebuild missing chunks from replicas or parity
        for chunk in chunks:
            remote = chunk.get("remote")
            path = chunk.get("path")

            if not self._check_chunk_exists(remote, path):
                log.info(f"  Rebuilding chunk {chunk['index']}...")

                # Try to restore from replica
                replicas = chunk.get("replicas", [])
                restored = False

                for replica in replicas:
                    if self._check_chunk_exists(replica["remote"], replica["path"]):
                        # Copy from replica to primary
                        data = self.backend.download_bytes(
                            replica["remote"], replica["path"], suppress_errors=True
                        )

                        if data:
                            success = self.backend.upload_bytes(data, remote, path)
                            if success:
                                log.info(
                                    f"    Restored from replica on {replica['remote']}"
                                )
                                rebuilt_chunks += 1
                                restored = True
                                break

                if not restored and self.mode in (
                    RedundancyMode.PARITY,
                    RedundancyMode.HYBRID,
                ):
                    # Try to reconstruct from parity
                    log.info("    Attempting parity reconstruction...")
                    # This would require implementing full Reed-Solomon reconstruction
                    # For now, log that it would be attempted
                    log.warning("    Parity reconstruction not yet implemented")

        log.info(f"Rebuild complete: {rebuilt_chunks} chunks restored")

        # Re-check health
        final_health = self.check_health(file_path)
        success = final_health.missing_chunks == 0

        if success:
            log.info("✓ File successfully rebuilt")
        else:
            log.error(f"✗ File still has {final_health.missing_chunks} missing chunks")

        return success

    def monitor_health_all(self) -> Dict[str, HealthStatus]:
        """
        Monitor health of all files in pool.

        Returns:
            Dict mapping file paths to health status
        """
        log.info("Monitoring health of all files...")

        manifests = self.manifest_mgr.list_manifests("/", recursive=True)
        health_report = {}

        total_files = len(manifests)
        healthy_files = 0
        degraded_files = 0
        unhealthy_files = 0

        for manifest in manifests:
            file_path = manifest.get("file_path")
            health = self.check_health(file_path)
            health_report[file_path] = health

            if health.missing_chunks == 0 and health.degraded_chunks == 0:
                healthy_files += 1
            elif health.is_recoverable:
                degraded_files += 1
            else:
                unhealthy_files += 1

        log.info(f"\nHealth Summary:")
        log.info(f"  Total files: {total_files}")
        log.info(f"  Healthy: {healthy_files}")
        log.info(f"  Degraded: {degraded_files}")
        log.info(f"  Unhealthy: {unhealthy_files}")

        if unhealthy_files > 0:
            log.warning(f"\nUnhealthy files (not recoverable):")
            for path, health in health_report.items():
                if not health.is_recoverable:
                    log.warning(f"  {path}: {health.missing_chunks} chunks missing")

        return health_report

    def _check_chunk_exists(self, remote: str, path: str) -> bool:
        """
        Check if a chunk exists.

        Args:
            remote: Remote name
            path: Chunk path

        Returns:
            True if chunk exists
        """
        try:
            data = self.backend.download_byte_range(remote, path, 0, 1)
            return data is not None
        except Exception:
            return False

    def _select_parity_remote(self) -> str:
        """
        Select a remote for parity chunk.

        Returns:
            Remote name
        """
        # For now, use simple round-robin
        # Could be enhanced to prefer less-used remotes
        import random

        return random.choice(self.config.remotes)
