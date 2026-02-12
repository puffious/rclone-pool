"""
Configuration management for rclonepool.
"""

# rclonepool/config.py

import json
import os
import sys
import logging

log = logging.getLogger('rclonepool')

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
    "webdav_host": "0.0.0.0"
}


class Config:
    def __init__(self, config_path: str = None):
        if config_path:
            self.config_path = os.path.expanduser(config_path)
        else:
            self.config_path = os.path.expanduser('~/.config/rclonepool/config.json')

        self._data = dict(DEFAULT_CONFIG)

        if os.path.exists(self.config_path):
            with open(self.config_path, 'r') as f:
                user_config = json.load(f)
                self._data.update(user_config)
            log.info(f"Loaded config from {self.config_path}")
        else:
            log.warning(f"No config found at {self.config_path}, using defaults")
            log.warning(f"Run 'rclonepool init' to create a config")

    @property
    def remotes(self) -> list:
        """Get the list of remotes to use (crypt remotes if encryption enabled)."""
        if self._data['use_crypt'] and self._data.get('crypt_remotes'):
            return self._data['crypt_remotes']
        return self._data['remotes']

    @property
    def base_remotes(self) -> list:
        """Get the base (non-crypt) remotes."""
        return self._data['remotes']

    @property
    def chunk_size(self) -> int:
        return self._data['chunk_size']

    @property
    def data_prefix(self) -> str:
        return self._data['data_prefix']

    @property
    def manifest_prefix(self) -> str:
        return self._data['manifest_prefix']

    @property
    def temp_dir(self) -> str:
        return self._data['temp_dir']

    @property
    def rclone_binary(self) -> str:
        return self._data['rclone_binary']

    @property
    def rclone_flags(self) -> list:
        return self._data['rclone_flags']

    @property
    def use_crypt(self) -> bool:
        return self._data['use_crypt']

    def save(self):
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, 'w') as f:
            json.dump(self._data, f, indent=2)
        log.info(f"Config saved to {self.config_path}")

    @staticmethod
    def init_interactive():
        """Interactive config initialization."""
        print("=== rclonepool Configuration ===\n")

        config_path = os.path.expanduser('~/.config/rclonepool/config.json')
        print(f"Config will be saved to: {config_path}\n")

        # Get remotes
        print("Enter your rclone remote names (the base MEGA remotes).")
        print("Example: mega1 mega2 mega3 mega4 mega5")
        remotes_input = input("Remotes (space-separated): ").strip()
        remotes = [r.strip().rstrip(':') + ':' for r in remotes_input.split()]

        if not remotes:
            print("Error: No remotes provided!")
            sys.exit(1)

        # Encryption
        use_crypt = input("\nUse encryption? (rclone crypt) [Y/n]: ").strip().lower()
        use_crypt = use_crypt != 'n'

        crypt_remotes = []
        if use_crypt:
            print(f"\nFor encryption, you need crypt remotes wrapping each base remote.")
            print(f"Expected crypt remote names:")
            for r in remotes:
                name = r.rstrip(':')
                print(f"  crypt-{name}:")
            print(f"\nDo these crypt remotes already exist in your rclone.conf?")
            existing = input("[Y/n]: ").strip().lower()
            if existing == 'n':
                print(f"\nPlease create them first. For each remote, run:")
                for r in remotes:
                    name = r.rstrip(':')
                    print(f"  rclone config create crypt-{name} crypt remote={r}encrypted password=<pass> password2=<salt>")
                print(f"\nThen run 'rclonepool init' again.")
                sys.exit(0)
            crypt_remotes = [f"crypt-{r.rstrip(':')}:" for r in remotes]

        # Chunk size
        chunk_input = input("\nChunk size in MB [100]: ").strip()
        chunk_size = int(chunk_input) * 1024 * 1024 if chunk_input else 100 * 1024 * 1024

        # Temp dir
        print(f"\nTemp directory for chunk operations (use /dev/shm for RAM-based):")
        temp_dir = input(f"Temp dir [/dev/shm/rclonepool]: ").strip() or "/dev/shm/rclonepool"

        config = dict(DEFAULT_CONFIG)
        config['remotes'] = remotes
        config['use_crypt'] = use_crypt
        config['crypt_remotes'] = crypt_remotes
        config['chunk_size'] = chunk_size
        config['temp_dir'] = temp_dir

        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)

        print(f"\n✓ Config saved to {config_path}")
        print(f"\nYou can now use:")
        print(f"  rclonepool upload <file> <remote_path>")
        print(f"  rclonepool ls")
        print(f"  rclonepool serve")