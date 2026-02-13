"""
Advanced features for rclonepool.
Part of v0.6 Advanced Features.

Provides:
- WebDAV authentication (Basic Auth, API key)
- HTTPS support for WebDAV server
- Deduplication (content-addressable storage)
- Compression before encryption (zstd)
- Bandwidth throttling
- Web UI dashboard
"""

import os
import ssl
import time
import hashlib
import logging
import threading
from typing import Optional, Dict, List, Tuple, Set
from dataclasses import dataclass
from enum import Enum
import base64
import secrets

log = logging.getLogger("rclonepool")


class AuthMethod(Enum):
    """Authentication methods."""

    NONE = "none"
    BASIC = "basic"
    API_KEY = "api_key"
    BEARER = "bearer"


@dataclass
class User:
    """User account information."""

    username: str
    password_hash: str
    api_key: Optional[str] = None
    enabled: bool = True
    created_at: float = 0.0
    last_login: float = 0.0


class AuthManager:
    """Manages authentication for WebDAV server."""

    def __init__(self, auth_method: AuthMethod = AuthMethod.NONE):
        """
        Initialize authentication manager.

        Args:
            auth_method: Authentication method to use
        """
        self.auth_method = auth_method
        self._users: Dict[str, User] = {}
        self._api_keys: Dict[str, str] = {}  # api_key -> username
        self._sessions: Dict[
            str, Tuple[str, float]
        ] = {}  # session_id -> (username, expiry)

    def add_user(self, username: str, password: str) -> User:
        """
        Add a user account.

        Args:
            username: Username
            password: Plain text password

        Returns:
            User object
        """
        password_hash = self._hash_password(password)
        api_key = self._generate_api_key()

        user = User(
            username=username,
            password_hash=password_hash,
            api_key=api_key,
            enabled=True,
            created_at=time.time(),
        )

        self._users[username] = user
        self._api_keys[api_key] = username

        log.info(f"User added: {username}")
        return user

    def remove_user(self, username: str) -> bool:
        """
        Remove a user account.

        Args:
            username: Username to remove

        Returns:
            True if user was removed
        """
        if username not in self._users:
            return False

        user = self._users[username]
        if user.api_key and user.api_key in self._api_keys:
            del self._api_keys[user.api_key]

        del self._users[username]
        log.info(f"User removed: {username}")
        return True

    def authenticate_basic(self, username: str, password: str) -> bool:
        """
        Authenticate with username and password.

        Args:
            username: Username
            password: Password

        Returns:
            True if authentication succeeded
        """
        if username not in self._users:
            return False

        user = self._users[username]
        if not user.enabled:
            return False

        password_hash = self._hash_password(password)
        if password_hash == user.password_hash:
            user.last_login = time.time()
            log.info(f"User authenticated: {username}")
            return True

        return False

    def authenticate_api_key(self, api_key: str) -> Optional[str]:
        """
        Authenticate with API key.

        Args:
            api_key: API key

        Returns:
            Username if authentication succeeded, None otherwise
        """
        username = self._api_keys.get(api_key)
        if username and username in self._users:
            user = self._users[username]
            if user.enabled:
                user.last_login = time.time()
                log.info(f"User authenticated via API key: {username}")
                return username

        return None

    def verify_request(self, headers: Dict[str, str]) -> Optional[str]:
        """
        Verify authentication from request headers.

        Args:
            headers: Request headers

        Returns:
            Username if authenticated, None otherwise
        """
        if self.auth_method == AuthMethod.NONE:
            return "anonymous"

        # Check for API key in header
        api_key = headers.get("X-API-Key") or headers.get("Authorization", "").replace(
            "Bearer ", ""
        )
        if api_key and self.auth_method in (AuthMethod.API_KEY, AuthMethod.BEARER):
            return self.authenticate_api_key(api_key)

        # Check for Basic Auth
        auth_header = headers.get("Authorization", "")
        if auth_header.startswith("Basic ") and self.auth_method == AuthMethod.BASIC:
            try:
                encoded = auth_header[6:]
                decoded = base64.b64decode(encoded).decode("utf-8")
                username, password = decoded.split(":", 1)
                if self.authenticate_basic(username, password):
                    return username
            except Exception as e:
                log.warning(f"Failed to parse Basic Auth header: {e}")

        return None

    def _hash_password(self, password: str) -> str:
        """Hash a password using SHA256."""
        return hashlib.sha256(password.encode()).hexdigest()

    def _generate_api_key(self) -> str:
        """Generate a random API key."""
        return secrets.token_urlsafe(32)


class SSLManager:
    """Manages SSL/TLS for HTTPS support."""

    def __init__(self, cert_file: Optional[str] = None, key_file: Optional[str] = None):
        """
        Initialize SSL manager.

        Args:
            cert_file: Path to SSL certificate file
            key_file: Path to SSL private key file
        """
        self.cert_file = cert_file
        self.key_file = key_file
        self._context: Optional[ssl.SSLContext] = None

    def create_self_signed_cert(
        self, cert_file: str, key_file: str, hostname: str = "localhost"
    ):
        """
        Create a self-signed certificate.

        Args:
            cert_file: Path to save certificate
            key_file: Path to save private key
            hostname: Hostname for certificate
        """
        try:
            from cryptography import x509
            from cryptography.x509.oid import NameOID
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.hazmat.primitives import serialization
            import datetime

            # Generate private key
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
            )

            # Create certificate
            subject = issuer = x509.Name(
                [
                    x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
                    x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "State"),
                    x509.NameAttribute(NameOID.LOCALITY_NAME, "City"),
                    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "rclonepool"),
                    x509.NameAttribute(NameOID.COMMON_NAME, hostname),
                ]
            )

            cert = (
                x509.CertificateBuilder()
                .subject_name(subject)
                .issuer_name(issuer)
                .public_key(private_key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(datetime.datetime.utcnow())
                .not_valid_after(
                    datetime.datetime.utcnow() + datetime.timedelta(days=365)
                )
                .add_extension(
                    x509.SubjectAlternativeName([x509.DNSName(hostname)]),
                    critical=False,
                )
                .sign(private_key, hashes.SHA256())
            )

            # Write private key
            with open(key_file, "wb") as f:
                f.write(
                    private_key.private_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PrivateFormat.TraditionalOpenSSL,
                        encryption_algorithm=serialization.NoEncryption(),
                    )
                )

            # Write certificate
            with open(cert_file, "wb") as f:
                f.write(cert.public_bytes(serialization.Encoding.PEM))

            self.cert_file = cert_file
            self.key_file = key_file

            log.info(f"Self-signed certificate created: {cert_file}")

        except ImportError:
            log.error(
                "cryptography library not installed. Cannot create self-signed certificate."
            )
            log.error("Install with: pip install cryptography")
            raise

    def get_ssl_context(self) -> Optional[ssl.SSLContext]:
        """
        Get SSL context for HTTPS.

        Returns:
            SSL context or None if SSL not configured
        """
        if not self.cert_file or not self.key_file:
            return None

        if self._context is None:
            self._context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self._context.load_cert_chain(self.cert_file, self.key_file)
            log.info("SSL context created")

        return self._context


class Deduplicator:
    """Handles content-addressable storage and deduplication."""

    def __init__(self, manifest_mgr):
        """
        Initialize deduplicator.

        Args:
            manifest_mgr: ManifestManager instance
        """
        self.manifest_mgr = manifest_mgr
        self._content_hashes: Dict[str, List[str]] = {}  # hash -> [file_paths]
        self._initialized = False

    def initialize(self):
        """Build content hash index from manifests."""
        if self._initialized:
            return

        log.info("Building deduplication index...")

        manifests = self.manifest_mgr.list_manifests("/", recursive=True)
        for manifest in manifests:
            file_path = manifest.get("file_path")
            content_hash = manifest.get("content_hash")

            if content_hash:
                if content_hash not in self._content_hashes:
                    self._content_hashes[content_hash] = []
                self._content_hashes[content_hash].append(file_path)

        log.info(f"  Indexed {len(self._content_hashes)} unique content hashes")
        self._initialized = True

    def compute_file_hash(self, file_path: str) -> str:
        """
        Compute SHA256 hash of a file.

        Args:
            file_path: Path to file

        Returns:
            Hex digest of file hash
        """
        sha256 = hashlib.sha256()

        with open(file_path, "rb") as f:
            while True:
                data = f.read(65536)  # 64KB chunks
                if not data:
                    break
                sha256.update(data)

        return sha256.hexdigest()

    def find_duplicate(self, content_hash: str) -> Optional[str]:
        """
        Find existing file with same content hash.

        Args:
            content_hash: Content hash to search for

        Returns:
            File path of duplicate if found, None otherwise
        """
        self.initialize()

        files = self._content_hashes.get(content_hash, [])
        if files:
            log.info(f"Duplicate content found: {len(files)} existing file(s)")
            return files[0]

        return None

    def add_file_hash(self, file_path: str, content_hash: str):
        """
        Add a file's content hash to the index.

        Args:
            file_path: Remote file path
            content_hash: Content hash
        """
        if content_hash not in self._content_hashes:
            self._content_hashes[content_hash] = []

        if file_path not in self._content_hashes[content_hash]:
            self._content_hashes[content_hash].append(file_path)

    def remove_file_hash(self, file_path: str, content_hash: str):
        """
        Remove a file's content hash from the index.

        Args:
            file_path: Remote file path
            content_hash: Content hash
        """
        if content_hash in self._content_hashes:
            if file_path in self._content_hashes[content_hash]:
                self._content_hashes[content_hash].remove(file_path)

            if not self._content_hashes[content_hash]:
                del self._content_hashes[content_hash]

    def get_stats(self) -> dict:
        """Get deduplication statistics."""
        self.initialize()

        total_files = sum(len(files) for files in self._content_hashes.values())
        unique_contents = len(self._content_hashes)
        duplicate_files = total_files - unique_contents

        return {
            "total_files": total_files,
            "unique_contents": unique_contents,
            "duplicate_files": duplicate_files,
            "dedup_ratio": (duplicate_files / total_files * 100)
            if total_files > 0
            else 0,
        }


class Compressor:
    """Handles compression before encryption."""

    def __init__(self, compression_level: int = 3):
        """
        Initialize compressor.

        Args:
            compression_level: Compression level (1-22 for zstd)
        """
        self.compression_level = compression_level
        self._zstd_available = False

        try:
            import zstandard

            self._zstd_available = True
            self._compressor = zstandard.ZstdCompressor(level=compression_level)
            self._decompressor = zstandard.ZstdDecompressor()
            log.info(f"Zstandard compression enabled (level {compression_level})")
        except ImportError:
            log.warning("zstandard library not installed. Compression disabled.")
            log.warning("Install with: pip install zstandard")

    def compress(self, data: bytes) -> Tuple[bytes, bool]:
        """
        Compress data.

        Args:
            data: Data to compress

        Returns:
            Tuple of (compressed_data, was_compressed)
        """
        if not self._zstd_available:
            return (data, False)

        try:
            compressed = self._compressor.compress(data)

            # Only use compression if it actually reduces size
            if len(compressed) < len(data):
                log.debug(
                    f"Compressed {len(data)} -> {len(compressed)} bytes "
                    f"({len(compressed) / len(data) * 100:.1f}%)"
                )
                return (compressed, True)
            else:
                log.debug("Compression didn't reduce size, using original")
                return (data, False)

        except Exception as e:
            log.warning(f"Compression failed: {e}")
            return (data, False)

    def decompress(self, data: bytes) -> bytes:
        """
        Decompress data.

        Args:
            data: Compressed data

        Returns:
            Decompressed data
        """
        if not self._zstd_available:
            return data

        try:
            return self._decompressor.decompress(data)
        except Exception as e:
            log.error(f"Decompression failed: {e}")
            raise


class BandwidthThrottler:
    """Throttles bandwidth for uploads/downloads."""

    def __init__(self, max_upload_mbps: float = 0, max_download_mbps: float = 0):
        """
        Initialize bandwidth throttler.

        Args:
            max_upload_mbps: Max upload speed in MB/s (0 = unlimited)
            max_download_mbps: Max download speed in MB/s (0 = unlimited)
        """
        self.max_upload_bps = max_upload_mbps * 1024 * 1024
        self.max_download_bps = max_download_mbps * 1024 * 1024

        self._upload_tokens = 0.0
        self._download_tokens = 0.0
        self._last_upload_time = time.time()
        self._last_download_time = time.time()
        self._lock = threading.Lock()

    def throttle_upload(self, bytes_count: int):
        """
        Throttle upload operation.

        Args:
            bytes_count: Number of bytes being uploaded
        """
        if self.max_upload_bps <= 0:
            return

        with self._lock:
            now = time.time()
            elapsed = now - self._last_upload_time
            self._last_upload_time = now

            # Add tokens based on elapsed time
            self._upload_tokens += elapsed * self.max_upload_bps

            # Cap tokens at 2 seconds worth
            max_tokens = self.max_upload_bps * 2
            self._upload_tokens = min(self._upload_tokens, max_tokens)

            # Consume tokens
            self._upload_tokens -= bytes_count

            # If we're out of tokens, sleep
            if self._upload_tokens < 0:
                sleep_time = abs(self._upload_tokens) / self.max_upload_bps
                time.sleep(sleep_time)
                self._upload_tokens = 0

    def throttle_download(self, bytes_count: int):
        """
        Throttle download operation.

        Args:
            bytes_count: Number of bytes being downloaded
        """
        if self.max_download_bps <= 0:
            return

        with self._lock:
            now = time.time()
            elapsed = now - self._last_download_time
            self._last_download_time = now

            # Add tokens based on elapsed time
            self._download_tokens += elapsed * self.max_download_bps

            # Cap tokens at 2 seconds worth
            max_tokens = self.max_download_bps * 2
            self._download_tokens = min(self._download_tokens, max_tokens)

            # Consume tokens
            self._download_tokens -= bytes_count

            # If we're out of tokens, sleep
            if self._download_tokens < 0:
                sleep_time = abs(self._download_tokens) / self.max_download_bps
                time.sleep(sleep_time)
                self._download_tokens = 0


class WebUIManager:
    """Manages web UI dashboard."""

    def __init__(self, pool):
        """
        Initialize web UI manager.

        Args:
            pool: RclonePool instance
        """
        self.pool = pool

    def get_dashboard_html(self) -> str:
        """
        Generate dashboard HTML.

        Returns:
            HTML string
        """
        # Get statistics
        usage_report = self.pool.balancer.get_usage_report()
        manifests = self.pool.manifest_mgr.list_manifests("/", recursive=True)

        total_files = len(manifests)
        total_size = sum(m.get("file_size", 0) for m in manifests)
        total_chunks = sum(m.get("chunk_count", 0) for m in manifests)

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>rclonepool Dashboard</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            margin: 0;
            padding: 20px;
            background: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        h1 {{
            color: #333;
        }}
        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }}
        .stat-card {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .stat-value {{
            font-size: 32px;
            font-weight: bold;
            color: #2196F3;
        }}
        .stat-label {{
            color: #666;
            margin-top: 5px;
        }}
        .remote-list {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin: 20px 0;
        }}
        .remote-item {{
            padding: 15px;
            border-bottom: 1px solid #eee;
        }}
        .remote-item:last-child {{
            border-bottom: none;
        }}
        .progress-bar {{
            height: 20px;
            background: #e0e0e0;
            border-radius: 10px;
            overflow: hidden;
            margin: 10px 0;
        }}
        .progress-fill {{
            height: 100%;
            background: linear-gradient(90deg, #2196F3, #21CBF3);
            transition: width 0.3s;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🗄️ rclonepool Dashboard</h1>

        <div class="stats">
            <div class="stat-card">
                <div class="stat-value">{total_files}</div>
                <div class="stat-label">Total Files</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{total_size / (1024**3):.2f} GB</div>
                <div class="stat-label">Total Size</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{total_chunks}</div>
                <div class="stat-label">Total Chunks</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{len(usage_report)}</div>
                <div class="stat-label">Remotes</div>
            </div>
        </div>

        <div class="remote-list">
            <h2>Remote Storage</h2>
"""

        for remote, info in usage_report.items():
            used_gb = info["used"] / (1024**3)
            total_gb = info["total"] / (1024**3)
            percent = info["percent"]

            html += f"""
            <div class="remote-item">
                <strong>{remote}</strong>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: {percent}%"></div>
                </div>
                <div>{used_gb:.2f} GB / {total_gb:.2f} GB ({percent:.1f}%)</div>
            </div>
"""

        html += """
        </div>
    </div>
</body>
</html>
"""
        return html
