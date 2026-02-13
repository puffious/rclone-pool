"""
Configuration management for rclonepool.
"""

# rclonepool/config.py

import json
import os
import sys
import logging

log = logging.getLogger("rclonepool")

DEFAULT_CONFIG = {
    "remotes": [],
    "chunk_size": 104857600,  # 100MB
    "data_prefix": "rclonepool_data",
    "manifest_prefix": "rclonepool_manifests",
    "use_crypt": True,
    "crypt_remotes": [],  # If empty and use_crypt is True, we expect crypt-<name> remotes
    "temp_dir": "/dev/shm/rclonepool",  # RAM-based temp on Linux
    "rclone_binary": "rclone",
    "rclone_flags": ["--fast-list", "--no-traverse"],
    "webdav_port": 8080,
    "webdav_host": "0.0.0.0",
    # v0.2 - Robustness
    "enable_retry": True,
    "max_retries": 3,
    "retry_delay": 1.0,
    "enable_manifest_cache": True,
    "manifest_cache_dir": "~/.cache/rclonepool",
    "enable_duplicate_detection": True,
    # v0.3 - Performance
    "parallel_uploads": False,
    "parallel_downloads": False,
    "max_parallel_workers": 4,
    "enable_chunk_cache": True,
    "chunk_cache_size_mb": 500,
    "enable_prefetch": True,
    "prefetch_chunks": 2,
    "enable_rclone_daemon": False,
    "rclone_daemon_port": 5572,
    "show_progress": True,
    # v0.4 - Balancing
    "balancing_strategy": "least_used",  # least_used, round_robin, weighted, random, round_robin_least_used
    "remote_weights": {},  # {"remote1:": 1.5, "remote2:": 1.0}
    "remote_priorities": {},  # {"remote1:": 10, "remote2:": 5}
    "auto_rebalance": False,
    "rebalance_threshold": 10.0,  # Trigger rebalance if variance > this %
    # v0.5 - Redundancy
    "redundancy_mode": "none",  # none, replication, parity, hybrid
    "replication_factor": 1,
    "parity_data_shards": 3,
    "parity_parity_shards": 1,
    "enable_health_monitoring": False,
    "health_check_interval": 3600,  # seconds
    # v0.6 - Advanced Features
    "enable_deduplication": False,
    "enable_compression": False,
    "compression_level": 3,
    "bandwidth_limit_upload_mbps": 0,  # 0 = unlimited
    "bandwidth_limit_download_mbps": 0,
    "webdav_auth_method": "none",  # none, basic, api_key, bearer
    "webdav_users": {},  # {"username": "password_hash"}
    "enable_https": False,
    "ssl_cert_file": "",
    "ssl_key_file": "",
    "enable_webui": True,
    # v1.0 - Production Ready
    "enable_api_server": False,
    "api_server_host": "0.0.0.0",
    "api_server_port": 8081,
    "enable_plugins": True,
    "plugins_dir": "~/.config/rclonepool/plugins",
    "log_level": "INFO",
    "log_file": "",
    "enable_metrics": False,
    "metrics_port": 9090,
}


class Config:
    def __init__(self, config_path: str = None):
        if config_path:
            self.config_path = os.path.expanduser(config_path)
        else:
            self.config_path = os.path.expanduser("~/.config/rclonepool/config.json")

        self._data = dict(DEFAULT_CONFIG)

        if os.path.exists(self.config_path):
            with open(self.config_path, "r") as f:
                user_config = json.load(f)
                self._data.update(user_config)
            log.info(f"Loaded config from {self.config_path}")
        else:
            log.warning(f"No config found at {self.config_path}, using defaults")
            log.warning(f"Run 'rclonepool init' to create a config")

    @property
    def remotes(self) -> list:
        """Get the list of remotes to use (crypt remotes if encryption enabled)."""
        if self._data["use_crypt"] and self._data.get("crypt_remotes"):
            return self._data["crypt_remotes"]
        return self._data["remotes"]

    @property
    def base_remotes(self) -> list:
        """Get the base (non-crypt) remotes."""
        return self._data["remotes"]

    @property
    def chunk_size(self) -> int:
        return self._data["chunk_size"]

    @property
    def data_prefix(self) -> str:
        return self._data["data_prefix"]

    @property
    def manifest_prefix(self) -> str:
        return self._data["manifest_prefix"]

    @property
    def temp_dir(self) -> str:
        return self._data["temp_dir"]

    @property
    def rclone_binary(self) -> str:
        return self._data["rclone_binary"]

    @property
    def rclone_flags(self) -> list:
        return self._data["rclone_flags"]

    @property
    def use_crypt(self) -> bool:
        return self._data["use_crypt"]

    # v0.2 - Robustness properties
    @property
    def enable_retry(self) -> bool:
        return self._data.get("enable_retry", True)

    @property
    def max_retries(self) -> int:
        return self._data.get("max_retries", 3)

    @property
    def enable_manifest_cache(self) -> bool:
        return self._data.get("enable_manifest_cache", True)

    @property
    def manifest_cache_dir(self) -> str:
        return os.path.expanduser(
            self._data.get("manifest_cache_dir", "~/.cache/rclonepool")
        )

    # v0.3 - Performance properties
    @property
    def parallel_uploads(self) -> bool:
        return self._data.get("parallel_uploads", False)

    @property
    def parallel_downloads(self) -> bool:
        return self._data.get("parallel_downloads", False)

    @property
    def max_parallel_workers(self) -> int:
        return self._data.get("max_parallel_workers", 4)

    @property
    def show_progress(self) -> bool:
        return self._data.get("show_progress", True)

    # v0.4 - Balancing properties
    @property
    def balancing_strategy(self) -> str:
        return self._data.get("balancing_strategy", "least_used")

    @property
    def remote_weights(self) -> dict:
        return self._data.get("remote_weights", {})

    @property
    def remote_priorities(self) -> dict:
        return self._data.get("remote_priorities", {})

    # v0.5 - Redundancy properties
    @property
    def redundancy_mode(self) -> str:
        return self._data.get("redundancy_mode", "none")

    @property
    def replication_factor(self) -> int:
        return self._data.get("replication_factor", 1)

    # v0.6 - Advanced Features properties
    @property
    def enable_deduplication(self) -> bool:
        return self._data.get("enable_deduplication", False)

    @property
    def enable_compression(self) -> bool:
        return self._data.get("enable_compression", False)

    @property
    def webdav_auth_method(self) -> str:
        return self._data.get("webdav_auth_method", "none")

    @property
    def enable_https(self) -> bool:
        return self._data.get("enable_https", False)

    @property
    def enable_webui(self) -> bool:
        return self._data.get("enable_webui", True)

    # v1.0 - Production Ready properties
    @property
    def enable_api_server(self) -> bool:
        return self._data.get("enable_api_server", False)

    @property
    def api_server_host(self) -> str:
        return self._data.get("api_server_host", "0.0.0.0")

    @property
    def api_server_port(self) -> int:
        return self._data.get("api_server_port", 8081)

    @property
    def enable_plugins(self) -> bool:
        return self._data.get("enable_plugins", True)

    @property
    def plugins_dir(self) -> str:
        return os.path.expanduser(
            self._data.get("plugins_dir", "~/.config/rclonepool/plugins")
        )

    @property
    def log_level(self) -> str:
        return self._data.get("log_level", "INFO")

    def save(self):
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w") as f:
            json.dump(self._data, f, indent=2)
        log.info(f"Config saved to {self.config_path}")

    @staticmethod
    def init_interactive():
        """Interactive config initialization."""
        print("=== rclonepool Configuration ===\n")

        config_path = os.path.expanduser("~/.config/rclonepool/config.json")
        print(f"Config will be saved to: {config_path}\n")

        # Get remotes
        print("Enter your rclone remote names (the base MEGA remotes).")
        print("Example: mega1 mega2 mega3 mega4 mega5")
        remotes_input = input("Remotes (space-separated): ").strip()
        remotes = [r.strip().rstrip(":") + ":" for r in remotes_input.split()]

        if not remotes:
            print("Error: No remotes provided!")
            sys.exit(1)

        # Encryption
        use_crypt = input("\nUse encryption? (rclone crypt) [Y/n]: ").strip().lower()
        use_crypt = use_crypt != "n"

        crypt_remotes = []
        if use_crypt:
            print(
                f"\nFor encryption, you need crypt remotes wrapping each base remote."
            )
            print(f"Expected crypt remote names:")
            for r in remotes:
                name = r.rstrip(":")
                print(f"  crypt-{name}:")
            print(f"\nDo these crypt remotes already exist in your rclone.conf?")
            existing = input("[Y/n]: ").strip().lower()
            if existing == "n":
                print(f"\nPlease create them first. For each remote, run:")
                for r in remotes:
                    name = r.rstrip(":")
                    print(
                        f"  rclone config create crypt-{name} crypt remote={r}encrypted password=<pass> password2=<salt>"
                    )
                print(f"\nThen run 'rclonepool init' again.")
                sys.exit(0)
            crypt_remotes = [f"crypt-{r.rstrip(':')}:" for r in remotes]

        # Chunk size
        chunk_input = input("\nChunk size in MB [100]: ").strip()
        chunk_size = (
            int(chunk_input) * 1024 * 1024 if chunk_input else 100 * 1024 * 1024
        )

        # Temp dir
        print(f"\nTemp directory for chunk operations (use /dev/shm for RAM-based):")
        temp_dir = (
            input(f"Temp dir [/dev/shm/rclonepool]: ").strip() or "/dev/shm/rclonepool"
        )

        config = dict(DEFAULT_CONFIG)
        config["remotes"] = remotes
        config["use_crypt"] = use_crypt
        config["crypt_remotes"] = crypt_remotes
        config["chunk_size"] = chunk_size
        config["temp_dir"] = temp_dir

        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)

        print(f"\n✓ Config saved to {config_path}")
        print(f"\n✓ Config saved to {config_path}")
        print(f"\nYou can now use:")
        print(f"  rclonepool upload <file> <remote_path>")
        print(f"  rclonepool ls")
        print(f"  rclonepool serve")
        print(f"\nAdvanced features (v0.2-v1.0):")
        print(f"  rclonepool verify          # Verify file integrity")
        print(f"  rclonepool rebalance       # Rebalance storage")
        print(f"  rclonepool health          # Check file health")
        print(f"  rclonepool api             # Start REST API server")
        print(f"  rclonepool plugins list    # Manage plugins")
