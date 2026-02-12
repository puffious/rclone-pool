# rclonepool

Distribute files as encrypted chunks across multiple rclone remotes, presenting them as a single unified storage pool.

---

## Features

- **Chunk & distribute** — Files are split into configurable chunks (default 100MB) and distributed across remotes using least-used-first balancing
- **Encryption** — rclone crypt layer on each remote — your cloud provider sees nothing
- **WebDAV server** — Exposes the pool as a WebDAV endpoint compatible with rclone, enabling `rclone mount`, `rclone copy`, `rclone ls`, etc.
- **Video streaming** — Full Range request support for seeking in video files
- **No local state** — Manifests are stored on all remotes — rebuild from scratch anytime
- **SSD-friendly** — Uses `/dev/shm` (RAM) for temp files, zero unnecessary disk writes
- **No external Python dependencies** — Pure stdlib

---

## Architecture

```text
Your files
    │
    ▼
┌─────────────────────────────┐
│  rclonepool (Python)        │
│  ┌────────┐ ┌────────────┐  │
│  │Chunker │ │ Balancer   │  │
│  │100MB   │ │ least-used │  │
│  └────────┘ └────────────┘  │
│  ┌────────────────────────┐ │
│  │ Manifest (JSON on all) │ │
│  └────────────────────────┘ │
├─────────────────────────────┤
│  WebDAV server (:8080)      │
│  → rclone mount/copy/ls    │
├──────┬──────┬──────┬────────┤
│crypt1│crypt2│crypt3│crypt4/5│  ← rclone crypt
├──────┼──────┼──────┼────────┤
│mega1 │mega2 │mega3 │mega4/5 │  ← raw remotes
└──────┴──────┴──────┴────────┘
```

---

## Quick Start

### 1. Install rclone and configure remotes

```bash
# Install rclone
curl https://rclone.org/install.sh | sudo bash

# Configure MEGA remotes
rclone config create mega1 mega user user1@example.com pass $(rclone obscure 'password1')
rclone config create mega2 mega user user2@example.com pass $(rclone obscure 'password2')
rclone config create mega3 mega user user3@example.com pass $(rclone obscure 'password3')
rclone config create mega4 mega user user4@example.com pass $(rclone obscure 'password4')
rclone config create mega5 mega user user5@example.com pass $(rclone obscure 'password5')
```

### 2. Set up encryption (optional but recommended)

```bash
# Create crypt wrappers (use the SAME password for all)
PASS=$(rclone obscure 'your-encryption-password')
SALT=$(rclone obscure 'your-salt-password')

rclone config create crypt-mega1 crypt remote=mega1:encrypted password=$PASS password2=$SALT
rclone config create crypt-mega2 crypt remote=mega2:encrypted password=$PASS password2=$SALT
rclone config create crypt-mega3 crypt remote=mega3:encrypted password=$PASS password2=$SALT
rclone config create crypt-mega4 crypt remote=mega4:encrypted password=$PASS password2=$SALT
rclone config create crypt-mega5 crypt remote=mega5:encrypted password=$PASS password2=$SALT
```

### 3. Initialize rclonepool

```bash
python rclonepool.py init
```

This creates `~/.config/rclonepool/config.json`:

```json
{
  "remotes": ["mega1:", "mega2:", "mega3:", "mega4:", "mega5:"],
  "chunk_size": 104857600,
  "data_prefix": "rclonepool_data",
  "manifest_prefix": "rclonepool_manifests",
  "use_crypt": true,
  "crypt_remotes": ["crypt-mega1:", "crypt-mega2:", "crypt-mega3:", "crypt-mega4:", "crypt-mega5:"],
  "temp_dir": "/dev/shm/rclonepool",
  "rclone_binary": "rclone",
  "rclone_flags": ["--fast-list", "--no-traverse"]
}
```

### 4. Upload files

```bash
# Upload a single file
python rclonepool.py upload ./movie.mkv /movies/movie.mkv
```

Example output:

```text
Uploading ./movie.mkv (2147483648 bytes) -> /movies/movie.mkv
Chunking into 100MB pieces...
Chunk 0: 104857600 bytes -> crypt-mega3:
Chunk 1: 104857600 bytes -> crypt-mega1:
Chunk 2: 104857600 bytes -> crypt-mega5:
...
✓ Upload complete: 21 chunks across remotes
```

### 5. Start WebDAV server

```bash
python rclonepool.py serve --port 8080
```

### 6. Add as rclone remote

Add this to `~/.config/rclone/rclone.conf`:

```ini
[rclonepool]
type = webdav
url = http://localhost:8080
vendor = other
```

### 7. Use with rclone!

```bash
# List files
rclone ls rclonepool:

# Mount as filesystem
rclone mount rclonepool: /mnt/pool --vfs-cache-mode full

# Copy files from pool
rclone copy rclonepool:/movies/movie.mkv ./

# Copy files TO pool (uploads via WebDAV → chunks → distributes)
rclone copy ./newfile.mkv rclonepool:/movies/

# Stream video
mpv http://localhost:8080/movies/movie.mkv
# OR after mounting:
mpv /mnt/pool/movies/movie.mkv

# Serve over DLNA/HTTP
rclone serve http rclonepool: --addr :9090
```

---

## CLI Reference

| Command | Description |
|---|---|
| `rclonepool init` | Interactive setup |
| `rclonepool upload <local> <remote_path>` | Upload and distribute a file |
| `rclonepool download <remote_path> <local>` | Download and reassemble a file |
| `rclonepool ls [directory]` | List files |
| `rclonepool delete <remote_path>` | Delete a file and all chunks |
| `rclonepool status` | Show remote usage |
| `rclonepool serve [--host HOST] [--port PORT]` | Start WebDAV server |

---

## How It Works

### Upload Flow

1. File is read in 100MB streaming chunks (only 100MB in RAM at a time)
2. For each chunk, the **balancer** picks the remote with least used space
3. Chunk is written to tmpfs (`/dev/shm`), uploaded via rclone, then deleted from tmpfs
4. A **manifest** (JSON) is created listing all chunks and their locations
5. Manifest is saved to **every remote** for redundancy

### Download Flow

1. Manifest is loaded (from cache or any remote)
2. Chunks are fetched in order and written/streamed sequentially

### Video Streaming Flow

1. Player sends HTTP Range request (e.g., `bytes=500000000-500100000`)
2. WebDAV server calculates which chunk(s) contain that range
3. Only the needed chunk(s) are fetched via `rclone cat --offset --count`
4. Byte range is returned to the player

### Manifest Example

```json
{
  "version": 1,
  "file_name": "movie.mkv",
  "remote_dir": "/movies",
  "file_path": "/movies/movie.mkv",
  "file_size": 2147483648,
  "chunk_size": 104857600,
  "chunk_count": 21,
  "chunks": [
    {
      "index": 0,
      "remote": "crypt-mega3:",
      "path": "rclonepool_data/movie.mkv.chunk.000",
      "size": 104857600,
      "offset": 0
    },
    {
      "index": 1,
      "remote": "crypt-mega1:",
      "path": "rclonepool_data/movie.mkv.chunk.001",
      "size": 104857600,
      "offset": 104857600
    }
  ],
  "created_at": 1700000000.0,
  "checksum": "a1b2c3d4e5f6g7h8"
}
```

---

## Configuration Options

| Key | Default | Description |
|---|---|---|
| `remotes` | `[]` | Base rclone remote names |
| `crypt_remotes` | `[]` | Crypt-wrapped remote names |
| `use_crypt` | `true` | Use crypt remotes if available |
| `chunk_size` | `104857600` | Chunk size in bytes (100MB) |
| `data_prefix` | `rclonepool_data` | Remote folder for chunks |
| `manifest_prefix` | `rclonepool_manifests` | Remote folder for manifests |
| `temp_dir` | `/dev/shm/rclonepool` | Temp dir (use RAM-backed fs!) |
| `rclone_binary` | `rclone` | Path to rclone binary |
| `rclone_flags` | `["--fast-list"]` | Extra rclone flags |

---

## Limitations and Future Work

- **No deduplication yet** — same file uploaded twice creates double chunks
- **No parity/redundancy** — losing a remote means losing those chunks
  - *Planned: Reed-Solomon parity chunks*
- **No concurrent uploads yet** — chunks upload sequentially
  - *Planned: async/threaded chunk uploads*
- **Rebalancing** is not yet implemented
  - *Planned: `rclonepool rebalance` command*
- Works with **any** rclone remote, not just MEGA

---

## rclone-only Approach (Quick and Dirty)

If you just want something working with zero code, add this to your `rclone.conf`:

```ini
[mega1]
type = mega
user = user1@example.com
pass = <encrypted_pass>

[mega2]
type = mega
user = user2@example.com
pass = <encrypted_pass>

# ... repeat for mega3, mega4, mega5 ...

[crypt-mega1]
type = crypt
remote = mega1:encrypted
password = <your_crypt_password>
password2 = <your_crypt_salt>

[crypt-mega2]
type = crypt
remote = mega2:encrypted
password = <your_crypt_password>
password2 = <your_crypt_salt>

# ... repeat for crypt-mega3, crypt-mega4, crypt-mega5 ...

[mega-union]
type = union
upstreams = crypt-mega1: crypt-mega2: crypt-mega3: crypt-mega4: crypt-mega5:
action_policy = epff
create_policy = epmfs
search_policy = ff

[mega-pool]
type = chunker
remote = mega-union:
chunk_size = 100M
hash_type = none
name_format = *.rclone_chunk.###
fail_hard = true
```

**Limitations of this approach:**

| Feature | Status |
|---|---|
| Files split into 100MB chunks | ✅ Works |
| Encryption | ✅ Works |
| Chunks balanced across remotes | ❌ All chunks of one file go to same remote |
| Files larger than 20GB (single remote size) | ❌ Fails |
| Rebalancing | ❌ Not possible |
| Video streaming/seeking | ⚠️ Works via `rclone mount` but no chunk-level seeking |

This is why the full `rclonepool` solution exists.

---

## Project Structure

```text
rclonepool/
├── rclonepool.py          # Main entry point & CLI
├── config.py              # Configuration management
├── chunker.py             # File splitting & reassembly (in RAM)
├── balancer.py            # Decides which remote gets which chunk
├── manifest.py            # Metadata tracking (JSON manifests)
├── webdav_server.py       # WebDAV interface for rclone compatibility
├── rclone_backend.py      # Wrapper around rclone CLI calls
├── requirements.txt       # (empty — pure stdlib)
└── README.md
```

---

## License

MIT
```

This version avoids nested triple-backtick issues, uses `text` language hints for ASCII diagrams, separates code output examples from bash commands, and uses proper heading hierarchy and table formatting that renders cleanly in OpenWebUI's markdown renderer.