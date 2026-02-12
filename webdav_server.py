"""
WebDAV server — exposes rclonepool as a WebDAV endpoint.

This allows you to:
  - Add it as an rclone webdav remote
  - Use rclone mount on it
  - Use rclone copy/ls/etc on it
  - Stream video files with seeking support (Range requests)
"""

# rclonepool/webdav_server.py

import os
import io
import logging
import threading
import time
import signal
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import unquote, quote
import xml.etree.ElementTree as ET

log = logging.getLogger('rclonepool')


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in a separate thread for concurrency."""
    daemon_threads = True
    allow_reuse_address = True


class WebDAVHandler(BaseHTTPRequestHandler):
    """
    Minimal WebDAV handler that supports:
    - PROPFIND (directory listing)
    - GET with Range support (file download / streaming)
    - PUT (file upload)
    - DELETE (file deletion)
    - OPTIONS (capability discovery)
    - HEAD (file metadata)
    - MKCOL (create directory — virtual)
    - MOVE (rename/move files)
    """

    pool = None  # Set by RclonePoolDAVServer
    server_version = "rclonepool/1.0"

    def log_message(self, format, *args):
        log.debug(f"WebDAV: {format % args}")

    # ─── OPTIONS ───────────────────────────────────────────
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Allow', 'OPTIONS, GET, HEAD, PUT, DELETE, PROPFIND, MKCOL, MOVE')
        self.send_header('DAV', '1, 2')
        self.send_header('MS-Author-Via', 'DAV')
        self.send_header('Content-Length', '0')
        self.end_headers()

    # ─── HEAD ──────────────────────────────────────────────
    def do_HEAD(self):
        path = unquote(self.path).rstrip('/')
        if not path:
            path = '/'

        if path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'httpd/unix-directory')
            self.end_headers()
            return

        manifest = self.pool.manifest_mgr.load_manifest_for_file(path)
        if manifest:
            self.send_response(200)
            self.send_header('Content-Type', self._guess_content_type(path))
            self.send_header('Content-Length', str(manifest['file_size']))
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Last-Modified', self._format_time(manifest.get('created_at', 0)))
            self.end_headers()
        else:
            # Check if it's a directory
            manifests = self.pool.manifest_mgr.list_manifests(path)
            if manifests:
                self.send_response(200)
                self.send_header('Content-Type', 'httpd/unix-directory')
                self.end_headers()
            else:
                self.send_error(404, 'Not Found')

    # ─── GET (with Range support for video streaming) ─────
    def do_GET(self):
        path = unquote(self.path).rstrip('/')
        if not path:
            path = '/'

        if path == '/':
            self._send_directory_listing('/')
            return

        manifest = self.pool.manifest_mgr.load_manifest_for_file(path)
        if not manifest:
            # Maybe it's a directory
            manifests = self.pool.manifest_mgr.list_manifests(path)
            if manifests:
                self._send_directory_listing(path)
                return
            self.send_error(404, 'Not Found')
            return

        file_size = manifest['file_size']
        range_header = self.headers.get('Range')

        if range_header:
            try:
                range_spec = range_header.replace('bytes=', '').strip()

                if range_spec.startswith('-'):
                    suffix_len = int(range_spec[1:])
                    start = max(0, file_size - suffix_len)
                    end = file_size - 1
                elif range_spec.endswith('-'):
                    start = int(range_spec[:-1])
                    end = file_size - 1
                else:
                    parts = range_spec.split('-')
                    start = int(parts[0])
                    end = int(parts[1])

                # Clamp
                end = min(end, file_size - 1)
                length = end - start + 1

                if start >= file_size or start < 0 or length <= 0:
                    self.send_response(416)
                    self.send_header('Content-Range', f'bytes */{file_size}')
                    self.end_headers()
                    return

                data = self.pool.download_range(path, start, length)
                if data is None:
                    self.send_error(500, 'Failed to read range')
                    return

                self.send_response(206)
                self.send_header('Content-Type', self._guess_content_type(path))
                self.send_header('Content-Range', f'bytes {start}-{end}/{file_size}')
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Accept-Ranges', 'bytes')
                self.end_headers()
                self.wfile.write(data)

            except (ValueError, IndexError) as e:
                log.error(f"Invalid Range header: {range_header} — {e}")
                self.send_error(416, 'Range Not Satisfiable')
        else:
            # Full file download — stream chunk by chunk
            self.send_response(200)
            self.send_header('Content-Type', self._guess_content_type(path))
            self.send_header('Content-Length', str(file_size))
            self.send_header('Accept-Ranges', 'bytes')
            self.end_headers()

            for chunk in sorted(manifest['chunks'], key=lambda c: c['index']):
                try:
                    data = self.pool.backend.download_bytes(chunk['remote'], chunk['path'])
                    if data is None:
                        log.error(f"Failed to download chunk {chunk['index']}")
                        break
                    self.wfile.write(data)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    log.debug("Client disconnected during download")
                    break

    # ─── PUT (upload) ──────────────────────────────────────
    def do_PUT(self):
        path = unquote(self.path)
        content_length = int(self.headers.get('Content-Length', 0))

        if content_length == 0:
            self.send_error(411, 'Length Required')
            return

        log.info(f"WebDAV PUT: {path} ({content_length} bytes)")

        temp_path = os.path.join(
            self.pool.config.temp_dir,
            f"webdav_upload_{os.getpid()}_{threading.current_thread().ident}.tmp"
        )

        try:
            os.makedirs(os.path.dirname(temp_path), exist_ok=True)
            with open(temp_path, 'wb') as f:
                remaining = content_length
                while remaining > 0:
                    read_size = min(remaining, 8 * 1024 * 1024)
                    chunk = self.rfile.read(read_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    remaining -= len(chunk)

            success = self.pool.upload(temp_path, path)
            if success:
                self.send_response(201)
                self.send_header('Content-Length', '0')
                self.end_headers()
            else:
                self.send_error(500, 'Upload failed')
        finally:
            try:
                os.remove(temp_path)
            except OSError:
                pass

    # ─── DELETE ────────────────────────────────────────────
    def do_DELETE(self):
        path = unquote(self.path)
        log.info(f"WebDAV DELETE: {path}")

        success = self.pool.delete(path)
        if success:
            self.send_response(204)
            self.end_headers()
        else:
            self.send_error(404, 'Not Found')

    # ─── MKCOL ─────────────────────────────────────────────
    def do_MKCOL(self):
        # Virtual directories — always succeed
        self.send_response(201)
        self.send_header('Content-Length', '0')
        self.end_headers()

    # ─── MOVE ──────────────────────────────────────────────
    def do_MOVE(self):
        src_path = unquote(self.path)
        dest_header = self.headers.get('Destination', '')

        if not dest_header:
            self.send_error(400, 'Destination header required')
            return

        # Parse destination — strip scheme+host
        from urllib.parse import urlparse
        parsed = urlparse(dest_header)
        dest_path = unquote(parsed.path)

        log.info(f"WebDAV MOVE: {src_path} -> {dest_path}")

        manifest = self.pool.manifest_mgr.load_manifest_for_file(src_path)
        if not manifest:
            self.send_error(404, 'Source not found')
            return

        # Update manifest with new path
        dest_name = dest_path.rstrip('/').split('/')[-1]
        dest_dir = '/'.join(dest_path.rstrip('/').split('/')[:-1]) or '/'

        # Delete old manifest
        self.pool.manifest_mgr.delete_manifest(src_path)

        # Update and save new manifest
        manifest['file_name'] = dest_name
        manifest['remote_dir'] = dest_dir
        manifest['file_path'] = dest_path
        self.pool.manifest_mgr.save_manifest(manifest)

        self.send_response(201)
        self.send_header('Content-Length', '0')
        self.end_headers()

    # ─── PROPFIND ──────────────────────────────────────────
    def do_PROPFIND(self):
        path = unquote(self.path).rstrip('/')
        if not path:
            path = '/'

        depth = self.headers.get('Depth', '1')

        # Read and discard request body
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length > 0:
            self.rfile.read(content_length)

        responses = []

        if path == '/':
            responses.append(self._propfind_dir_response('/'))

            if depth != '0':
                manifests = self.pool.manifest_mgr.list_manifests('/')
                dirs = set()
                for m in manifests:
                    rd = m.get('remote_dir', '/')
                    if rd != '/':
                        parts = rd.strip('/').split('/')
                        if parts[0]:
                            dirs.add('/' + parts[0])

                for d in sorted(dirs):
                    responses.append(self._propfind_dir_response(d))

                for m in manifests:
                    if m.get('remote_dir', '/') == '/':
                        responses.append(self._propfind_file_response(
                            m['file_path'], m['file_size'], m.get('created_at', 0)
                        ))
        else:
            manifest = self.pool.manifest_mgr.load_manifest_for_file(path)
            if manifest:
                responses.append(self._propfind_file_response(
                    path, manifest['file_size'], manifest.get('created_at', 0)
                ))
            else:
                manifests = self.pool.manifest_mgr.list_manifests(path)
                if manifests:
                    responses.append(self._propfind_dir_response(path))
                    if depth != '0':
                        for m in manifests:
                            responses.append(self._propfind_file_response(
                                m['file_path'], m['file_size'], m.get('created_at', 0)
                            ))
                else:
                    self.send_error(404, 'Not Found')
                    return

        xml = self._build_multistatus(responses)

        self.send_response(207)
        self.send_header('Content-Type', 'application/xml; charset=utf-8')
        self.send_header('Content-Length', str(len(xml)))
        self.end_headers()
        self.wfile.write(xml)

    # ─── XML / Response Helpers ────────────────────────────

    def _propfind_dir_response(self, path: str) -> dict:
        href = quote(path + '/') if path != '/' else '/'
        return {
            'href': href,
            'is_dir': True,
            'size': 0,
            'modified': time.time()
        }

    def _propfind_file_response(self, path: str, size: int, modified: float) -> dict:
        return {
            'href': quote(path),
            'is_dir': False,
            'size': size,
            'modified': modified,
            'content_type': self._guess_content_type(path)
        }

    def _build_multistatus(self, responses: list) -> bytes:
        lines = ['<?xml version="1.0" encoding="utf-8"?>']
        lines.append('<D:multistatus xmlns:D="DAV:">')

        for resp in responses:
            lines.append('  <D:response>')
            lines.append(f'    <D:href>{resp["href"]}</D:href>')
            lines.append('    <D:propstat>')
            lines.append('      <D:prop>')

            if resp['is_dir']:
                lines.append('        <D:resourcetype><D:collection/></D:resourcetype>')
            else:
                lines.append('        <D:resourcetype/>')
                lines.append(f'        <D:getcontentlength>{resp["size"]}</D:getcontentlength>')
                ct = resp.get('content_type', 'application/octet-stream')
                lines.append(f'        <D:getcontenttype>{ct}</D:getcontenttype>')

            lines.append(f'        <D:getlastmodified>{self._format_time(resp["modified"])}</D:getlastmodified>')
            lines.append('      </D:prop>')
            lines.append('      <D:status>HTTP/1.1 200 OK</D:status>')
            lines.append('    </D:propstat>')
            lines.append('  </D:response>')

        lines.append('</D:multistatus>')

        return '\n'.join(lines).encode('utf-8')

    def _format_time(self, timestamp: float) -> str:
        if timestamp == 0:
            timestamp = time.time()
        return time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime(timestamp))

    def _guess_content_type(self, path: str) -> str:
        ext = os.path.splitext(path)[1].lower()
        types = {
            '.mp4': 'video/mp4',
            '.mkv': 'video/x-matroska',
            '.avi': 'video/x-msvideo',
            '.mov': 'video/quicktime',
            '.webm': 'video/webm',
            '.flv': 'video/x-flv',
            '.m4v': 'video/mp4',
            '.ts': 'video/mp2t',
            '.mp3': 'audio/mpeg',
            '.flac': 'audio/flac',
            '.wav': 'audio/wav',
            '.aac': 'audio/aac',
            '.ogg': 'audio/ogg',
            '.m4a': 'audio/mp4',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
            '.pdf': 'application/pdf',
            '.zip': 'application/zip',
            '.rar': 'application/x-rar-compressed',
            '.7z': 'application/x-7z-compressed',
            '.tar': 'application/x-tar',
            '.gz': 'application/gzip',
            '.txt': 'text/plain',
            '.json': 'application/json',
            '.xml': 'application/xml',
            '.html': 'text/html',
            '.srt': 'text/plain',
            '.ass': 'text/plain',
            '.sub': 'text/plain',
            '.iso': 'application/x-iso9660-image',
            '.img': 'application/octet-stream',
        }
        return types.get(ext, 'application/octet-stream')

    def _send_directory_listing(self, path: str):
        manifests = self.pool.manifest_mgr.list_manifests(path)

        html = f"""<!DOCTYPE html>
<html>
<head><title>rclonepool — {path}</title>
<style>
    body {{ font-family: monospace; padding: 20px; background: #1a1a2e; color: #eee; }}
    a {{ color: #4fc3f7; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ text-align: left; padding: 8px 16px; border-bottom: 1px solid #333; }}
    th {{ color: #aaa; }}
    .size {{ text-align: right; }}
    h2 {{ color: #4fc3f7; }}
</style>
</head>
<body>
<h2>📦 rclonepool — {path}</h2>
<table>
<tr><th>Name</th><th class="size">Size</th><th>Chunks</th><th>Remotes</th></tr>
"""
        if path != '/':
            parent = '/'.join(path.rstrip('/').split('/')[:-1]) or '/'
            html += f'<tr><td><a href="{quote(parent)}">⬆️ ..</a></td><td></td><td></td><td></td></tr>\n'

        for m in manifests:
            size_str = self._human_size(m['file_size'])
            remotes_used = ', '.join(sorted(set(c['remote'] for c in m['chunks'])))
            html += (f'<tr>'
                     f'<td><a href="{quote(m["file_path"])}">{m["file_name"]}</a></td>'
                     f'<td class="size">{size_str}</td>'
                     f'<td>{len(m["chunks"])}</td>'
                     f'<td>{remotes_used}</td>'
                     f'</tr>\n')

        html += """</table>
<hr>
<p>rclonepool WebDAV server · <a href="/">home</a></p>
</body></html>"""

        data = html.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    @staticmethod
    def _human_size(size: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"


class RclonePoolDAVServer:
    """WebDAV server wrapper with graceful shutdown."""

    def __init__(self, pool, host: str = '0.0.0.0', port: int = 8080):
        self.pool = pool
        self.host = host
        self.port = port
        self.server = None

    def run(self):
        """Start the WebDAV server (blocking)."""
        # Set the pool reference on the handler class
        WebDAVHandler.pool = self.pool

        self.server = ThreadedHTTPServer((self.host, self.port), WebDAVHandler)

        # Graceful shutdown on SIGINT/SIGTERM
        def shutdown_handler(signum, frame):
            log.info("\nShutting down WebDAV server...")
            threading.Thread(target=self.server.shutdown).start()

        signal.signal(signal.SIGINT, shutdown_handler)
        signal.signal(signal.SIGTERM, shutdown_handler)

        log.info(f"WebDAV server running on http://{self.host}:{self.port}")
        log.info(f"Press Ctrl+C to stop\n")

        try:
            self.server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self.server.server_close()
            log.info("WebDAV server stopped")

    def stop(self):
        """Stop the server."""
        if self.server:
            self.server.shutdown()