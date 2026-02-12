# rclonepool — System Prompt / Project Bible

---

## 1. Project Identity

**Name:** rclonepool
**Tagline:** Unified chunked encrypted storage pool across multiple rclone remotes
**Author:** Human + AI collaborative design
**Language:** Python 3.10+ (stdlib only, zero external dependencies)
**License:** MIT
**Status:** v0.1.0 — functional prototype

---

## 2. Problem Statement

Cloud storage providers offer limited free tiers (e.g., MEGA gives 20GB per account). A user with multiple accounts across one or more providers wants to:

1. **Combine** all accounts into a single logical storage pool (e.g., 5 × 20GB = 100GB)
2. **Store files larger than any single account's capacity** (e.g., a 30GB file across 20GB accounts)
3. **Encrypt** everything so the cloud provider cannot read the data
4. **Stream** media files (video/audio) with seeking support
5. **Avoid local state** — the system should be rebuildable from the remotes alone
6. **Minimize local disk writes** — prefer RAM-backed temp storage
7. **Integrate with rclone** — the dominant tool for cloud storage management — so that existing rclone workflows (mount, copy, serve, sync) work transparently

No existing rclone feature combination solves this:

- `rclone union` pools remotes but does not split files across them
- `rclone chunker` splits files but stores all chunks on a single remote
- `union + chunker` does NOT distribute chunks — chunker treats union as one remote, and union picks ONE upstream for all chunks of a file
- There is no rclone backend that does chunk-level distribution with balancing

Therefore, a custom orchestration layer is needed.

---

## 3. Core Philosophy

### 3.1 Design Principles

1. **rclone is the transport layer, not the brain.** rclonepool uses rclone as a reliable, battle-tested tool for moving bytes to/from remotes. All intelligence (chunking, balancing, manifest tracking, reassembly) lives in rclonepool.

2. **No local state is required.** Everything needed to reconstruct the pool exists on the remotes themselves. If the local machine burns down, a fresh install of rclonepool + rclone with the same remote configs can reconstruct the entire file catalog by reading manifests from the remotes.

3. **Manifests are the source of truth.** Every file in the pool has a JSON manifest that describes its name, size, chunk layout, and which remote holds each chunk. Manifests are stored on ALL remotes for redundancy.

4. **Least-used-first balancing.** When uploading, each chunk goes to the remote with the most available space (or least used space). This naturally balances storage across remotes over time.

5. **Streaming-first for reads.** The system is designed so that video/audio files can be streamed with seeking. This means the WebDAV server supports HTTP Range requests, and the chunk layout allows fetching arbitrary byte ranges without downloading entire files.

6. **SSD-friendly.** Temp files are written to `/dev/shm` (RAM-backed tmpfs on Linux) or equivalent. The user's SSD sees zero unnecessary writes. Only the final rclone upload/download touches the network.

7. **Provider-agnostic.** Although the motivating use case is MEGA, rclonepool works with ANY rclone remote — Google Drive, Dropbox, S3, B2, SFTP, local paths, or any mix thereof.

8. **Encryption is a layer, not a feature.** rclonepool does not implement its own encryption. It delegates to rclone crypt, which is well-audited, uses NaCl secretbox (XSalsa20 + Poly1305), and encrypts both file names and contents. The user sets up crypt remotes wrapping their base remotes, and rclonepool uses the crypt remotes as its storage targets.

9. **WebDAV is the bridge.** To integrate with rclone's ecosystem, rclonepool exposes itself as a WebDAV server. This means:
   - You can add it as an rclone remote (`type = webdav`)
   - You can `rclone mount` it
   - You can `rclone copy` to/from it
   - You can `rclone serve http/dlna/ftp` on top of it
   - Any WebDAV client (including OS file managers) can access it
   - Video players can stream from it via HTTP with Range support

10. **Simplicity over cleverness.** The codebase uses only Python stdlib. No async frameworks, no database engines, no complex dependency trees. A single `python rclonepool.py serve` starts everything.

### 3.2 Non-Goals (Explicit)

- **Not a filesystem.** rclonepool does not implement POSIX semantics. No hard links, no permissions, no inotify. It is a file store with upload/download/delete/list.
- **Not a sync tool.** It does not watch for changes or auto-sync. Use rclone sync on top if needed.
- **Not a backup tool.** It does not do versioning, snapshots, or incremental backups. It stores files.
- **Not a RAID system.** v0.1 has no parity or redundancy. Losing a remote means losing the chunks on it. (Parity is planned for future versions.)
- **Not a CDN.** There is no caching layer, no edge distribution, no geo-routing.

---

## 4. Architecture — Detailed

### 4.1 Component Overview

```text
┌──────────────────────────────────────────────────────────────────┐
│                        USER INTERFACES                           │
│                                                                  │
│  CLI (rclonepool.py)          WebDAV Server (webdav_server.py)   │
│  ├── upload                   ├── GET + Range (streaming)        │
│  ├── download                 ├── PUT (upload)                   │
│  ├── ls                       ├── DELETE                         │
│  ├── delete                   ├── PROPFIND (listing)             │
│  ├── status                   ├── HEAD (metadata)                │
│  ├── serve                    ├── OPTIONS (capability)           │
│  └── init                     ├── MKCOL (mkdir — virtual)        │
│                               └── MOVE (rename)                  │
├──────────────────────────────────────────────────────────────────┤
│                     ORCHESTRATION LAYER                           │
│                                                                  │
│  RclonePool (rclonepool.py)                                      │
│  ├── Coordinates all operations                                  │
│  ├── Owns instances of Chunker, Balancer, ManifestManager,       │
│  │   RcloneBackend                                               │
│  ├── upload() — chunk + distribute + manifest                    │
│  ├── download() — manifest lookup + fetch + reassemble           │
│  ├── download_range() — manifest lookup + partial chunk fetch    │
│  ├── ls() — manifest enumeration                                 │
│  ├── delete() — chunk deletion + manifest deletion               │
│  └── status() — remote space reporting                           │
├──────────────────────────────────────────────────────────────────┤
│                      CORE COMPONENTS                             │
│                                                                  │
│  Chunker (chunker.py)           Balancer (balancer.py)           │
│  ├── split_file_streaming()     ├── get_least_used_remote()      │
│  │   Generator that yields      │   Returns remote with most     │
│  │   (index, data, offset,      │   free space                   │
│  │    length) tuples             ├── record_usage()               │
│  ├── get_chunk_count()          │   Updates cached usage after   │
│  └── reassemble_chunks()       │   an upload                    │
│                                 └── get_usage_report()           │
│                                                                  │
│  ManifestManager (manifest.py)  RcloneBackend (rclone_backend.py)│
│  ├── create_manifest()          ├── upload_file()                │
│  ├── save_manifest()            ├── upload_bytes()               │
│  │   Saves to ALL remotes       ├── download_bytes()             │
│  ├── load_manifest_for_file()   ├── download_byte_range()        │
│  │   Tries cache, then remotes  │   Uses rclone cat --offset     │
│  ├── list_manifests()           ├── download_file()              │
│  ├── delete_manifest()          ├── delete_file()                │
│  └── rebuild_cache()            ├── list_files()                 │
│                                 ├── list_dirs()                  │
│                                 ├── get_space()                  │
│                                 │   Uses rclone about --json     │
│                                 └── check_remote_exists()        │
├──────────────────────────────────────────────────────────────────┤
│                      CONFIGURATION                               │
│                                                                  │
│  Config (config.py)                                              │
│  ├── Loads from ~/.config/rclonepool/config.json                 │
│  ├── Provides typed property accessors                           │
│  ├── Handles defaults for missing keys                           │
│  └── init_interactive() — guided setup wizard                    │
├──────────────────────────────────────────────────────────────────┤
│                      STORAGE LAYER                               │
│                                                                  │
│  rclone crypt remotes (optional)                                 │
│  ├── crypt-mega1: → mega1:encrypted/                             │
│  ├── crypt-mega2: → mega2:encrypted/                             │
│  ├── crypt-mega3: → mega3:encrypted/                             │
│  ├── crypt-mega4: → mega4:encrypted/                             │
│  └── crypt-mega5: → mega5:encrypted/                             │
│                                                                  │
│  Base remotes (any rclone remote type)                           │
│  ├── mega1: (MEGA account 1, 20GB)                               │
│  ├── mega2: (MEGA account 2, 20GB)                               │
│  ├── mega3: (MEGA account 3, 20GB)                               │
│  ├── mega4: (MEGA account 4, 20GB)                               │
│  └── mega5: (MEGA account 5, 20GB)                               │
└──────────────────────────────────────────────────────────────────┘
```

### 4.2 Data Flow — Upload

```text
User: rclonepool upload ./movie.mkv /movies/movie.mkv

1. RclonePool.upload() called
   │
2. Check file exists, get file_size
   │
3. If file_size <= chunk_size (100MB):
   │  ├── Balancer.get_least_used_remote() → pick one remote
   │  ├── RcloneBackend.upload_file() → rclone copyto ./movie.mkv crypt-mega3:rclonepool_data/movie.mkv.chunk.000
   │  ├── ManifestManager.create_manifest() → JSON with 1 chunk entry
   │  └── ManifestManager.save_manifest() → rclone copyto manifest.json to ALL remotes
   │
4. If file_size > chunk_size:
   │  ├── Chunker.split_file_streaming() → generator
   │  ├── For each (index, data, offset, length):
   │  │   ├── Balancer.get_least_used_remote() → pick remote with most free space
   │  │   ├── Write data to /dev/shm/rclonepool/chunk_xxx.tmp (RAM)
   │  │   ├── RcloneBackend.upload_file() → rclone copyto tmpfile crypt-megaN:rclonepool_data/movie.mkv.chunk.NNN
   │  │   ├── Delete tmpfile from /dev/shm
   │  │   ├── Balancer.record_usage() → update cached usage for that remote
   │  │   └── Append chunk info to chunks_info list
   │  ├── ManifestManager.create_manifest() → JSON with all chunk entries
   │  └── ManifestManager.save_manifest() → upload manifest to ALL remotes
   │
5. Done. File is now distributed across remotes as encrypted chunks.
```

### 4.3 Data Flow — Download

```text
User: rclonepool download /movies/movie.mkv ./movie.mkv

1. RclonePool.download() called
   │
2. ManifestManager.load_manifest_for_file("/movies/movie.mkv")
   │  ├── Check in-memory cache
   │  ├── If not cached: try each remote until manifest found
   │  └── Parse JSON, return manifest dict
   │
3. Open output file for writing
   │
4. For each chunk (sorted by index):
   │  ├── RcloneBackend.download_bytes(chunk.remote, chunk.path)
   │  │   ├── rclone copyto crypt-mega3:rclonepool_data/movie.mkv.chunk.000 /dev/shm/rclonepool/dl_xxx.tmp
   │  │   ├── Read tmpfile into memory
   │  │   └── Delete tmpfile
   │  └── Write chunk data to output file
   │
5. Close output file. Done.
```

### 4.4 Data Flow — Range Request (Video Streaming)

```text
Video player: GET /movies/movie.mkv  Range: bytes=524288000-525336575
(Player wants bytes 500MB–501MB of the file)

1. WebDAVHandler.do_GET() detects Range header
   │
2. RclonePool.download_range("/movies/movie.mkv", offset=524288000, length=1048576)
   │
3. ManifestManager.load_manifest_for_file() → get manifest
   │
4. Calculate which chunks contain the requested range:
   │  ├── chunk_size = 104857600 (100MB)
   │  ├── Chunk 4: offset 419430400 – 524288000 (does NOT contain start)
   │  ├── Chunk 5: offset 524288000 – 629145600 (CONTAINS start)
   │  │   offset_in_chunk = 524288000 - 524288000 = 0
   │  │   bytes_from_chunk = min(104857600 - 0, 1048576) = 1048576
   │  └── Only chunk 5 needed (request fits within one chunk)
   │
5. RcloneBackend.download_byte_range(chunk.remote, chunk.path, 0, 1048576)
   │  └── rclone cat crypt-mega2:rclonepool_data/movie.mkv.chunk.005 --offset 0 --count 1048576
   │
6. Return 1048576 bytes to WebDAVHandler
   │
7. WebDAVHandler sends HTTP 206 Partial Content with Content-Range header
   │
8. Video player receives bytes, continues playback. Seeking works.
```

### 4.5 Data Flow — Cross-Chunk Range Request

```text
Player requests bytes that span two chunks:

Range: bytes=104857500-104857700
(Last 100 bytes of chunk 0 + first 101 bytes of chunk 1)

1. download_range() iterates chunks:
   │
2. Chunk 0: offset 0 – 104857600
   │  ├── offset_in_chunk = 104857500 - 0 = 104857500
   │  ├── bytes_from_chunk = min(104857600 - 104857500, 201) = 100
   │  └── Fetch 100 bytes from chunk 0 via rclone cat --offset 104857500 --count 100
   │
3. Chunk 1: offset 104857600 – 209715200
   │  ├── current_offset is now 104857600
   │  ├── offset_in_chunk = 104857600 - 104857600 = 0
   │  ├── bytes_from_chunk = min(104857600 - 0, 101) = 101
   │  └── Fetch 101 bytes from chunk 1 via rclone cat --offset 0 --count 101
   │
4. Concatenate: 100 + 101 = 201 bytes returned
```

---

## 5. On-Remote Data Layout

### 5.1 Directory Structure (per remote)

```text
crypt-mega1:
├── rclonepool_data/
│   ├── movie.mkv.chunk.000
│   ├── movie.mkv.chunk.003
│   ├── movie.mkv.chunk.007
│   ├── photo.jpg.chunk.000        (small file, single chunk)
│   └── bigarchive.tar.chunk.012
│
└── rclonepool_manifests/
    ├── _movies_movie.mkv.manifest.json
    ├── _photos_photo.jpg.manifest.json
    └── _backups_bigarchive.tar.manifest.json
```

Note: Each remote only has SOME chunks of each file (whichever the balancer assigned to it), but ALL remotes have ALL manifests.

### 5.2 Chunk Naming Convention

```text
{file_name}.chunk.{index:03d}

Examples:
  movie.mkv.chunk.000
  movie.mkv.chunk.001
  movie.mkv.chunk.021
  photo.jpg.chunk.000
```

The 3-digit zero-padded index supports up to 1000 chunks per file. At 100MB per chunk, that is 100GB max file size. For larger files, the format could be extended to 4+ digits.

### 5.3 Manifest Naming Convention

```text
{safe_file_path}.manifest.json

Where safe_file_path = file_path.replace('/', '_').strip('_')

Examples:
  /movies/movie.mkv       → _movies_movie.mkv.manifest.json
  /photo.jpg               → _photo.jpg.manifest.json
  /backups/2024/dump.tar   → _backups_2024_dump.tar.manifest.json
```

### 5.4 Manifest JSON Schema

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
    },
    {
      "index": 20,
      "remote": "crypt-mega4:",
      "path": "rclonepool_data/movie.mkv.chunk.020",
      "size": 41943040,
      "offset": 2097152000
    }
  ],
  "created_at": 1700000000.0,
  "checksum": "a1b2c3d4e5f6g7h8"
}
```

Fields:

| Field | Type | Description |
|---|---|---|
| `version` | int | Manifest format version (currently 1) |
| `file_name` | string | Base filename |
| `remote_dir` | string | Virtual directory path |
| `file_path` | string | Full virtual path (`remote_dir/file_name`) |
| `file_size` | int | Total file size in bytes |
| `chunk_size` | int | Configured chunk size (for reference) |
| `chunk_count` | int | Number of chunks |
| `chunks` | array | Ordered list of chunk descriptors |
| `chunks[].index` | int | Zero-based chunk index |
| `chunks[].remote` | string | rclone remote name holding this chunk |
| `chunks[].path` | string | Path within the remote |
| `chunks[].size` | int | Actual size of this chunk in bytes (last chunk may be smaller) |
| `chunks[].offset` | int | Byte offset of this chunk within the original file |
| `created_at` | float | Unix timestamp of upload |
| `checksum` | string | Short hash for integrity verification |

---

## 6. Balancing Strategy — Detailed

### 6.1 Current: Least-Used-First

```text
Algorithm:
  1. On startup, query `rclone about --json` for each remote
  2. Cache: { remote_name: used_bytes }
  3. For each chunk to upload:
     a. Pick remote with MINIMUM used_bytes
     b. Upload chunk to that remote
     c. Update cache: used_bytes[remote] += chunk_size
  4. Result: chunks distribute evenly across remotes
```

Example with 5 remotes and a 500MB file (5 chunks of 100MB):

```text
Initial state:
  crypt-mega1: 2GB used
  crypt-mega2: 1GB used    ← least
  crypt-mega3: 3GB used
  crypt-mega4: 1.5GB used
  crypt-mega5: 2.5GB used

Chunk 0 → crypt-mega2 (1GB, least used)
  crypt-mega2: now 1.1GB

Chunk 1 → crypt-mega2 (still least at 1.1GB)
  crypt-mega2: now 1.2GB

Chunk 2 → crypt-mega2 (still least at 1.2GB)
  crypt-mega2: now 1.3GB

Chunk 3 → crypt-mega2 (still least at 1.3GB)
  crypt-mega2: now 1.4GB

Chunk 4 → crypt-mega2 (still least at 1.4GB)
  crypt-mega2: now 1.5GB

Result: All chunks went to mega2 because it was always the least used.
```

### 6.2 Known Limitation

The current strategy can concentrate chunks on one remote when there is a large gap in usage. This is actually correct behavior for balancing overall storage usage, but it means a single file's chunks may not be spread across all remotes.

### 6.3 Planned: Round-Robin with Least-Used Tiebreaker

```text
Future algorithm:
  1. Maintain a round-robin pointer across remotes
  2. For each chunk:
     a. Start from the next remote in rotation
     b. Skip any remote that is full (free < chunk_size)
     c. Among eligible remotes, prefer the least-used one
     d. Upload chunk
     e. Advance rotation pointer
  3. Result: chunks spread across ALL remotes, with slight preference for emptier ones
```

### 6.4 Planned: Rebalancing

```text
Future command: rclonepool rebalance

Algorithm:
  1. Load all manifests
  2. Calculate ideal distribution: total_chunks / num_remotes = chunks_per_remote
  3. Identify over-loaded remotes (more chunks than ideal)
  4. Identify under-loaded remotes (fewer chunks than ideal)
  5. For each excess chunk on over-loaded remotes:
     a. Download chunk from over-loaded remote
     b. Upload chunk to most under-loaded remote
     c. Update manifest
     d. Delete chunk from original remote
     e. Save updated manifest to all remotes
  6. Result: chunks redistributed evenly

Triggers:
  - Manual: user runs `rclonepool rebalance`
  - Automatic: when a new remote is added to config
  - Threshold: when imbalance exceeds configurable percentage
```

---

## 7. Encryption — Detailed

### 7.1 How rclone crypt Works

```text
rclone crypt wraps another remote and provides:
  - File content encryption: NaCl secretbox (XSalsa20 cipher + Poly1305 MAC)
  - File name encryption: EME wide-block cipher (optional, enabled by default)
  - File name obfuscation: alternative to full encryption
  - No metadata leakage: file sizes are padded (optional)

When rclonepool uploads a chunk to crypt-mega1:
  1. rclone writes the chunk to the crypt remote
  2. The crypt remote encrypts the chunk data
  3. The crypt remote encrypts the file name
  4. The encrypted data + encrypted filename are stored on mega1:encrypted/
  5. MEGA sees only encrypted blobs with random-looking names
```

### 7.2 What MEGA Sees

```text
Without encryption:
  mega1:rclonepool_data/movie.mkv.chunk.000     ← MEGA knows the filename and can read content

With encryption:
  mega1:encrypted/q7k2m8x1p3/f9j4n2v8r6w1      ← MEGA sees encrypted name, encrypted content
```

### 7.3 Key Management

- The user provides a password and salt when creating crypt remotes
- The SAME password and salt must be used for ALL crypt remotes (so that rclonepool can read any manifest from any remote)
- Passwords are stored in rclone's config file (`~/.config/rclone/rclone.conf`), obscured (not truly encrypted — rclone's obscure is reversible, it is obfuscation only)
- For true security, use `RCLONE_CONFIG_PASS` environment variable to encrypt the rclone config file itself

### 7.4 Manifest Encryption

Manifests are also stored through the crypt layer, so:
- Manifest filenames are encrypted on the remote
- Manifest JSON content is encrypted on the remote
- MEGA cannot see which files you have, how they are chunked, or where chunks live

---

## 8. WebDAV Server — Detailed

### 8.1 Why WebDAV?

| Requirement | WebDAV Support |
|---|---|
| rclone can use it as a remote | ✅ `type = webdav` |
| rclone can mount it | ✅ `rclone mount webdav-remote: /mnt/pool` |
| rclone can copy to/from it | ✅ `rclone copy webdav-remote:file ./` |
| Supports Range requests (video seeking) | ✅ HTTP Range is part of WebDAV/HTTP |
| Supports file upload | ✅ PUT method |
| Supports directory listing | ✅ PROPFIND method |
| Supports deletion | ✅ DELETE method |
| Works with OS file managers | ✅ macOS Finder, Windows Explorer, GNOME Files |
| Works with video players | ✅ mpv, VLC can stream HTTP with Range |
| Low implementation complexity | ✅ ~400 lines of Python stdlib |

### 8.2 Supported HTTP/WebDAV Methods

| Method | Purpose | Implementation Notes |
|---|---|---|
| `OPTIONS` | Capability discovery | Returns DAV: 1, 2 and allowed methods |
| `HEAD` | File/dir metadata | Returns Content-Length, Content-Type, Accept-Ranges |
| `GET` | Download / stream | Full download or partial (Range). Streams chunk-by-chunk |
| `PUT` | Upload | Receives body, writes to tmpfs, calls pool.upload() |
| `DELETE` | Delete file | Calls pool.delete() which removes all chunks + manifest |
| `MKCOL` | Create directory | No-op success (directories are virtual) |
| `MOVE` | Rename/move file | Updates manifest path, does not move chunks |
| `PROPFIND` | Directory listing | Returns XML multistatus with file/dir properties |

### 8.3 Range Request Handling

```text
Client: GET /movies/movie.mkv
        Range: bytes=0-1048575

Server:
  1. Parse Range header → start=0, end=1048575, length=1048576
  2. Call pool.download_range("/movies/movie.mkv", 0, 1048576)
  3. Receive 1MB of data from chunk 0
  4. Respond: HTTP 206 Partial Content
             Content-Range: bytes 0-1048575/2147483648
             Content-Length: 1048576
             Content-Type: video/x-matroska
             Accept-Ranges: bytes
             [1MB of data]
```

Range format support:

| Format | Example | Meaning |
|---|---|---|
| `bytes=start-end` | `bytes=0-1023` | First 1024 bytes |
| `bytes=start-` | `bytes=1000-` | From byte 1000 to end |
| `bytes=-suffix` | `bytes=-500` | Last 500 bytes |

### 8.4 Threading Model

The WebDAV server uses `ThreadingMixIn` from Python stdlib:
- Each incoming request is handled in a separate thread
- This allows concurrent reads (e.g., video streaming while listing files)
- `daemon_threads = True` ensures threads die with the main process
- No explicit thread pool or async — simple and sufficient for personal use

### 8.5 Browser Access

Navigating to `http://localhost:8080/` in a browser shows an HTML directory listing with:
- File names (clickable — downloads/streams the file)
- File sizes (human-readable)
- Chunk count
- Which remotes hold chunks of each file
- Dark theme with monospace font

---

## 9. Configuration — Detailed

### 9.1 Config File Location

```text
~/.config/rclonepool/config.json
```

Overridable with `-c` / `--config` flag.

### 9.2 Full Config Schema

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
  "rclone_flags": ["--fast-list", "--no-traverse"],
  "webdav_port": 8080,
  "webdav_host": "0.0.0.0"
}
```

### 9.3 Config Field Reference

| Field | Type | Default | Description |
|---|---|---|---|
| `remotes` | string[] | `[]` | Base rclone remote names (with trailing colon) |
| `crypt_remotes` | string[] | `[]` | Crypt-wrapped remote names. If `use_crypt` is true and this is non-empty, these are used instead of `remotes` for all data operations |
| `use_crypt` | bool | `true` | Whether to use crypt remotes |
| `chunk_size` | int | `104857600` | Chunk size in bytes. 100MB = 104857600 |
| `data_prefix` | string | `"rclonepool_data"` | Folder name on remotes where chunks are stored |
| `manifest_prefix` | string | `"rclonepool_manifests"` | Folder name on remotes where manifests are stored |
| `temp_dir` | string | `"/dev/shm/rclonepool"` | Temp directory for chunk operations. Use RAM-backed filesystem |
| `rclone_binary` | string | `"rclone"` | Path to rclone binary |
| `rclone_flags` | string[] | `["--fast-list", "--no-traverse"]` | Additional flags passed to all rclone commands |
| `webdav_port` | int | `8080` | Port for the WebDAV server |
| `webdav_host` | string | `"0.0.0.0"` | Bind address for the WebDAV server. Use `127.0.0.1` for local-only access |

### 9.4 Choosing Chunk Size

| Chunk Size | Chunks per 20GB Remote | Max File Size (999 chunks) | Balancing Granularity | Upload Overhead |
|---|---|---|---|---|
| 10MB | 2,048 | ~10GB | Excellent | High (many rclone calls) |
| 50MB | 409 | ~50GB | Very good | Medium |
| **100MB** | **204** | **~100GB** | **Good (default)** | **Low** |
| 250MB | 81 | ~250GB | Fair | Very low |
| 500MB | 40 | ~500GB | Poor | Minimal |
| 1GB | 20 | ~1TB | Poor | Minimal |

Recommendation:
- **100MB** is the sweet spot for most users
- Use **50MB** if you have many remotes and want finer-grained balancing
- Use **250MB+** only if you have very large files and few remotes

### 9.5 Temp Directory Recommendations

| OS | Recommended `temp_dir` | Notes |
|---|---|---|
| Linux | `/dev/shm/rclonepool` | tmpfs, RAM-backed, no disk writes |
| macOS | `/tmp/rclonepool` | macOS `/tmp` is often RAM-backed via `tmps` but not guaranteed. Alternatively use a RAM disk: `diskutil erasevolume HFS+ 'RAMDisk' $(hdiutil attach -nomount ram://2097152)` |
| Linux (no /dev/shm) | `/run/user/$(id -u)/rclonepool` | User-specific tmpfs on systemd systems |
| Fallback | `/tmp/rclonepool` | Works everywhere but may write to disk |

---

## 10. Memory and Performance Characteristics

### 10.1 Memory Usage

| Operation | Peak RAM Usage | Notes |
|---|---|---|
| Upload (chunked) | ~chunk_size (100MB) | One chunk in memory at a time |
| Upload (small file) | ~file_size | Entire file in memory |
| Download (full) | ~chunk_size (100MB) | One chunk in memory at a time, written to disk sequentially |
| Download (range) | ~requested_range | Only the requested bytes, fetched via `rclone cat` |
| WebDAV GET (full) | ~chunk_size (100MB) | Chunks streamed to client one at a time |
| WebDAV GET (range) | ~requested_range | Typically 1-10MB for video streaming |
| Manifest operations | ~few KB per manifest | JSON files are tiny |
| Balancer | ~few KB | Just a dict of remote → used_bytes |

### 10.2 Disk I/O

| Operation | Disk Writes | Location |
|---|---|---|
| Upload chunk | 1 temp write + 1 temp delete | `/dev/shm` (RAM) |
| Download chunk | 1 temp write + 1 temp delete | `/dev/shm` (RAM) |
| Download to file | 1 sequential write | User-specified output path |
| WebDAV upload | 1 temp write + 1 temp delete per chunk | `/dev/shm` (RAM) |
| WebDAV streaming | 0 disk writes | Streamed directly from rclone to HTTP response |
| Manifest save | 0 (goes to remote) | Via rclone, temp in `/dev/shm` |

**Net SSD writes for typical usage: ZERO** (assuming `/dev/shm` is used)

### 10.3 Network I/O

| Operation | Network Calls | Notes |
|---|---|---|
| Upload 1GB file | 10 chunk uploads + 5 manifest uploads | 10 chunks × 100MB + manifest to each remote |
| Download 1GB file | 1 manifest download + 10 chunk downloads | Manifest from first available remote |
| Stream 10s of video | 1 manifest download + 1-2 chunk range reads | `rclone cat` with offset/count |
| List files | 1 `rclone lsf` + N manifest downloads | N = number of files in directory |
| Delete file | 1 manifest load + C chunk deletes + R manifest deletes | C = chunk count, R = remote count |

### 10.4 Latency Expectations

| Operation | Expected Latency | Bottleneck |
|---|---|---|
| Upload chunk | 2-30s per chunk | MEGA upload speed |
| Download chunk | 2-30s per chunk | MEGA download speed |
| Range read (1MB) | 1-5s | rclone startup + MEGA API latency |
| List files | 2-10s | rclone lsf + manifest parsing |
| Video seek | 2-8s | Chunk fetch latency |
| Manifest load | 1-3s | First rclone download |

Note: Video streaming will have noticeable seek latency (2-8 seconds) because each seek may require fetching a new chunk from MEGA. This is inherent to the architecture and cannot be avoided without a local cache.

### 10.5 Performance Optimization Ideas (Future)

1. **Chunk cache in RAM** — Keep recently accessed chunks in an LRU cache in `/dev/shm`. This would make repeated range reads (e.g., video player buffering) instant.

2. **Prefetch** — When a range read hits chunk N, proactively fetch chunk N+1 in a background thread. This would smooth out sequential streaming.

3. **Parallel chunk uploads** — Upload multiple chunks simultaneously using a thread pool. Would dramatically speed up large file uploads.

4. **Parallel chunk downloads** — Same for downloads.

5. **Manifest caching on disk** — Cache manifests locally (they are tiny) to avoid fetching from remotes on every operation. The current in-memory cache works but is lost on restart.

6. **Connection pooling** — Reuse rclone processes instead of spawning a new one per operation. Could use `rclone rc` (remote control) API.

---

## 11. Error Handling and Edge Cases

### 11.1 Failure Modes

| Failure | Impact | Current Handling | Planned Handling |
|---|---|---|---|
| Remote offline during upload | Chunk upload fails | Error logged, upload aborted | Retry with backoff, skip to next remote |
| Remote offline during download | Chunk download fails | Error logged, download aborted | Retry with backoff |
| Remote offline during manifest save | Manifest not saved to that remote | Warning logged, continues to other remotes | Already handled (saves to all, warns on failure) |
| All remotes offline | Nothing works | Error messages | Graceful error with retry prompt |
| Manifest missing from all remotes | File appears lost | "No manifest found" error | Scan data folders for orphaned chunks, attempt reconstruction |
| Chunk missing from remote | File partially unrecoverable | Download fails at that chunk | Skip with warning, or use parity to reconstruct (future) |
| Manifest corrupted | File metadata lost | JSON parse error | Fall back to other remotes' copies |
| Disk full on remote during upload | rclone error | Upload fails, error logged | Detect, skip to next remote, retry chunk |
| `/dev/shm` full | Temp file write fails | OS error | Detect, warn, suggest increasing tmpfs size |
| rclone binary not found | All operations fail | FileNotFoundError | Clear error message with install instructions |
| rclone config missing remote | Operations on that remote fail | rclone error propagated | Validate remotes on startup |
| Duplicate file upload | Old chunks orphaned | No detection | Check for existing manifest, prompt for overwrite, clean old chunks |
| Concurrent uploads to same path | Race condition on manifest | Last writer wins | File-level locking (future) |

### 11.2 Chunk Naming Collisions

If two different files have the same name but are in different directories:

```text
/movies/clip.mp4    → chunks: clip.mp4.chunk.000, clip.mp4.chunk.001
/backup/clip.mp4    → chunks: clip.mp4.chunk.000, clip.mp4.chunk.001  ← COLLISION!
```

**Current status:** This is a known bug. Chunks would overwrite each other.

**Planned fix:** Include a hash of the full path in the chunk name:

```text
/movies/clip.mp4    → chunks: a1b2c3_clip.mp4.chunk.000
/backup/clip.mp4    → chunks: d4e5f6_clip.mp4.chunk.000
```

Or use the full safe path:

```text
/movies/clip.mp4    → chunks: movies_clip.mp4.chunk.000
/backup/clip.mp4    → chunks: backup_clip.mp4.chunk.000
```

---

## 12. Security Considerations

### 12.1 Threat Model

| Threat | Mitigation |
|---|---|
| Cloud provider reads your files | rclone crypt encrypts content + filenames |
| Cloud provider correlates files by size | Chunking makes all objects ~100MB (uniform) |
| Cloud provider analyzes access patterns | Not mitigated — access patterns visible |
| MITM on network | rclone uses HTTPS for MEGA API |
| Local attacker reads rclone config | Use `RCLONE_CONFIG_PASS` to encrypt rclone.conf |
| Local attacker reads temp files | Temp files are in RAM (`/dev/shm`), deleted immediately after use |
| Local attacker reads manifests in RAM | Python process memory — standard OS protections apply |
| WebDAV server accessed by unauthorized users | Bind to `127.0.0.1`, or add authentication (future) |
| Manifest tampering on remote | Checksum field in manifest (weak — future: HMAC) |

### 12.2 What is NOT Encrypted

- **rclone.conf** — contains remote credentials and crypt passwords (obfuscated, not encrypted). Use `RCLONE_CONFIG_PASS` to encrypt it.
- **Manifest structure** — while the manifest content is encrypted by crypt on the remote, the local in-memory cache is plaintext. This is necessary for operation.
- **WebDAV traffic** — the WebDAV server runs plain HTTP. If exposed to the network, use a reverse proxy with TLS (nginx, caddy).
- **rclone process arguments** — chunk paths and remote names are visible in `ps aux` output on the local machine.

### 12.3 WebDAV Authentication (Planned)

Currently the WebDAV server has no authentication. Planned options:

1. **HTTP Basic Auth** — simple username/password
2. **API key in header** — custom `X-API-Key` header
3. **Bind to localhost only** — simplest, use `127.0.0.1` as host

---

## 13. Future Roadmap

### 13.1 v0.2 — Robustness

- [ ] Fix chunk naming collision for same-named files in different directories
- [ ] Add retry logic with exponential backoff for failed rclone operations
- [ ] Add `rclonepool verify` command — check all chunks exist and match manifest
- [ ] Add `rclonepool repair` command — re-upload missing chunks from local copy
- [ ] Add `rclonepool orphans` command — find chunks with no manifest reference
- [ ] Local manifest cache file (persist across restarts)
- [ ] Duplicate file detection (check manifest before upload)

### 13.2 v0.3 — Performance

- [ ] Parallel chunk uploads (configurable thread count)
- [ ] Parallel chunk downloads
- [ ] Chunk LRU cache in `/dev/shm` for streaming
- [ ] Prefetch next chunk during sequential reads
- [ ] Use `rclone rcd` (daemon mode) for connection pooling
- [ ] Progress bars for CLI uploads/downloads

### 13.3 v0.4 — Balancing

- [ ] Round-robin with least-used tiebreaker balancing
- [ ] `rclonepool rebalance` command
- [ ] Auto-rebalance when new remote added
- [ ] Configurable balancing strategy (least-used, round-robin, random, weighted)
- [ ] Remote weight/priority configuration (prefer faster remotes)

### 13.4 v0.5 — Redundancy

- [ ] Reed-Solomon parity chunks (configurable: e.g., 3 data + 1 parity)
- [ ] `rclonepool rebuild` — reconstruct lost chunks from parity
- [ ] Configurable replication factor (store each chunk on N remotes)
- [ ] Health monitoring — periodic check that all chunks are accessible

### 13.5 v0.6 — Advanced Features

- [ ] WebDAV authentication (Basic Auth, API key)
- [ ] HTTPS support for WebDAV server
- [ ] Deduplication (content-addressable storage using chunk hashes)
- [ ] Compression before encryption (zstd)
- [ ] Bandwidth throttling (per-remote)
- [ ] Web UI dashboard (storage usage, file browser, upload/download)
- [ ] Docker container with all dependencies
- [ ] Systemd service file for auto-start

### 13.6 v1.0 — Production Ready

- [ ] Comprehensive test suite
- [ ] CI/CD pipeline
- [ ] Documentation site
- [ ] Plugin system for custom balancing/chunking strategies
- [ ] Multi-user support with isolated pools
- [ ] API for programmatic access (REST + WebSocket)

---

## 14. Comparison with Alternatives

| Feature | rclonepool | rclone union+chunker | Minio Gateway | SeaweedFS | IPFS |
|---|---|---|---|---|---|
| Chunks across remotes | ✅ | ❌ | ❌ | ✅ | ✅ |
| Works with MEGA/GDrive/etc | ✅ | ✅ | ❌ (S3 only) | ❌ | ❌ |
| Encryption | ✅ (rclone crypt) | ✅ | ✅ | ⚠️ | ⚠️ |
| Video streaming with seek | ✅ | ⚠️ | ✅ | ✅ | ❌ |
| No local state needed | ✅ | ✅ | ❌ | ❌ | ❌ |
| No external dependencies | ✅ | ✅ | ❌ | ❌ | ❌ |
| Files larger than single remote | ✅ | ❌ | N/A | ✅ | ✅ |
| Balanced distribution | ✅ | ❌ | N/A | ✅ | ✅ |
| rclone integration | ✅ (WebDAV) | ✅ (native) | ⚠️ | ❌ | ❌ |
| Setup complexity | Low | Very Low | High | High | High |
| Production ready | ❌ (v0.1) | ✅ | ✅ | ✅ | ✅ |

---

## 15. Glossary

| Term | Definition |
|---|---|
| **Remote** | An rclone-configured storage backend (e.g., `mega1:`, `gdrive:`, `s3:`) |
| **Crypt remote** | An rclone remote of type `crypt` that wraps another remote with encryption |
| **Chunk** | A fixed-size piece of a file, stored as a separate object on a remote |
| **Manifest** | A JSON file describing a file's chunks, their locations, and metadata |
| **Balancer** | The component that decides which remote receives each chunk |
| **Pool** | The logical combination of all remotes, appearing as unified storage |
| **Data prefix** | The folder name on each remote where chunks are stored |
| **Manifest prefix** | The folder name on each remote where manifests are stored |
| **Range request** | An HTTP request for a specific byte range of a file (used for video seeking) |
| **tmpfs** | A RAM-backed temporary filesystem (e.g., `/dev/shm` on Linux) |
| **WebDAV** | Web Distributed Authoring and Versioning — an HTTP extension for file management |
| **PROPFIND** | A WebDAV method for querying file/directory properties |
| **Multistatus** | A WebDAV XML response format containing multiple resource properties |

---

## 16. Development Notes

### 16.1 Running in Development

```bash
# Clone the project
git clone <repo>
cd rclonepool

# No dependencies to install!

# Run init
python rclonepool.py init

# Test with local remotes (no cloud needed)
mkdir -p /tmp/fake-remote-{1,2,3}
# Add to rclone.conf:
#   [local1]
#   type = local
#   nounc = true
# (repeat for local2, local3)
# Then configure rclonepool with remotes: ["local1:/tmp/fake-remote-1/", ...]

# Run server
python rclonepool.py serve --port 8080

# Test upload
python rclonepool.py upload testfile.bin /test/testfile.bin

# Test download
python rclonepool.py download /test/testfile.bin ./downloaded.bin

# Test via rclone WebDAV
rclone ls :webdav,url=http://localhost:8080:
```

### 16.2 Debugging

```bash
# Enable debug logging
export LOGLEVEL=DEBUG
python rclonepool.py serve

# Or modify the logging line in rclonepool.py:
# logging.basicConfig(level=logging.DEBUG, ...)

# Watch rclone commands being executed:
# All rclone commands are logged at DEBUG level with full arguments
```

### 16.3 Testing Strategies

1. **Unit tests** — Mock `RcloneBackend` to test `Chunker`, `Balancer`, `ManifestManager` in isolation
2. **Integration tests with local remotes** — Use `type = local` rclone remotes pointing to temp directories
3. **Integration tests with real remotes** — Use a dedicated test account
4. **WebDAV compliance tests** — Use `litmus` WebDAV test suite
5. **Streaming tests** — Use `curl` with `Range` headers, or `ffprobe` on the WebDAV URL

---

*This document is the complete specification for rclonepool v0.1. It should contain everything needed to understand, implement, extend, debug, and reason about the system.*