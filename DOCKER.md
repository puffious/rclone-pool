# Docker Usage for rclonepool

## Quick Start

### Using Docker Hub / GHCR Image

```bash
# Pull the latest image
docker pull ghcr.io/YOURUSERNAME/rclone-pool:latest

# Run the container
docker run -d \
  --name rclonepool \
  -p 8080:8080 \
  -v /path/to/your/config:/config:ro \
  ghcr.io/YOURUSERNAME/rclone-pool:latest
```

### Using Docker Compose

1. Create a `config` directory with your `rclone.conf` and `config.json`
2. Run:

```bash
docker-compose up -d
```

## Configuration

### Directory Structure

```
your-project/
├── docker-compose.yml
└── config/
    ├── rclone.conf       # Your rclone configuration
    └── config.json       # Your rclonepool configuration
```

### Example config.json for Docker

```json
{
  "remotes": ["crypt-mega1:", "crypt-mega2:", "crypt-mega3:"],
  "chunk_size": 104857600,
  "data_prefix": "rclonepool_data",
  "manifest_prefix": "rclonepool_manifests",
  "use_crypt": true,
  "crypt_remotes": ["crypt-mega1:", "crypt-mega2:", "crypt-mega3:"],
  "temp_dir": "/tmp/rclonepool",
  "rclone_binary": "rclone",
  "rclone_flags": ["--fast-list", "--no-traverse"],
  "webdav_port": 8080,
  "webdav_host": "0.0.0.0"
}
```

## Building Locally

```bash
# Build the image
docker build -t rclonepool:local .

# Run it
docker run -d \
  --name rclonepool \
  -p 8080:8080 \
  -v $(pwd)/config:/config:ro \
  rclonepool:local
```

## Docker Compose with Custom Settings

```yaml
version: '3.8'

services:
  rclonepool:
    image: ghcr.io/YOURUSERNAME/rclone-pool:latest
    container_name: rclonepool
    ports:
      - "8080:8080"
    volumes:
      - ./config:/config:ro
      - rclonepool-cache:/tmp/rclonepool
    environment:
      - RCLONE_CONFIG=/config/rclone.conf
      - RCLONEPOOL_CONFIG=/config/config.json
      - TZ=America/New_York
    restart: unless-stopped

volumes:
  rclonepool-cache:
```

## Health Check

The Docker image includes a health check that pings the WebDAV server every 30 seconds:

```bash
# Check container health
docker ps

# View health check logs
docker inspect --format='{{json .State.Health}}' rclonepool
```

## Accessing the WebDAV Server

Once running, access the server at:
- HTTP: `http://localhost:8080`
- Add as rclone remote:

```bash
rclone config create rcpool webdav url http://localhost:8080
```

## Logs

```bash
# View logs
docker logs rclonepool

# Follow logs
docker logs -f rclonepool
```

## Stopping and Removing

```bash
# Stop the container
docker stop rclonepool

# Remove the container
docker rm rclonepool

# Using docker-compose
docker-compose down
```

## Multi-Architecture Support

The Docker image is built for both `amd64` and `arm64` architectures, so it works on:
- x86_64 / AMD64 (Intel/AMD processors)
- ARM64 / aarch64 (Apple Silicon, Raspberry Pi 4+, ARM servers)

## Security Considerations

1. **Mount config as read-only**: Use `:ro` when mounting the config directory
2. **Network isolation**: Consider using Docker networks for isolation
3. **Reverse proxy**: Put behind nginx/traefik with TLS for external access
4. **Bind to localhost**: Change `webdav_host` to `127.0.0.1` if only local access needed

## Advanced: Custom Entrypoint

To run custom commands instead of the server:

```bash
docker run -it --rm \
  -v $(pwd)/config:/config:ro \
  ghcr.io/YOURUSERNAME/rclone-pool:latest \
  python rclonepool.py status
```

## Troubleshooting

### Container won't start
- Check logs: `docker logs rclonepool`
- Verify config files exist and are valid JSON
- Ensure rclone.conf has valid remote configurations

### Can't access WebDAV server
- Verify port mapping: `docker ps`
- Check firewall rules
- Ensure `webdav_host` is set to `0.0.0.0` in config.json

### Permission issues
- Ensure config files are readable
- Check Docker volume permissions
