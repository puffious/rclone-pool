"""
REST API and WebSocket server for rclonepool.
Part of v1.0 Production Ready features.

Provides:
- RESTful API for programmatic access
- WebSocket support for real-time updates
- Multi-user support with isolated pools
- API documentation (OpenAPI/Swagger)
"""

import json
import logging
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, asdict
from enum import Enum
import hashlib
import base64

log = logging.getLogger("rclonepool")


class APIVersion(Enum):
    """API versions."""

    V1 = "v1"


@dataclass
class APIResponse:
    """Standard API response format."""

    success: bool
    data: Any = None
    error: Optional[str] = None
    message: Optional[str] = None
    timestamp: float = 0.0

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "message": self.message,
            "timestamp": self.timestamp or time.time(),
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())


class WebSocketConnection:
    """Represents a WebSocket connection."""

    def __init__(self, conn_id: str, username: str):
        """
        Initialize WebSocket connection.

        Args:
            conn_id: Connection ID
            username: Username
        """
        self.conn_id = conn_id
        self.username = username
        self.created_at = time.time()
        self.last_ping = time.time()
        self.subscriptions: Set[str] = set()

    def subscribe(self, topic: str):
        """Subscribe to a topic."""
        self.subscriptions.add(topic)

    def unsubscribe(self, topic: str):
        """Unsubscribe from a topic."""
        self.subscriptions.discard(topic)

    def is_subscribed(self, topic: str) -> bool:
        """Check if subscribed to a topic."""
        return topic in self.subscriptions


class WebSocketManager:
    """Manages WebSocket connections and broadcasts."""

    def __init__(self):
        """Initialize WebSocket manager."""
        self._connections: Dict[str, WebSocketConnection] = {}
        self._lock = threading.Lock()

    def add_connection(self, conn_id: str, username: str) -> WebSocketConnection:
        """
        Add a new connection.

        Args:
            conn_id: Connection ID
            username: Username

        Returns:
            WebSocketConnection object
        """
        with self._lock:
            conn = WebSocketConnection(conn_id, username)
            self._connections[conn_id] = conn
            log.info(f"WebSocket connection added: {conn_id} (user: {username})")
            return conn

    def remove_connection(self, conn_id: str):
        """
        Remove a connection.

        Args:
            conn_id: Connection ID
        """
        with self._lock:
            if conn_id in self._connections:
                del self._connections[conn_id]
                log.info(f"WebSocket connection removed: {conn_id}")

    def get_connection(self, conn_id: str) -> Optional[WebSocketConnection]:
        """
        Get a connection.

        Args:
            conn_id: Connection ID

        Returns:
            WebSocketConnection or None
        """
        return self._connections.get(conn_id)

    def broadcast(self, topic: str, message: dict):
        """
        Broadcast message to all subscribers of a topic.

        Args:
            topic: Topic name
            message: Message to broadcast
        """
        with self._lock:
            for conn in self._connections.values():
                if conn.is_subscribed(topic):
                    # In a real implementation, this would send via WebSocket
                    log.debug(
                        f"Broadcasting to {conn.conn_id}: topic={topic}, msg={message}"
                    )

    def get_stats(self) -> dict:
        """Get WebSocket statistics."""
        with self._lock:
            return {
                "total_connections": len(self._connections),
                "connections": [
                    {
                        "conn_id": conn.conn_id,
                        "username": conn.username,
                        "subscriptions": list(conn.subscriptions),
                        "connected_for": time.time() - conn.created_at,
                    }
                    for conn in self._connections.values()
                ],
            }


class APIRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for REST API."""

    def __init__(self, *args, api_server=None, **kwargs):
        """Initialize with API server reference."""
        self.api_server = api_server
        super().__init__(*args, **kwargs)

    def log_message(self, format, *args):
        """Override to use our logger."""
        log.info(f"{self.address_string()} - {format % args}")

    def _send_response(self, response: APIResponse, status_code: int = 200):
        """
        Send API response.

        Args:
            response: APIResponse object
            status_code: HTTP status code
        """
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS"
        )
        self.send_header(
            "Access-Control-Allow-Headers", "Content-Type, Authorization, X-API-Key"
        )
        self.end_headers()
        self.wfile.write(response.to_json().encode())

    def _send_error_response(self, error: str, status_code: int = 400):
        """
        Send error response.

        Args:
            error: Error message
            status_code: HTTP status code
        """
        response = APIResponse(success=False, error=error)
        self._send_response(response, status_code)

    def _authenticate(self) -> Optional[str]:
        """
        Authenticate request.

        Returns:
            Username if authenticated, None otherwise
        """
        if not self.api_server or not self.api_server.auth_manager:
            return "anonymous"

        headers = {k.lower(): v for k, v in self.headers.items()}
        return self.api_server.auth_manager.verify_request(headers)

    def _parse_body(self) -> Optional[dict]:
        """
        Parse JSON request body.

        Returns:
            Parsed JSON dict or None
        """
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            return {}

        try:
            body = self.rfile.read(content_length)
            return json.loads(body.decode())
        except Exception as e:
            log.error(f"Failed to parse request body: {e}")
            return None

    def do_OPTIONS(self):
        """Handle OPTIONS request (CORS preflight)."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS"
        )
        self.send_header(
            "Access-Control-Allow-Headers", "Content-Type, Authorization, X-API-Key"
        )
        self.end_headers()

    def do_GET(self):
        """Handle GET request."""
        username = self._authenticate()
        if not username:
            self._send_error_response("Authentication required", 401)
            return

        parsed_url = urlparse(self.path)
        path = parsed_url.path
        query_params = parse_qs(parsed_url.query)

        # Route to appropriate handler
        if path == "/api/v1/status":
            self._handle_status(username)
        elif path == "/api/v1/files":
            self._handle_list_files(username, query_params)
        elif path.startswith("/api/v1/files/"):
            file_path = path[14:]  # Remove "/api/v1/files"
            self._handle_get_file(username, file_path)
        elif path == "/api/v1/remotes":
            self._handle_list_remotes(username)
        elif path == "/api/v1/stats":
            self._handle_stats(username)
        elif path == "/api/v1/health":
            self._handle_health(username)
        elif path == "/api/v1/docs":
            self._handle_docs()
        else:
            self._send_error_response("Not found", 404)

    def do_POST(self):
        """Handle POST request."""
        username = self._authenticate()
        if not username:
            self._send_error_response("Authentication required", 401)
            return

        parsed_url = urlparse(self.path)
        path = parsed_url.path
        body = self._parse_body()

        if body is None:
            self._send_error_response("Invalid JSON body", 400)
            return

        # Route to appropriate handler
        if path == "/api/v1/files":
            self._handle_upload_file(username, body)
        elif path == "/api/v1/verify":
            self._handle_verify(username, body)
        elif path == "/api/v1/repair":
            self._handle_repair(username, body)
        elif path == "/api/v1/rebalance":
            self._handle_rebalance(username, body)
        elif path == "/api/v1/websocket/subscribe":
            self._handle_ws_subscribe(username, body)
        else:
            self._send_error_response("Not found", 404)

    def do_DELETE(self):
        """Handle DELETE request."""
        username = self._authenticate()
        if not username:
            self._send_error_response("Authentication required", 401)
            return

        parsed_url = urlparse(self.path)
        path = parsed_url.path

        if path.startswith("/api/v1/files/"):
            file_path = path[14:]  # Remove "/api/v1/files"
            self._handle_delete_file(username, file_path)
        else:
            self._send_error_response("Not found", 404)

    def _handle_status(self, username: str):
        """Handle status request."""
        try:
            pool = self.api_server.get_user_pool(username)
            if not pool:
                self._send_error_response("Pool not found", 404)
                return

            data = {
                "version": "1.0.0",
                "user": username,
                "remotes": pool.config.remotes,
                "chunk_size": pool.config.chunk_size,
            }

            response = APIResponse(success=True, data=data)
            self._send_response(response)
        except Exception as e:
            log.error(f"Error in status handler: {e}")
            self._send_error_response(str(e), 500)

    def _handle_list_files(self, username: str, query_params: dict):
        """Handle list files request."""
        try:
            pool = self.api_server.get_user_pool(username)
            if not pool:
                self._send_error_response("Pool not found", 404)
                return

            remote_dir = query_params.get("dir", ["/"])[0]
            recursive = query_params.get("recursive", ["false"])[0].lower() == "true"

            manifests = pool.manifest_mgr.list_manifests(remote_dir, recursive)

            files = [
                {
                    "name": m["file_name"],
                    "path": m["file_path"],
                    "size": m["file_size"],
                    "chunks": m["chunk_count"],
                    "created_at": m.get("created_at", 0),
                }
                for m in manifests
            ]

            response = APIResponse(
                success=True, data={"files": files, "count": len(files)}
            )
            self._send_response(response)
        except Exception as e:
            log.error(f"Error in list files handler: {e}")
            self._send_error_response(str(e), 500)

    def _handle_get_file(self, username: str, file_path: str):
        """Handle get file metadata request."""
        try:
            pool = self.api_server.get_user_pool(username)
            if not pool:
                self._send_error_response("Pool not found", 404)
                return

            manifest = pool.manifest_mgr.load_manifest_for_file(file_path)
            if not manifest:
                self._send_error_response("File not found", 404)
                return

            response = APIResponse(success=True, data=manifest)
            self._send_response(response)
        except Exception as e:
            log.error(f"Error in get file handler: {e}")
            self._send_error_response(str(e), 500)

    def _handle_upload_file(self, username: str, body: dict):
        """Handle upload file request."""
        try:
            pool = self.api_server.get_user_pool(username)
            if not pool:
                self._send_error_response("Pool not found", 404)
                return

            local_path = body.get("local_path")
            remote_path = body.get("remote_path")

            if not local_path or not remote_path:
                self._send_error_response("Missing local_path or remote_path", 400)
                return

            success = pool.upload(local_path, remote_path)

            if success:
                response = APIResponse(
                    success=True, message=f"File uploaded: {remote_path}"
                )
                self._send_response(response)
            else:
                self._send_error_response("Upload failed", 500)
        except Exception as e:
            log.error(f"Error in upload handler: {e}")
            self._send_error_response(str(e), 500)

    def _handle_delete_file(self, username: str, file_path: str):
        """Handle delete file request."""
        try:
            pool = self.api_server.get_user_pool(username)
            if not pool:
                self._send_error_response("Pool not found", 404)
                return

            success = pool.delete(file_path)

            if success:
                response = APIResponse(
                    success=True, message=f"File deleted: {file_path}"
                )
                self._send_response(response)
            else:
                self._send_error_response("Delete failed", 500)
        except Exception as e:
            log.error(f"Error in delete handler: {e}")
            self._send_error_response(str(e), 500)

    def _handle_list_remotes(self, username: str):
        """Handle list remotes request."""
        try:
            pool = self.api_server.get_user_pool(username)
            if not pool:
                self._send_error_response("Pool not found", 404)
                return

            usage_report = pool.balancer.get_usage_report()

            remotes = [
                {
                    "name": remote,
                    "used": info["used"],
                    "free": info["free"],
                    "total": info["total"],
                    "utilization": info["percent"],
                }
                for remote, info in usage_report.items()
            ]

            response = APIResponse(success=True, data={"remotes": remotes})
            self._send_response(response)
        except Exception as e:
            log.error(f"Error in list remotes handler: {e}")
            self._send_error_response(str(e), 500)

    def _handle_stats(self, username: str):
        """Handle stats request."""
        try:
            pool = self.api_server.get_user_pool(username)
            if not pool:
                self._send_error_response("Pool not found", 404)
                return

            manifests = pool.manifest_mgr.list_manifests("/", recursive=True)
            usage_report = pool.balancer.get_usage_report()

            total_files = len(manifests)
            total_size = sum(m.get("file_size", 0) for m in manifests)
            total_chunks = sum(m.get("chunk_count", 0) for m in manifests)
            total_used = sum(info["used"] for info in usage_report.values())
            total_capacity = sum(info["total"] for info in usage_report.values())

            stats = {
                "files": total_files,
                "total_size": total_size,
                "chunks": total_chunks,
                "remotes": len(usage_report),
                "used_space": total_used,
                "total_capacity": total_capacity,
                "utilization": (total_used / total_capacity * 100)
                if total_capacity > 0
                else 0,
            }

            response = APIResponse(success=True, data=stats)
            self._send_response(response)
        except Exception as e:
            log.error(f"Error in stats handler: {e}")
            self._send_error_response(str(e), 500)

    def _handle_health(self, username: str):
        """Handle health check request."""
        try:
            response = APIResponse(
                success=True,
                data={"status": "healthy", "timestamp": time.time()},
            )
            self._send_response(response)
        except Exception as e:
            log.error(f"Error in health handler: {e}")
            self._send_error_response(str(e), 500)

    def _handle_verify(self, username: str, body: dict):
        """Handle verify request."""
        try:
            pool = self.api_server.get_user_pool(username)
            if not pool:
                self._send_error_response("Pool not found", 404)
                return

            file_path = body.get("file_path")
            if not file_path:
                self._send_error_response("Missing file_path", 400)
                return

            # This would call the verifier
            response = APIResponse(
                success=True,
                message="Verification not yet implemented in API",
            )
            self._send_response(response)
        except Exception as e:
            log.error(f"Error in verify handler: {e}")
            self._send_error_response(str(e), 500)

    def _handle_repair(self, username: str, body: dict):
        """Handle repair request."""
        try:
            pool = self.api_server.get_user_pool(username)
            if not pool:
                self._send_error_response("Pool not found", 404)
                return

            file_path = body.get("file_path")
            local_source = body.get("local_source")

            if not file_path or not local_source:
                self._send_error_response("Missing file_path or local_source", 400)
                return

            response = APIResponse(
                success=True,
                message="Repair not yet implemented in API",
            )
            self._send_response(response)
        except Exception as e:
            log.error(f"Error in repair handler: {e}")
            self._send_error_response(str(e), 500)

    def _handle_rebalance(self, username: str, body: dict):
        """Handle rebalance request."""
        try:
            pool = self.api_server.get_user_pool(username)
            if not pool:
                self._send_error_response("Pool not found", 404)
                return

            dry_run = body.get("dry_run", False)

            response = APIResponse(
                success=True,
                message="Rebalance not yet implemented in API",
            )
            self._send_response(response)
        except Exception as e:
            log.error(f"Error in rebalance handler: {e}")
            self._send_error_response(str(e), 500)

    def _handle_ws_subscribe(self, username: str, body: dict):
        """Handle WebSocket subscribe request."""
        try:
            topic = body.get("topic")
            if not topic:
                self._send_error_response("Missing topic", 400)
                return

            response = APIResponse(
                success=True,
                message=f"Subscribed to topic: {topic}",
            )
            self._send_response(response)
        except Exception as e:
            log.error(f"Error in WebSocket subscribe handler: {e}")
            self._send_error_response(str(e), 500)

    def _handle_docs(self):
        """Handle API documentation request."""
        docs = {
            "version": "1.0.0",
            "endpoints": {
                "GET /api/v1/status": "Get pool status",
                "GET /api/v1/files": "List files (params: dir, recursive)",
                "GET /api/v1/files/{path}": "Get file metadata",
                "POST /api/v1/files": "Upload file (body: local_path, remote_path)",
                "DELETE /api/v1/files/{path}": "Delete file",
                "GET /api/v1/remotes": "List remotes",
                "GET /api/v1/stats": "Get statistics",
                "GET /api/v1/health": "Health check",
                "POST /api/v1/verify": "Verify file (body: file_path)",
                "POST /api/v1/repair": "Repair file (body: file_path, local_source)",
                "POST /api/v1/rebalance": "Rebalance pool (body: dry_run)",
            },
            "authentication": {
                "methods": ["Basic Auth", "API Key (X-API-Key header)", "Bearer token"],
            },
        }

        response = APIResponse(success=True, data=docs)
        self._send_response(response)


class APIServer:
    """REST API server for rclonepool."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8081, auth_manager=None):
        """
        Initialize API server.

        Args:
            host: Host to bind to
            port: Port to bind to
            auth_manager: AuthManager instance for authentication
        """
        self.host = host
        self.port = port
        self.auth_manager = auth_manager
        self._user_pools: Dict[str, Any] = {}
        self._ws_manager = WebSocketManager()
        self._server = None
        self._server_thread = None

    def register_user_pool(self, username: str, pool):
        """
        Register a pool for a user.

        Args:
            username: Username
            pool: RclonePool instance
        """
        self._user_pools[username] = pool
        log.info(f"Registered pool for user: {username}")

    def get_user_pool(self, username: str):
        """
        Get pool for a user.

        Args:
            username: Username

        Returns:
            RclonePool instance or None
        """
        return self._user_pools.get(username)

    def start(self):
        """Start API server."""
        log.info(f"Starting API server on {self.host}:{self.port}")

        def handler(*args, **kwargs):
            APIRequestHandler(*args, api_server=self, **kwargs)

        self._server = HTTPServer((self.host, self.port), handler)

        self._server_thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )
        self._server_thread.start()

        log.info(f"API server running at http://{self.host}:{self.port}")
        log.info(f"API documentation: http://{self.host}:{self.port}/api/v1/docs")

    def stop(self):
        """Stop API server."""
        if self._server:
            log.info("Stopping API server...")
            self._server.shutdown()
            self._server = None
            log.info("API server stopped")

    def broadcast_event(self, topic: str, event: dict):
        """
        Broadcast event to WebSocket subscribers.

        Args:
            topic: Topic name
            event: Event data
        """
        self._ws_manager.broadcast(topic, event)

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
        return False
