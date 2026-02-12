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
| `webdav_