"""
Verification and repair functionality for rclonepool.
Part of v0.2 Robustness features.

Provides commands to:
- verify: Check all chunks exist and match manifest
- repair: Re-upload missing chunks from local copy
- orphans: Find chunks with no manifest reference
"""

import os
import logging
from typing import List, Dict, Set, Tuple, Optional
from dataclasses import dataclass

log = logging.getLogger("rclonepool")


@dataclass
class VerificationResult:
    """Result of a verification operation."""

    file_path: str
    status: str  # "ok", "missing_chunks", "corrupt", "error"
    missing_chunks: List[int]
    error_message: Optional[str] = None
    total_chunks: int = 0
    verified_chunks: int = 0


@dataclass
class OrphanChunk:
    """Information about an orphaned chunk."""

    remote: str
    path: str
    size: int


class Verifier:
    """Handles verification and repair operations."""

    def __init__(self, config, backend, manifest_mgr):
        """
        Initialize verifier.

        Args:
            config: RclonePool configuration
            backend: RcloneBackend instance
            manifest_mgr: ManifestManager instance
        """
        self.config = config
        self.backend = backend
        self.manifest_mgr = manifest_mgr

    def verify_file(self, file_path: str, quick: bool = False) -> VerificationResult:
        """
        Verify a single file's chunks exist.

        Args:
            file_path: Remote file path
            quick: If True, only check existence; if False, also verify sizes

        Returns:
            VerificationResult
        """
        log.info(f"Verifying {file_path}...")

        # Load manifest
        manifest = self.manifest_mgr.load_manifest_for_file(file_path)
        if not manifest:
            return VerificationResult(
                file_path=file_path,
                status="error",
                missing_chunks=[],
                error_message="Manifest not found",
                total_chunks=0,
                verified_chunks=0,
            )

        chunks = manifest.get("chunks", [])
        total_chunks = len(chunks)
        missing_chunks = []
        verified_chunks = 0

        log.info(f"  Checking {total_chunks} chunks...")

        for chunk in chunks:
            chunk_index = chunk.get("index")
            remote = chunk.get("remote")
            chunk_path = chunk.get("path")
            expected_size = chunk.get("size")

            # Check if chunk exists
            exists = self._check_chunk_exists(
                remote, chunk_path, expected_size if not quick else None
            )

            if exists:
                verified_chunks += 1
                log.debug(f"  ✓ Chunk {chunk_index} exists on {remote}")
            else:
                missing_chunks.append(chunk_index)
                log.warning(f"  ✗ Chunk {chunk_index} missing or corrupted on {remote}")

        if missing_chunks:
            status = "missing_chunks"
            log.error(
                f"  File verification FAILED: {len(missing_chunks)} chunks missing"
            )
        else:
            status = "ok"
            log.info(f"  ✓ File verification passed: all {total_chunks} chunks present")

        return VerificationResult(
            file_path=file_path,
            status=status,
            missing_chunks=missing_chunks,
            total_chunks=total_chunks,
            verified_chunks=verified_chunks,
        )

    def verify_all(self, quick: bool = False) -> List[VerificationResult]:
        """
        Verify all files in the pool.

        Args:
            quick: If True, only check existence; if False, also verify sizes

        Returns:
            List of VerificationResult objects
        """
        log.info("Verifying all files in pool...")

        manifests = self.manifest_mgr.list_manifests("/", recursive=True)
        results = []

        for manifest in manifests:
            file_path = manifest.get("file_path")
            result = self.verify_file(file_path, quick=quick)
            results.append(result)

        # Summary
        total_files = len(results)
        ok_count = sum(1 for r in results if r.status == "ok")
        failed_count = total_files - ok_count

        log.info(f"\nVerification Summary:")
        log.info(f"  Total files: {total_files}")
        log.info(f"  Passed: {ok_count}")
        log.info(f"  Failed: {failed_count}")

        if failed_count > 0:
            log.warning(f"\n{failed_count} file(s) have missing or corrupted chunks:")
            for r in results:
                if r.status != "ok":
                    log.warning(
                        f"  {r.file_path}: {len(r.missing_chunks)} missing chunks"
                    )

        return results

    def repair_file(self, file_path: str, local_source_path: str) -> bool:
        """
        Repair a file by re-uploading missing chunks from a local copy.

        Args:
            file_path: Remote file path
            local_source_path: Local file to use for repair

        Returns:
            True if repair succeeded
        """
        log.info(f"Repairing {file_path} from {local_source_path}...")

        if not os.path.exists(local_source_path):
            log.error(f"Local source file not found: {local_source_path}")
            return False

        # Verify first to identify missing chunks
        result = self.verify_file(file_path)

        if result.status == "error":
            log.error(f"Cannot repair: {result.error_message}")
            return False

        if result.status == "ok":
            log.info("File is already intact, no repair needed")
            return True

        manifest = self.manifest_mgr.load_manifest_for_file(file_path)
        chunk_size = manifest.get("chunk_size")

        log.info(f"Re-uploading {len(result.missing_chunks)} missing chunks...")

        # Re-upload missing chunks
        repaired_count = 0
        for chunk_index in result.missing_chunks:
            chunk_info = manifest["chunks"][chunk_index]
            remote = chunk_info.get("remote")
            chunk_path = chunk_info.get("path")
            offset = chunk_info.get("offset")
            size = chunk_info.get("size")

            log.info(f"  Repairing chunk {chunk_index} -> {remote}")

            # Read chunk data from local file
            try:
                with open(local_source_path, "rb") as f:
                    f.seek(offset)
                    chunk_data = f.read(size)

                if len(chunk_data) != size:
                    log.error(
                        f"  Failed to read correct amount of data for chunk {chunk_index}"
                    )
                    continue

                # Upload chunk
                success = self.backend.upload_bytes(chunk_data, remote, chunk_path)
                if success:
                    log.info(f"  ✓ Chunk {chunk_index} repaired")
                    repaired_count += 1
                else:
                    log.error(f"  ✗ Failed to upload chunk {chunk_index}")

            except IOError as e:
                log.error(f"  Failed to read chunk {chunk_index} from local file: {e}")
                continue

        log.info(
            f"Repair complete: {repaired_count}/{len(result.missing_chunks)} chunks restored"
        )

        # Verify again
        log.info("Re-verifying file...")
        final_result = self.verify_file(file_path)

        if final_result.status == "ok":
            log.info("✓ File successfully repaired and verified")
            return True
        else:
            log.error(
                f"✗ File still has {len(final_result.missing_chunks)} missing chunks after repair"
            )
            return False

    def find_orphans(self) -> List[OrphanChunk]:
        """
        Find chunks that have no corresponding manifest entry.

        Returns:
            List of OrphanChunk objects
        """
        log.info("Scanning for orphaned chunks...")

        # Get all chunk paths referenced in manifests
        referenced_chunks: Set[Tuple[str, str]] = set()

        manifests = self.manifest_mgr.list_manifests("/", recursive=True)
        for manifest in manifests:
            for chunk in manifest.get("chunks", []):
                remote = chunk.get("remote")
                path = chunk.get("path")
                referenced_chunks.add((remote, path))

        log.info(
            f"  Found {len(referenced_chunks)} chunks referenced in {len(manifests)} manifests"
        )

        # Scan all remotes for chunks
        orphans = []

        for remote in self.config.remotes:
            log.info(f"  Scanning {remote}...")

            try:
                files = self.backend.list_files(remote, self.config.data_prefix)
                if not files:
                    continue

                for file_name in files:
                    chunk_path = f"{self.config.data_prefix}/{file_name}"

                    if (remote, chunk_path) not in referenced_chunks:
                        # This is an orphan
                        log.warning(f"  Found orphan: {remote}{chunk_path}")
                        orphans.append(
                            OrphanChunk(
                                remote=remote,
                                path=chunk_path,
                                size=0,  # We could get actual size if needed
                            )
                        )

            except Exception as e:
                log.error(f"  Error scanning {remote}: {e}")
                continue

        log.info(f"\nFound {len(orphans)} orphaned chunks")

        if orphans:
            log.warning("\nOrphaned chunks:")
            for orphan in orphans:
                log.warning(f"  {orphan.remote}{orphan.path}")

        return orphans

    def delete_orphans(
        self, orphans: List[OrphanChunk] = None, confirm: bool = True
    ) -> int:
        """
        Delete orphaned chunks.

        Args:
            orphans: List of orphans to delete (if None, will find them first)
            confirm: If True, ask for confirmation before deleting

        Returns:
            Number of orphans deleted
        """
        if orphans is None:
            orphans = self.find_orphans()

        if not orphans:
            log.info("No orphans to delete")
            return 0

        log.warning(f"\nAbout to delete {len(orphans)} orphaned chunks")

        if confirm:
            response = input("Are you sure? (yes/no): ").strip().lower()
            if response not in ("yes", "y"):
                log.info("Deletion cancelled")
                return 0

        deleted_count = 0
        for orphan in orphans:
            try:
                success = self.backend.delete_file(orphan.remote, orphan.path)
                if success:
                    log.info(f"  ✓ Deleted {orphan.remote}{orphan.path}")
                    deleted_count += 1
                else:
                    log.error(f"  ✗ Failed to delete {orphan.remote}{orphan.path}")
            except Exception as e:
                log.error(f"  Error deleting {orphan.remote}{orphan.path}: {e}")

        log.info(f"\nDeleted {deleted_count}/{len(orphans)} orphaned chunks")
        return deleted_count

    def _check_chunk_exists(
        self, remote: str, chunk_path: str, expected_size: Optional[int] = None
    ) -> bool:
        """
        Check if a chunk exists on a remote.

        Args:
            remote: Remote name
            chunk_path: Path to chunk
            expected_size: If provided, also verify size matches

        Returns:
            True if chunk exists (and size matches if specified)
        """
        try:
            # Try to download just 1 byte to check existence
            data = self.backend.download_byte_range(remote, chunk_path, 0, 1)

            if data is None:
                return False

            # If size check requested, download full chunk
            if expected_size is not None:
                full_data = self.backend.download_bytes(
                    remote, chunk_path, suppress_errors=True
                )
                if full_data is None:
                    return False
                if len(full_data) != expected_size:
                    log.warning(
                        f"Size mismatch: expected {expected_size}, got {len(full_data)}"
                    )
                    return False

            return True

        except Exception as e:
            log.debug(f"Error checking chunk {remote}{chunk_path}: {e}")
            return False


class DuplicateDetector:
    """Detects duplicate files before upload (v0.2)."""

    def __init__(self, manifest_mgr):
        """
        Initialize duplicate detector.

        Args:
            manifest_mgr: ManifestManager instance
        """
        self.manifest_mgr = manifest_mgr

    def find_duplicate(
        self, file_name: str, file_size: int, remote_dir: str = "/"
    ) -> Optional[dict]:
        """
        Check if a file with same name and size already exists.

        Args:
            file_name: Name of file to check
            file_size: Size of file
            remote_dir: Directory to check in

        Returns:
            Manifest of duplicate file if found, None otherwise
        """
        file_path = f"{remote_dir.rstrip('/')}/{file_name}"

        manifest = self.manifest_mgr.load_manifest_for_file(file_path)

        if manifest and manifest.get("file_size") == file_size:
            log.info(f"Duplicate file detected: {file_path} ({file_size} bytes)")
            return manifest

        return None

    def check_content_hash(self, local_path: str, manifest: dict) -> bool:
        """
        Check if a local file matches an existing manifest by comparing checksums.

        Args:
            local_path: Path to local file
            manifest: Manifest to compare against

        Returns:
            True if content matches
        """
        # This would require computing checksums
        # For now, we only do basic name/size matching
        # Could be enhanced with SHA256 comparison
        pass
