# rclonepool - Complete Feature Documentation

**Version:** 1.0.0  
**Status:** Production Ready  
**License:** MIT

## Overview

rclonepool is a unified chunked encrypted storage pool system that distributes files across multiple rclone remotes. This document provides a comprehensive overview of all features from v0.1 (base functionality) through v1.0 (production ready).

---

## Table of Contents

- [Version History](#version-history)
- [v0.1 - Base Functionality](#v01---base-functionality)
- [v0.2 - Robustness](#v02---robustness)
- [v0.3 - Performance](#v03---performance)
- [v0.4 - Balancing](#v04---balancing)
- [v0.5 - Redundancy](#v05---redundancy)
- [v0.6 - Advanced Features](#v06---advanced-features)
- [v1.0 - Production Ready](#v10---production-ready)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Configuration Reference](#configuration-reference)
- [API Documentation](#api-documentation)
- [Plugin Development](#plugin-development)

---

## Version History

| Version | Release | Status | Key Features |
|---------|---------|--------|--------------|
| v0.1 | Base | ✅ Complete | Core chunking, upload/download, WebDAV |
| v0.2 | Robustness | ✅ Complete | Retry logic, verification, repair, caching |
| v0.3 | Performance | ✅ Complete | Parallel operations, progress bars, prefetching |
| v0.4 | Balancing | ✅ Complete | Multiple strategies, rebalancing, weights |
| v0.5 | Redundancy | ✅ Complete | Reed-Solomon parity, replication, health monitoring |
| v0.6 | Advanced | ✅ Complete | Auth, HTTPS, deduplication, compression, Web UI |
| v1.0 | Production | ✅ Complete | REST API, WebSocket, plugins, multi-user |

---

## v0.1 - Base Functionality

### Core Features

#### File Chunking
- Split large files into fixed-size chunks (default: 100MB)
- Stream-based processing for minimal memory usage
- Support for files larger than any single remote's capacity

#### Upload/Download
```bash
# Upload a file
rclonepool upload /path/to/file.mkv /backups/file.mkv

# Download a file
rclonepool download /backups/file.mkv /path/to/local.mkv

# List files
rclonepool ls /backups

# Delete a file
rclonepool delete /backups/file.mkv
```

#### Chunk Distribution
- Least-used-first balancing strategy
- Automatic distribution across all configured remotes
- Manifest-based tracking (JSON metadata)

#### WebDAV Server
```bash
# Start WebDAV server
rclonepool serve --host 0.0.0.0 --port 8080

# Access via rclone
rclone ls rclonepool:
rclone mount rclonepool: /mnt/pool
```

**Features:**
- HTTP Range request support (video streaming with seeking)
- PROPFIND for directory listing
- PUT/GET/DELETE operations
- Compatible with any WebDAV client

#### Encryption
- Delegates to rclone crypt (NaCl secretbox)
- Encrypts both filenames and contents
- No local state required - everything on remotes

#### Manifest System
- JSON manifests stored on ALL remotes for redundancy
- Contains chunk locations, sizes, offsets
- Enables pool reconstruction from remotes alone

---

## v0.2 - Robustness

### Retry Logic with Exponential Backoff

```python
# Automatic retry for failed operations
from retry import retry_with_backoff, RetryConfig

@retry_with_backoff(RetryConfig(max_retries=5, base_delay=1.0))
def upload_chunk(data, remote, path):
    return backend.upload_bytes(data, remote, path)
```

**Configuration:**
```json
{
  "enable_retry": true,
  "max_retries": 3,
  "retry_delay": 1.0
}
```

### Verification

```bash
# Verify a single file
rclonepool verify /backups/file.mkv

# Verify all files
rclonepool verify

# Quick check (existence only)
rclonepool verify --quick
```

**Features:**
- Check all chunks exist
- Verify chunk sizes match manifest
- Identify missing or corrupted chunks
- Detailed verification reports

### Repair

```bash
# Repair missing chunks from local copy
rclonepool repair /backups/file.mkv /path/to/local/source.mkv
```

**Features:**
- Re-upload missing chunks
- Automatic manifest update
- Verification after repair

### Orphan Detection

```bash
# Find orphaned chunks
rclonepool orphans

# Delete orphaned chunks
rclonepool orphans --delete
```

**Features:**
- Identify chunks without manifest references
- Safe deletion with confirmation
- Reclaim storage space

### Persistent Manifest Cache

```python
from cache import ManifestCache

cache = ManifestCache()
manifest = cache.get("/backups/file.mkv")
```

**Features:**
- Disk-based caching for fast access
- Reduces remote API calls
- Automatic persistence across restarts

**Configuration:**
```json
{
  "enable_manifest_cache": true,
  "manifest_cache_dir": "~/.cache/rclonepool"
}
```

### Duplicate File Detection

```bash
# Upload with deduplication check
rclonepool upload file.mkv /backups/file.mkv
```

**Features:**
- Check for existing files before upload
- Compare by name and size
- Optional content hash comparison

---

## v0.3 - Performance

### Parallel Chunk Operations

```bash
# Parallel upload
rclonepool upload --parallel file.mkv /backups/file.mkv

# Parallel download
rclonepool download --parallel /backups/file.mkv local.mkv
```

**Configuration:**
```json
{
  "parallel_uploads": true,
  "parallel_downloads": true,
  "max_parallel_workers": 4
}
```

**Features:**
- Configurable worker thread count
- Automatic error handling per chunk
- Progress tracking across all workers

### Progress Bars

```bash
# Upload with progress bar
rclonepool upload large_file.mkv /backups/large_file.mkv
```

**Output:**
```
████████████████████████████████████████ 100.0% | 1024.0/1024.0 MB | 12.34 MB/s | ETA: 00:00:00 | Elapsed: 00:01:23 | 10/10 items
```

**Features:**
- Real-time progress display
- Speed calculation (MB/s)
- ETA estimation
- Elapsed time tracking

### Chunk LRU Cache

```python
from cache import ChunkCache

chunk_cache = ChunkCache(max_size_mb=500)
data = chunk_cache.get("chunk_key")
```

**Features:**
- RAM-backed cache in `/dev/shm`
- LRU eviction policy
- Configurable size limit
- Improves streaming performance

**Configuration:**
```json
{
  "enable_chunk_cache": true,
  "chunk_cache_size_mb": 500
}
```

### Prefetching

```python
from performance import ChunkPrefetcher

prefetcher = ChunkPrefetcher(backend, cache, prefetch_count=2)
prefetcher.start()
```

**Features:**
- Prefetch next N chunks during sequential reads
- Background worker thread
- Improves video streaming experience

**Configuration:**
```json
{
  "enable_prefetch": true,
  "prefetch_chunks": 2
}
```

### rclone Daemon Mode

```python
from performance import RcloneDaemon

daemon = RcloneDaemon(config, port=5572)
daemon.start()
```

**Features:**
- Connection pooling via `rclone rcd`
- Reduced overhead for multiple operations
- Persistent connections to remotes

**Configuration:**
```json
{
  "enable_rclone_daemon": false,
  "rclone_daemon_port": 5572
}
```

---

## v0.4 - Balancing

### Multiple Balancing Strategies

```bash
# Set balancing strategy in config
{
  "balancing_strategy": "round_robin_least_used"
}
```

**Available Strategies:**

1. **least_used** (default)
   - Select remote with least used space
   - Naturally balances over time

2. **round_robin**
   - Cycle through remotes in order
   - Simple and predictable

3. **weighted**
   - Assign weights to remotes
   - Prefer faster/more reliable remotes

4. **random**
   - Random selection
   - Good for load distribution

5. **round_robin_least_used**
   - Round-robin with least-used tiebreaker
   - Switches to least-used if variance > 10%

### Remote Weights and Priorities

```json
{
  "remote_weights": {
    "fast_remote:": 2.0,
    "slow_remote:": 0.5
  },
  "remote_priorities": {
    "premium_remote:": 10,
    "free_remote:": 5
  }
}
```

**Features:**
- Weight: Higher = more likely to be selected
- Priority: Higher priority remotes preferred first
- Combine with any balancing strategy

### Rebalancing

```bash
# Analyze current balance
rclonepool balance-status

# Rebalance (dry run)
rclonepool rebalance --dry-run

# Rebalance for real
rclonepool rebalance --target-variance 5.0
```

**Features:**
- Move chunks between remotes
- Target utilization variance
- Dry-run mode for safety
- Automatic manifest updates

**Configuration:**
```json
{
  "auto_rebalance": false,
  "rebalance_threshold": 10.0
}
```

### Auto-Rebalance

**Features:**
- Trigger rebalancing when variance exceeds threshold
- Runs automatically when new remote added
- Configurable threshold

---

## v0.5 - Redundancy

### Redundancy Modes

```json
{
  "redundancy_mode": "parity",
  "replication_factor": 2,
  "parity_data_shards": 3,
  "parity_parity_shards": 1
}
```

**Modes:**

1. **none** - No redundancy (default)
2. **replication** - Store each chunk on N remotes
3. **parity** - Reed-Solomon erasure coding
4. **hybrid** - Both replication and parity

### Reed-Solomon Parity

```python
from redundancy import RedundancyManager, RedundancyMode

redundancy_mgr = RedundancyManager(config, backend, manifest_mgr)
redundancy_mgr.set_mode(RedundancyMode.PARITY)
redundancy_mgr.set_parity_config(data_shards=3, parity_shards=1)
```

**Features:**
- Configurable data/parity shard ratio
- Can lose up to N parity shards
- Automatic parity chunk generation
- Efficient storage overhead

**Example:** 3 data + 1 parity = can lose 1 chunk

### Replication

```python
redundancy_mgr.set_mode(RedundancyMode.REPLICATION)
redundancy_mgr.set_replication_factor(3)
```

**Features:**
- Store each chunk on multiple remotes
- Simple and reliable
- Higher storage overhead than parity

### Health Monitoring

```bash
# Check health of a file
rclonepool health /backups/file.mkv

# Check health of all files
rclonepool health
```

**Features:**
- Check chunk availability
- Verify replication factor
- Identify degraded files
- Determine if file is recoverable

**Configuration:**
```json
{
  "enable_health_monitoring": true,
  "health_check_interval": 3600
}
```

### Rebuild

```bash
# Rebuild file from redundancy
rclonepool rebuild /backups/file.mkv
```

**Features:**
- Reconstruct missing chunks from parity
- Restore from replicas
- Automatic verification after rebuild

---

## v0.6 - Advanced Features

### WebDAV Authentication

```json
{
  "webdav_auth_method": "basic",
  "webdav_users": {
    "admin": "hashed_password"
  }
}
```

**Methods:**
- **none** - No authentication
- **basic** - HTTP Basic Auth
- **api_key** - API key in header
- **bearer** - Bearer token

```bash
# Start with authentication
rclonepool serve --auth basic
```

### HTTPS Support

```json
{
  "enable_https": true,
  "ssl_cert_file": "/path/to/cert.pem",
  "ssl_key_file": "/path/to/key.pem"
}
```

```bash
# Start with HTTPS
rclonepool serve --https
```

**Features:**
- Self-signed certificate generation
- Custom certificate support
- Automatic SSL context management

### Deduplication

```json
{
  "enable_deduplication": true
}
```

**Features:**
- Content-addressable storage
- SHA256 hash-based deduplication
- Automatic duplicate detection on upload
- Storage space savings

```python
from advanced_features import Deduplicator

dedup = Deduplicator(manifest_mgr)
duplicate = dedup.find_duplicate(content_hash)
```

### Compression

```json
{
  "enable_compression": true,
  "compression_level": 3
}
```

**Features:**
- Zstandard (zstd) compression
- Configurable compression level (1-22)
- Compress before encryption
- Only use if reduces size

**Requirements:**
```bash
pip install zstandard
```

### Bandwidth Throttling

```json
{
  "bandwidth_limit_upload_mbps": 10.0,
  "bandwidth_limit_download_mbps": 20.0
}
```

**Features:**
- Token bucket algorithm
- Per-operation throttling
- Configurable upload/download limits
- 0 = unlimited

### Web UI Dashboard

```bash
# Access at http://localhost:8080/
rclonepool serve --host 0.0.0.0 --port 8080
```

**Features:**
- Real-time statistics
- Storage usage visualization
- File browser
- Remote status monitoring
- Responsive design

### Docker Support

```bash
# Build image
docker build -t rclonepool .

# Run container
docker-compose up -d
```

**Features:**
- Pre-configured Docker image
- Docker Compose support
- Volume mounts for config
- Health checks

### Systemd Service

```bash
# Install service
sudo cp rclonepool.service /etc/systemd/system/rclonepool@.service
sudo systemctl enable rclonepool@username
sudo systemctl start rclonepool@username
```

**Features:**
- Auto-start on boot
- Automatic restart on failure
- Resource limits
- Security hardening

---

## v1.0 - Production Ready

### REST API

```bash
# Start API server
rclonepool api --host 0.0.0.0 --port 8081
```

**Endpoints:**

```bash
# Status
GET /api/v1/status

# List files
GET /api/v1/files?dir=/backups&recursive=true

# Get file metadata
GET /api/v1/files/{path}

# Upload file
POST /api/v1/files
{
  "local_path": "/path/to/file",
  "remote_path": "/backups/file"
}

# Delete file
DELETE /api/v1/files/{path}

# List remotes
GET /api/v1/remotes

# Statistics
GET /api/v1/stats

# Health check
GET /api/v1/health

# Verify file
POST /api/v1/verify
{
  "file_path": "/backups/file.mkv"
}

# Repair file
POST /api/v1/repair
{
  "file_path": "/backups/file.mkv",
  "local_source": "/path/to/source.mkv"
}

# Rebalance
POST /api/v1/rebalance
{
  "dry_run": false
}

# API documentation
GET /api/v1/docs
```

**Authentication:**
```bash
# Basic Auth
curl -u username:password http://localhost:8081/api/v1/status

# API Key
curl -H "X-API-Key: your_api_key" http://localhost:8081/api/v1/status

# Bearer Token
curl -H "Authorization: Bearer your_token" http://localhost:8081/api/v1/status
```

### WebSocket Support

```javascript
// Connect to WebSocket
const ws = new WebSocket('ws://localhost:8081/ws');

// Subscribe to events
ws.send(JSON.stringify({
  action: 'subscribe',
  topic: 'upload_progress'
}));

// Receive events
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Event:', data);
};
```

**Topics:**
- `upload_progress` - Upload progress updates
- `download_progress` - Download progress updates
- `verification` - Verification results
- `health` - Health check results
- `rebalance` - Rebalancing progress

### Plugin System

```bash
# List plugins
rclonepool plugins list

# Enable plugin
rclonepool plugins enable balancer:custom_balancer

# Disable plugin
rclonepool plugins disable balancer:custom_balancer

# Load plugin
rclonepool plugins load /path/to/plugin.py
```

**Plugin Types:**
- **balancer** - Custom balancing strategies
- **chunker** - Custom chunking strategies
- **storage_backend** - Custom storage backends
- **compression** - Custom compression algorithms
- **encryption** - Custom encryption methods
- **event_handler** - Event hooks
- **transformer** - Data transformers

**Example Plugin:**

```python
from plugin_system import BalancerPlugin, PluginMetadata, PluginType

class CustomBalancerPlugin(BalancerPlugin):
    def get_metadata(self):
        return PluginMetadata(
            name="custom_balancer",
            version="1.0.0",
            author="Your Name",
            description="Custom balancing strategy",
            plugin_type=PluginType.BALANCER
        )
    
    def initialize(self, config):
        self.config = config
    
    def select_remote(self, remotes, chunk_size):
        # Your custom logic here
        return remotes[0]["name"]
```

**Plugin Hooks:**
- `PRE_UPLOAD` - Before upload
- `POST_UPLOAD` - After upload
- `PRE_DOWNLOAD` - Before download
- `POST_DOWNLOAD` - After download
- `PRE_DELETE` - Before delete
- `POST_DELETE` - After delete
- `FILE_VERIFIED` - After verification
- `FILE_REPAIRED` - After repair
- `CHUNK_MISSING` - When chunk is missing
- `REMOTE_ERROR` - On remote error

### Multi-User Support

```python
from api_server import APIServer

api_server = APIServer(host="0.0.0.0", port=8081)

# Register pools for different users
api_server.register_user_pool("user1", pool1)
api_server.register_user_pool("user2", pool2)

api_server.start()
```

**Features:**
- Isolated storage pools per user
- Per-user authentication
- Separate configurations
- Resource quotas

### Comprehensive Test Suite

```bash
# Run all tests
python test_all.py

# Run specific test
python -m unittest test_all.TestConfig

# Run with coverage
coverage run test_all.py
coverage report
```

**Test Coverage:**
- Unit tests for all modules
- Integration tests
- Performance benchmarks
- Security tests

### CI/CD Pipeline

**GitHub Actions:**
- Automated testing on push
- Multi-platform builds (Linux, macOS, Windows)
- Docker image publishing
- Release automation

### Metrics and Monitoring

```json
{
  "enable_metrics": true,
  "metrics_port": 9090
}
```

**Prometheus Metrics:**
- Upload/download rates
- Chunk distribution
- Remote utilization
- Error rates
- API request latency

---

## Installation

### Requirements

- Python 3.10+
- rclone (latest version)
- No external Python dependencies (stdlib only)

### Optional Dependencies

```bash
# For compression (v0.6)
pip install zstandard

# For HTTPS with self-signed certs (v0.6)
pip install cryptography

# For advanced features
pip install pyeclib  # Better Reed-Solomon implementation
```

### Install from Source

```bash
# Clone repository
git clone https://github.com/yourusername/rclonepool.git
cd rclonepool

# Install
sudo cp rclonepool.py /usr/local/bin/rclonepool
sudo chmod +x /usr/local/bin/rclonepool

# Or use directly
python rclonepool.py --help
```

### Docker Installation

```bash
# Pull image
docker pull rclonepool/rclonepool:latest

# Run
docker run -d \
  -v ~/.config/rclonepool:/config \
  -v /dev/shm:/dev/shm \
  -p 8080:8080 \
  -p 8081:8081 \
  rclonepool/rclonepool:latest
```

---

## Quick Start

### 1. Configure rclone

```bash
# Add your remotes
rclone config

# Example: Add MEGA remotes
rclone config create mega1 mega user=user1@example.com pass=obscured_password
rclone config create mega2 mega user=user2@example.com pass=obscured_password

# Add crypt remotes (for encryption)
rclone config create crypt-mega1 crypt remote=mega1:encrypted password=your_password
rclone config create crypt-mega2 crypt remote=mega2:encrypted password=your_password
```

### 2. Initialize rclonepool

```bash
rclonepool init
```

Follow the interactive prompts to configure remotes, encryption, chunk size, etc.

### 3. Upload Files

```bash
# Upload a file
rclonepool upload /path/to/movie.mkv /movies/movie.mkv

# Upload with parallel chunks (v0.3)
rclonepool upload --parallel /path/to/large_file.mkv /backups/large_file.mkv
```

### 4. Access via WebDAV

```bash
# Start WebDAV server
rclonepool serve --host 0.0.0.0 --port 8080

# Mount with rclone
rclone mount rclonepool: /mnt/pool --daemon

# Stream video
vlc http://localhost:8080/movies/movie.mkv
```

### 5. Verify and Maintain

```bash
# Verify all files
rclonepool verify

# Check health
rclonepool health

# Rebalance storage
rclonepool rebalance

# Find and clean orphans
rclonepool orphans --delete
```

---

## Configuration Reference

### Complete Configuration Example

```json
{
  "remotes": ["mega1:", "mega2:", "mega3:"],
  "chunk_size": 104857600,
  "data_prefix": "rclonepool_data",
  "manifest_prefix": "rclonepool_manifests",
  "use_crypt": true,
  "crypt_remotes": ["crypt-mega1:", "crypt-mega2:", "crypt-mega3:"],
  "temp_dir": "/dev/shm/rclonepool",
  "rclone_binary": "rclone",
  "rclone_flags": ["--fast-list", "--no-traverse"],
  "webdav_port": 8080,
  "webdav_host": "0.0.0.0",
  
  "enable_retry": true,
  "max_retries": 3,
  "retry_delay": 1.0,
  "enable_manifest_cache": true,
  "manifest_cache_dir": "~/.cache/rclonepool",
  "enable_duplicate_detection": true,
  
  "parallel_uploads": true,
  "parallel_downloads": true,
  "max_parallel_workers": 4,
  "enable_chunk_cache": true,
  "chunk_cache_size_mb": 500,
  "enable_prefetch": true,
  "prefetch_chunks": 2,
  "show_progress": true,
  
  "balancing_strategy": "round_robin_least_used",
  "remote_weights": {},
  "remote_priorities": {},
  "auto_rebalance": false,
  "rebalance_threshold": 10.0,
  
  "redundancy_mode": "parity",
  "replication_factor": 2,
  "parity_data_shards": 3,
  "parity_parity_shards": 1,
  "enable_health_monitoring": true,
  "health_check_interval": 3600,
  
  "enable_deduplication": true,
  "enable_compression": true,
  "compression_level": 3,
  "bandwidth_limit_upload_mbps": 0,
  "bandwidth_limit_download_mbps": 0,
  "webdav_auth_method": "api_key",
  "enable_https": true,
  "ssl_cert_file": "/path/to/cert.pem",
  "ssl_key_file": "/path/to/key.pem",
  "enable_webui": true,
  
  "enable_api_server": true,
  "api_server_host": "0.0.0.0",
  "api_server_port": 8081,
  "enable_plugins": true,
  "plugins_dir": "~/.config/rclonepool/plugins",
  "log_level": "INFO",
  "enable_metrics": true,
  "metrics_port": 9090
}
```

---

## API Documentation

See [API.md](API.md) for complete REST API documentation.

---

## Plugin Development

See [PLUGINS.md](PLUGINS.md) for plugin development guide.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines.

---

## License

MIT License - see [LICENSE](LICENSE) for details.

---

## Support

- **Documentation:** https://rclonepool.readthedocs.io
- **Issues:** https://github.com/yourusername/rclonepool/issues
- **Discussions:** https://github.com/yourusername/rclonepool/discussions
- **Discord:** https://discord.gg/rclonepool

---

## Acknowledgments

- rclone team for the excellent cloud storage tool
- Contributors and testers
- Open source community

---

**Made with ❤️ by the rclonepool team**