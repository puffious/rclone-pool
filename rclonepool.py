#!/usr/bin/env python3
"""
rclonepool - Distribute files as chunks across multiple rclone remotes.

Main entry point and CLI.
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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
log = logging.getLogger('rclonepool')


class RclonePool:
    """Main orchestrator for rclonepool operations."""

    def __init__(self, config_path: str = None):
        self.config = Config(config_path)
        self.backend = RcloneBackend(self.config)
        self.manifest_mgr = ManifestManager(self.config, self.backend)
        self.balancer = Balancer(self.config, self.backend)
        self.chunker = Chunker(self.config)

    def upload(self, local_path: str, remote_path: str):
        """Upload a file, chunking and distributing across remotes."""
        if not os.path.exists(local_path):
            log.error(f"File not found: {local_path}")
            return False

        file_size = os.path.getsize(local_path)
        file_name = os.path.basename(local_path) if not remote_path else remote_path.rstrip('/').split('/')[-1] or os.path.basename(local_path)

        # Determine the remote directory path
        remote_dir = remote_path if remote_path else '/'
        if not remote_dir.endswith('/'):
            # If remote_path looks like a file path, use its directory
            remote_dir = '/'.join(remote_dir.split('/')[:-1]) or '/'
            file_name = remote_path.split('/')[-1]

        log.info(f"Uploading {local_path} ({file_size} bytes) -> {remote_dir}/{file_name}")

        # Check if file needs chunking
        chunk_size = self.config.chunk_size

        if file_size <= chunk_size:
            # Small file — upload to least-used remote as single chunk
            target_remote = self.balancer.get_least_used_remote()
            chunk_id = f"{file_name}.chunk.000"
            chunk_remote_path = f"{self.config.data_prefix}/{chunk_id}"

            log.info(f"  Small file, uploading as single chunk to {target_remote}")
            success = self.backend.upload_file(local_path, target_remote, chunk_remote_path)
            if not success:
                log.error("  Upload failed!")
                return False

            manifest = self.manifest_mgr.create_manifest(
                file_name=file_name,
                remote_dir=remote_dir,
                file_size=file_size,
                chunk_size=chunk_size,
                chunks=[{
                    'index': 0,
                    'remote': target_remote,
                    'path': chunk_remote_path,
                    'size': file_size,
                    'offset': 0
                }]
            )
            self.manifest_mgr.save_manifest(manifest)
            log.info(f"  ✓ Upload complete")
            return True
        else:
            # Large file — chunk and distribute
            log.info(f"  Chunking into {chunk_size // (1024*1024)}MB pieces...")
            chunks_info = []

            for chunk_index, chunk_data, chunk_offset, chunk_len in self.chunker.split_file_streaming(local_path, chunk_size):
                target_remote = self.balancer.get_least_used_remote()
                chunk_id = f"{file_name}.chunk.{chunk_index:03d}"
                chunk_remote_path = f"{self.config.data_prefix}/{chunk_id}"

                log.info(f"  Chunk {chunk_index}: {chunk_len} bytes -> {target_remote}")
                success = self.backend.upload_bytes(chunk_data, target_remote, chunk_remote_path)
                if not success:
                    log.error(f"  Failed to upload chunk {chunk_index}!")
                    return False

                chunks_info.append({
                    'index': chunk_index,
                    'remote': target_remote,
                    'path': chunk_remote_path,
                    'size': chunk_len,
                    'offset': chunk_offset
                })

                # Update balancer's view of used space
                self.balancer.record_usage(target_remote, chunk_len)

            manifest = self.manifest_mgr.create_manifest(
                file_name=file_name,
                remote_dir=remote_dir,
                file_size=file_size,
                chunk_size=chunk_size,
                chunks=chunks_info
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

        log.info(f"Downloading {remote_path} ({manifest['file_size']} bytes, {len(manifest['chunks'])} chunks)")

        with open(local_path, 'wb') as out_f:
            for chunk in sorted(manifest['chunks'], key=lambda c: c['index']):
                log.info(f"  Fetching chunk {chunk['index']} from {chunk['remote']}...")
                data = self.backend.download_bytes(chunk['remote'], chunk['path'])
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

        for chunk in sorted(manifest['chunks'], key=lambda c: c['index']):
            chunk_start = chunk['offset']
            chunk_end = chunk['offset'] + chunk['size']

            if current_offset >= chunk_end:
                continue
            if current_offset < chunk_start:
                break

            # Calculate what we need from this chunk
            offset_in_chunk = current_offset - chunk_start
            bytes_from_chunk = min(chunk['size'] - offset_in_chunk, remaining)

            data = self.backend.download_byte_range(
                chunk['remote'], chunk['path'],
                offset_in_chunk, bytes_from_chunk
            )
            if data is None:
                return None

            result.extend(data)
            remaining -= len(data)
            current_offset += len(data)

            if remaining <= 0:
                break

        return bytes(result)

    def ls(self, remote_dir: str = '/'):
        """List files in the pool."""
        manifests = self.manifest_mgr.list_manifests(remote_dir)
        if not manifests:
            log.info("No files found.")
            return []

        files = []
        for m in manifests:
            files.append({
                'name': m['file_name'],
                'path': f"{m['remote_dir']}/{m['file_name']}",
                'size': m['file_size'],
                'chunks': len(m['chunks']),
                'remotes': list(set(c['remote'] for c in m['chunks']))
            })
            log.info(f"  {m['file_name']:40s}  {m['file_size']:>12,} bytes  "
                     f"{len(m['chunks']):>3} chunks  "
                     f"remotes: {', '.join(set(c['remote'] for c in m['chunks']))}")

        return files

    def delete(self, remote_path: str):
        """Delete a file and all its chunks."""
        manifest = self.manifest_mgr.load_manifest_for_file(remote_path)
        if not manifest:
            log.error(f"No manifest found for: {remote_path}")
            return False

        log.info(f"Deleting {remote_path} ({len(manifest['chunks'])} chunks)...")
        for chunk in manifest['chunks']:
            log.info(f"  Deleting chunk {chunk['index']} from {chunk['remote']}")
            self.backend.delete_file(chunk['remote'], chunk['path'])

        self.manifest_mgr.delete_manifest(remote_path)
        log.info(f"  ✓ Deleted")
        return True

    def status(self):
        """Show status of all remotes."""
        log.info("Remote status:")
        for remote in self.config.remotes:
            used, free, total = self.backend.get_space(remote)
            log.info(f"  {remote:15s}  used: {used:>12,}  free: {free:>12,}  total: {total:>12,}")

    def serve(self, host: str = '0.0.0.0', port: int = 8080):
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
        prog='rclonepool',
        description='Distribute files as chunks across multiple rclone remotes'
    )
    parser.add_argument('-c', '--config', default='~/.config/rclonepool/config.json',
                        help='Config file path')

    subparsers = parser.add_subparsers(dest='command', help='Command')

    # upload
    p_upload = subparsers.add_parser('upload', help='Upload a file')
    p_upload.add_argument('local_path', help='Local file path')
    p_upload.add_argument('remote_path', help='Remote path (e.g., /backups/file.mkv)')

    # download
    p_download = subparsers.add_parser('download', help='Download a file')
    p_download.add_argument('remote_path', help='Remote path')
    p_download.add_argument('local_path', help='Local file path')

    # ls
    p_ls = subparsers.add_parser('ls', help='List files')
    p_ls.add_argument('remote_dir', nargs='?', default='/', help='Remote directory')

    # delete
    p_delete = subparsers.add_parser('delete', help='Delete a file')
    p_delete.add_argument('remote_path', help='Remote path')

    # status
    subparsers.add_parser('status', help='Show remote status')

    # serve
    p_serve = subparsers.add_parser('serve', help='Start WebDAV server')
    p_serve.add_argument('--host', default='0.0.0.0', help='Bind host')
    p_serve.add_argument('--port', type=int, default=8080, help='Bind port')

    # init
    subparsers.add_parser('init', help='Initialize config')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == 'init':
        Config.init_interactive()
        return

    pool = RclonePool(args.config)

    if args.command == 'upload':
        success = pool.upload(args.local_path, args.remote_path)
        sys.exit(0 if success else 1)
    elif args.command == 'download':
        success = pool.download(args.remote_path, args.local_path)
        sys.exit(0 if success else 1)
    elif args.command == 'ls':
        pool.ls(args.remote_dir)
    elif args.command == 'delete':
        pool.delete(args.remote_path)
    elif args.command == 'status':
        pool.status()
    elif args.command == 'serve':
        pool.serve(args.host, args.port)


if __name__ == '__main__':
    main()