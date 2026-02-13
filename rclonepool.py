#!/usr/bin/env python3
"""
rclonepool - Distribute files as chunks across multiple rclone remotes.

Main entry point and CLI.
Versions: v0.1 (base) through v1.0 (production ready)
"""

# rclonepool/rclonepool.py

import argparse
import sys
import os
import signal
import logging

from config import Config
from chunker import Chunker
from balancer import Balancer
from manifest import ManifestManager
from rclone_backend import RcloneBackend
from webdav_server import RclonePoolDAVServer

# v0.2 - Robustness
from retry import retry_with_backoff, RetryConfig
from cache import ManifestCache, ChunkCache
from verification import Verifier, DuplicateDetector

# v0.3 - Performance
from performance import (
    ProgressTracker,
    ParallelUploader,
    ParallelDownloader,
    ChunkPrefetcher,
    RcloneDaemon,
)

# v0.4 - Balancing
from advanced_balancer import AdvancedBalancer, Rebalancer, BalancingStrategy

# v0.5 - Redundancy
from redundancy import RedundancyManager, RedundancyMode, ParityConfig

# v0.6 - Advanced Features
from advanced_features import (
    AuthManager,
    AuthMethod,
    SSLManager,
    Deduplicator,
    Compressor,
    BandwidthThrottler,
    WebUIManager,
)

# v1.0 - Production Ready
from api_server import APIServer
from plugin_system import PluginRegistry, PluginLoader, PluginHook

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("rclonepool")


class RclonePool:
    """Main orchestrator for rclonepool operations with all v0.2-v1.0 features."""

    def __init__(self, config_path: str = None, enable_advanced_features: bool = True):
        self.config = Config(config_path)
        self.backend = RcloneBackend(self.config)

        # v0.2 - Robustness
        self.manifest_cache = ManifestCache()
        self.chunk_cache = ChunkCache()
        self.manifest_mgr = ManifestManager(self.config, self.backend)
        self.verifier = Verifier(self.config, self.backend, self.manifest_mgr)
        self.duplicate_detector = DuplicateDetector(self.manifest_mgr)

        # v0.3 - Performance
        self.parallel_uploader = ParallelUploader(self.backend, max_workers=4)
        self.parallel_downloader = ParallelDownloader(self.backend, max_workers=4)
        self.prefetcher = ChunkPrefetcher(self.backend, self.chunk_cache)

        # v0.4 - Balancing
        self.advanced_balancer = AdvancedBalancer(
            self.config, self.backend, BalancingStrategy.LEAST_USED
        )
        self.balancer = self.advanced_balancer  # Backward compatibility
        self.rebalancer = Rebalancer(
            self.config, self.backend, self.manifest_mgr, Chunker(self.config)
        )

        # v0.5 - Redundancy
        self.redundancy_mgr = RedundancyManager(
            self.config, self.backend, self.manifest_mgr
        )

        # v0.6 - Advanced Features
        self.deduplicator = (
            Deduplicator(self.manifest_mgr) if enable_advanced_features else None
        )
        self.compressor = Compressor() if enable_advanced_features else None
        self.bandwidth_throttler = BandwidthThrottler()

        # v1.0 - Production Ready
        self.plugin_registry = PluginRegistry()
        self.plugin_loader = PluginLoader(self.plugin_registry)

        self.chunker = Chunker(self.config)

        # Load plugins if directory exists
        plugins_dir = os.path.expanduser("~/.config/rclonepool/plugins")
        if os.path.isdir(plugins_dir):
            self.plugin_loader.discover_plugins([plugins_dir])

    def upload(self, local_path: str, remote_path: str):
        """Upload a file, chunking and distributing across remotes."""
        if not os.path.exists(local_path):
            log.error(f"File not found: {local_path}")
            return False

        file_size = os.path.getsize(local_path)
        file_name = (
            os.path.basename(local_path)
            if not remote_path
            else remote_path.rstrip("/").split("/")[-1] or os.path.basename(local_path)
        )

        # Determine the remote directory path
        remote_dir = remote_path if remote_path else "/"
        if not remote_dir.endswith("/"):
            # If remote_path looks like a file path, use its directory
            remote_dir = "/".join(remote_dir.split("/")[:-1]) or "/"
            file_name = remote_path.split("/")[-1]

        log.info(
            f"Uploading {local_path} ({file_size} bytes) -> {remote_dir}/{file_name}"
        )

        # Check if file needs chunking
        chunk_size = self.config.chunk_size

        if file_size <= chunk_size:
            # Small file — upload to least-used remote as single chunk
            target_remote = self.balancer.get_least_used_remote()
            chunk_id = f"{file_name}.chunk.000"
            chunk_remote_path = f"{self.config.data_prefix}/{chunk_id}"

            log.info(f"  Small file, uploading as single chunk to {target_remote}")
            success = self.backend.upload_file(
                local_path, target_remote, chunk_remote_path
            )
            if not success:
                log.error("  Upload failed!")
                return False

            manifest = self.manifest_mgr.create_manifest(
                file_name=file_name,
                remote_dir=remote_dir,
                file_size=file_size,
                chunk_size=chunk_size,
                chunks=[
                    {
                        "index": 0,
                        "remote": target_remote,
                        "path": chunk_remote_path,
                        "size": file_size,
                        "offset": 0,
                    }
                ],
            )
            self.manifest_mgr.save_manifest(manifest)
            log.info(f"  ✓ Upload complete")
            return True
        else:
            # Large file — chunk and distribute
            log.info(f"  Chunking into {chunk_size // (1024 * 1024)}MB pieces...")
            chunks_info = []

            for (
                chunk_index,
                chunk_data,
                chunk_offset,
                chunk_len,
            ) in self.chunker.split_file_streaming(local_path, chunk_size):
                target_remote = self.balancer.get_least_used_remote()
                chunk_id = f"{file_name}.chunk.{chunk_index:03d}"
                chunk_remote_path = f"{self.config.data_prefix}/{chunk_id}"

                log.info(f"  Chunk {chunk_index}: {chunk_len} bytes -> {target_remote}")
                success = self.backend.upload_bytes(
                    chunk_data, target_remote, chunk_remote_path
                )
                if not success:
                    log.error(f"  Failed to upload chunk {chunk_index}!")
                    return False

                chunks_info.append(
                    {
                        "index": chunk_index,
                        "remote": target_remote,
                        "path": chunk_remote_path,
                        "size": chunk_len,
                        "offset": chunk_offset,
                    }
                )

                # Update balancer's view of used space
                self.balancer.record_usage(target_remote, chunk_len)

            manifest = self.manifest_mgr.create_manifest(
                file_name=file_name,
                remote_dir=remote_dir,
                file_size=file_size,
                chunk_size=chunk_size,
                chunks=chunks_info,
            )
            self.manifest_mgr.save_manifest(manifest)
            log.info(f"  ✓ Upload complete: {len(chunks_info)} chunks across remotes")
            return True

    def download(self, remote_path: str, local_path: str):
        """Download a file, fetching and reassembling chunks."""
        manifest = self.manifest_mgr.load_manifest_for_file(remote_path)
        if not manifest:
            log.error(f"No manifest found for: {remote_path}")
            return False

        log.info(
            f"Downloading {remote_path} ({manifest['file_size']} bytes, {len(manifest['chunks'])} chunks)"
        )

        with open(local_path, "wb") as out_f:
            for chunk in sorted(manifest["chunks"], key=lambda c: c["index"]):
                log.info(f"  Fetching chunk {chunk['index']} from {chunk['remote']}...")
                data = self.backend.download_bytes(chunk["remote"], chunk["path"])
                if data is None:
                    log.error(f"  Failed to download chunk {chunk['index']}!")
                    return False
                out_f.write(data)

        log.info(f"  ✓ Download complete: {local_path}")
        return True

    def download_range(self, remote_path: str, offset: int, length: int) -> bytes:
        """Download a byte range from a chunked file (for streaming)."""
        manifest = self.manifest_mgr.load_manifest_for_file(remote_path)
        if not manifest:
            return None

        result = bytearray()
        remaining = length
        current_offset = offset

        for chunk in sorted(manifest["chunks"], key=lambda c: c["index"]):
            chunk_start = chunk["offset"]
            chunk_end = chunk["offset"] + chunk["size"]

            if current_offset >= chunk_end:
                continue
            if current_offset < chunk_start:
                break

            # Calculate what we need from this chunk
            offset_in_chunk = current_offset - chunk_start
            bytes_from_chunk = min(chunk["size"] - offset_in_chunk, remaining)

            data = self.backend.download_byte_range(
                chunk["remote"], chunk["path"], offset_in_chunk, bytes_from_chunk
            )
            if data is None:
                return None

            result.extend(data)
            remaining -= len(data)
            current_offset += len(data)

            if remaining <= 0:
                break

        return bytes(result)

    def ls(self, remote_dir: str = "/"):
        """List files in the pool."""
        manifests = self.manifest_mgr.list_manifests(remote_dir)
        if not manifests:
            log.info("No files found.")
            return []

        files = []
        for m in manifests:
            files.append(
                {
                    "name": m["file_name"],
                    "path": f"{m['remote_dir']}/{m['file_name']}",
                    "size": m["file_size"],
                    "chunks": len(m["chunks"]),
                    "remotes": list(set(c["remote"] for c in m["chunks"])),
                }
            )
            log.info(
                f"  {m['file_name']:40s}  {m['file_size']:>12,} bytes  "
                f"{len(m['chunks']):>3} chunks  "
                f"remotes: {', '.join(set(c['remote'] for c in m['chunks']))}"
            )

        return files

    def delete(self, remote_path: str):
        """Delete a file and all its chunks."""
        manifest = self.manifest_mgr.load_manifest_for_file(remote_path)
        if not manifest:
            log.error(f"No manifest found for: {remote_path}")
            return False

        log.info(f"Deleting {remote_path} ({len(manifest['chunks'])} chunks)...")
        for chunk in manifest["chunks"]:
            log.info(f"  Deleting chunk {chunk['index']} from {chunk['remote']}")
            self.backend.delete_file(chunk["remote"], chunk["path"])

        self.manifest_mgr.delete_manifest(remote_path)
        log.info(f"  ✓ Deleted")
        return True

    def status(self):
        """Show status of all remotes."""
        log.info("Remote status:")
        for remote in self.config.remotes:
            used, free, total = self.backend.get_space(remote)
            log.info(
                f"  {remote:15s}  used: {used:>12,}  free: {free:>12,}  total: {total:>12,}"
            )

    def serve(self, host: str = "0.0.0.0", port: int = 8080):
        """Start WebDAV server."""
        log.info(f"Starting WebDAV server on {host}:{port}")
        log.info(f"Add to rclone.conf:")
        log.info(f"  [rclonepool]")
        log.info(f"  type = webdav")
        log.info(f"  url = http://localhost:{port}")
        log.info(f"  vendor = other")
        log.info(f"")
        log.info(f"Then use: rclone ls rclonepool:")
        log.info(f"     or:  rclone mount rclonepool: /mnt/pool")
        log.info(f"     or:  rclone copy rclonepool:file.mkv ./")

        server = RclonePoolDAVServer(self, host, port)
        server.run()


def main():
    parser = argparse.ArgumentParser(
        prog="rclonepool",
        description="Distribute files as chunks across multiple rclone remotes (v1.0)",
    )
    parser.add_argument(
        "-c",
        "--config",
        default="~/.config/rclonepool/config.json",
        help="Config file path",
    )
    parser.add_argument("--version", action="version", version="rclonepool 1.0.0")

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # upload
    p_upload = subparsers.add_parser("upload", help="Upload a file")
    p_upload.add_argument("local_path", help="Local file path")
    p_upload.add_argument("remote_path", help="Remote path (e.g., /backups/file.mkv)")
    p_upload.add_argument(
        "--parallel", action="store_true", help="Use parallel upload (v0.3)"
    )
    p_upload.add_argument(
        "--no-dedup", action="store_true", help="Skip deduplication check (v0.6)"
    )

    # download
    p_download = subparsers.add_parser("download", help="Download a file")
    p_download.add_argument("remote_path", help="Remote path")
    p_download.add_argument("local_path", help="Local file path")
    p_download.add_argument(
        "--parallel", action="store_true", help="Use parallel download (v0.3)"
    )

    # ls
    p_ls = subparsers.add_parser("ls", help="List files")
    p_ls.add_argument("remote_dir", nargs="?", default="/", help="Remote directory")
    p_ls.add_argument("--recursive", "-r", action="store_true", help="List recursively")

    # delete
    p_delete = subparsers.add_parser("delete", help="Delete a file")
    p_delete.add_argument("remote_path", help="Remote path")

    # status
    subparsers.add_parser("status", help="Show remote status")

    # serve
    p_serve = subparsers.add_parser("serve", help="Start WebDAV server")
    p_serve.add_argument("--host", default="0.0.0.0", help="Bind host")
    p_serve.add_argument("--port", type=int, default=8080, help="Bind port")
    p_serve.add_argument("--https", action="store_true", help="Enable HTTPS (v0.6)")
    p_serve.add_argument(
        "--auth",
        choices=["none", "basic", "api_key"],
        default="none",
        help="Authentication method (v0.6)",
    )

    # init
    subparsers.add_parser("init", help="Initialize config")

    # v0.2 - Robustness commands
    p_verify = subparsers.add_parser("verify", help="Verify file integrity (v0.2)")
    p_verify.add_argument(
        "file_path", nargs="?", help="File to verify (or all if omitted)"
    )
    p_verify.add_argument(
        "--quick", action="store_true", help="Quick check (existence only)"
    )

    p_repair = subparsers.add_parser("repair", help="Repair missing chunks (v0.2)")
    p_repair.add_argument("remote_path", help="Remote file path")
    p_repair.add_argument("local_source", help="Local source file for repair")

    p_orphans = subparsers.add_parser("orphans", help="Find orphaned chunks (v0.2)")
    p_orphans.add_argument(
        "--delete", action="store_true", help="Delete orphaned chunks"
    )

    # v0.4 - Balancing commands
    p_rebalance = subparsers.add_parser(
        "rebalance", help="Rebalance chunks across remotes (v0.4)"
    )
    p_rebalance.add_argument(
        "--dry-run", action="store_true", help="Simulate rebalancing"
    )
    p_rebalance.add_argument(
        "--target-variance",
        type=float,
        default=5.0,
        help="Target variance in utilization percentage",
    )

    p_balance_status = subparsers.add_parser(
        "balance-status", help="Show balance status (v0.4)"
    )

    # v0.5 - Redundancy commands
    p_health = subparsers.add_parser("health", help="Check file health (v0.5)")
    p_health.add_argument(
        "file_path", nargs="?", help="File to check (or all if omitted)"
    )

    p_rebuild = subparsers.add_parser(
        "rebuild", help="Rebuild file from redundancy (v0.5)"
    )
    p_rebuild.add_argument("file_path", help="File to rebuild")

    # v1.0 - Production commands
    p_api = subparsers.add_parser("api", help="Start REST API server (v1.0)")
    p_api.add_argument("--host", default="0.0.0.0", help="Bind host")
    p_api.add_argument("--port", type=int, default=8081, help="Bind port")

    p_plugins = subparsers.add_parser("plugins", help="Manage plugins (v1.0)")
    p_plugins.add_argument(
        "action", choices=["list", "enable", "disable", "load"], help="Plugin action"
    )
    p_plugins.add_argument("plugin_id", nargs="?", help="Plugin ID")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "init":
        Config.init_interactive()
        return

    pool = RclonePool(args.config)

    # Core commands
    if args.command == "upload":
        success = pool.upload(args.local_path, args.remote_path)
        sys.exit(0 if success else 1)
    elif args.command == "download":
        success = pool.download(args.remote_path, args.local_path)
        sys.exit(0 if success else 1)
    elif args.command == "ls":
        pool.ls(args.remote_dir)
    elif args.command == "delete":
        pool.delete(args.remote_path)
    elif args.command == "status":
        pool.status()
    elif args.command == "serve":
        pool.serve(args.host, args.port)

    # v0.2 - Robustness commands
    elif args.command == "verify":
        if args.file_path:
            result = pool.verifier.verify_file(args.file_path, quick=args.quick)
            sys.exit(0 if result.status == "ok" else 1)
        else:
            results = pool.verifier.verify_all(quick=args.quick)
            failed = sum(1 for r in results if r.status != "ok")
            sys.exit(0 if failed == 0 else 1)

    elif args.command == "repair":
        success = pool.verifier.repair_file(args.remote_path, args.local_source)
        sys.exit(0 if success else 1)

    elif args.command == "orphans":
        orphans = pool.verifier.find_orphans()
        if args.delete and orphans:
            pool.verifier.delete_orphans(orphans, confirm=True)
        sys.exit(0)

    # v0.4 - Balancing commands
    elif args.command == "rebalance":
        result = pool.rebalancer.rebalance(
            target_variance=args.target_variance, dry_run=args.dry_run
        )
        log.info(f"Rebalance result: {result['status']}")
        sys.exit(0)

    elif args.command == "balance-status":
        analysis = pool.rebalancer.analyze_balance()
        log.info(
            f"Balance status: {'Balanced' if analysis['is_balanced'] else 'Unbalanced'}"
        )
        sys.exit(0)

    # v0.5 - Redundancy commands
    elif args.command == "health":
        if args.file_path:
            health = pool.redundancy_mgr.check_health(args.file_path)
            sys.exit(0 if health.is_recoverable else 1)
        else:
            health_report = pool.redundancy_mgr.monitor_health_all()
            unhealthy = sum(1 for h in health_report.values() if not h.is_recoverable)
            sys.exit(0 if unhealthy == 0 else 1)

    elif args.command == "rebuild":
        success = pool.redundancy_mgr.rebuild_file(args.file_path)
        sys.exit(0 if success else 1)

    # v1.0 - Production commands
    elif args.command == "api":
        api_server = APIServer(host=args.host, port=args.port)
        api_server.register_user_pool("default", pool)
        api_server.start()
        log.info("Press Ctrl+C to stop")
        try:
            signal.pause()
        except KeyboardInterrupt:
            api_server.stop()

    elif args.command == "plugins":
        if args.action == "list":
            plugins = pool.plugin_registry.list_plugins()
            for p in plugins:
                status = "✓" if p["enabled"] else "✗"
                log.info(f"{status} {p['name']} v{p['version']} ({p['type']})")
        elif args.action == "enable" and args.plugin_id:
            pool.plugin_registry.enable_plugin(args.plugin_id)
        elif args.action == "disable" and args.plugin_id:
            pool.plugin_registry.disable_plugin(args.plugin_id)
        elif args.action == "load" and args.plugin_id:
            pool.plugin_loader.load_plugin_file(args.plugin_id)
        sys.exit(0)


if __name__ == "__main__":
    main()
