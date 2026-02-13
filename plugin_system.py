"""
Plugin system for rclonepool.
Part of v1.0 Production Ready features.

Provides:
- Extensible plugin architecture
- Custom balancing strategies
- Custom chunking strategies
- Event hooks
- Plugin discovery and loading
"""

import os
import sys
import importlib
import importlib.util
import logging
import inspect
from typing import Dict, List, Optional, Any, Callable, Type
from dataclasses import dataclass
from enum import Enum
from abc import ABC, abstractmethod

log = logging.getLogger("rclonepool")


class PluginType(Enum):
    """Plugin types."""

    BALANCER = "balancer"
    CHUNKER = "chunker"
    STORAGE_BACKEND = "storage_backend"
    COMPRESSION = "compression"
    ENCRYPTION = "encryption"
    EVENT_HANDLER = "event_handler"
    TRANSFORMER = "transformer"


class PluginHook(Enum):
    """Event hooks for plugins."""

    PRE_UPLOAD = "pre_upload"
    POST_UPLOAD = "post_upload"
    PRE_DOWNLOAD = "pre_download"
    POST_DOWNLOAD = "post_download"
    PRE_DELETE = "pre_delete"
    POST_DELETE = "post_delete"
    PRE_CHUNK = "pre_chunk"
    POST_CHUNK = "post_chunk"
    PRE_BALANCE = "pre_balance"
    POST_BALANCE = "post_balance"
    FILE_VERIFIED = "file_verified"
    FILE_REPAIRED = "file_repaired"
    CHUNK_MISSING = "chunk_missing"
    REMOTE_ERROR = "remote_error"


@dataclass
class PluginMetadata:
    """Plugin metadata."""

    name: str
    version: str
    author: str
    description: str
    plugin_type: PluginType
    dependencies: List[str] = None
    enabled: bool = True

    def __post_init__(self):
        if self.dependencies is None:
            self.dependencies = []


class Plugin(ABC):
    """Base class for all plugins."""

    @abstractmethod
    def get_metadata(self) -> PluginMetadata:
        """
        Get plugin metadata.

        Returns:
            PluginMetadata object
        """
        pass

    @abstractmethod
    def initialize(self, config: dict):
        """
        Initialize plugin with configuration.

        Args:
            config: Plugin configuration
        """
        pass

    def cleanup(self):
        """Cleanup plugin resources."""
        pass


class BalancerPlugin(Plugin):
    """Base class for balancer plugins."""

    @abstractmethod
    def select_remote(self, remotes: List[dict], chunk_size: int) -> str:
        """
        Select a remote for the next chunk.

        Args:
            remotes: List of available remotes with usage info
            chunk_size: Size of chunk to be uploaded

        Returns:
            Remote name
        """
        pass


class ChunkerPlugin(Plugin):
    """Base class for chunker plugins."""

    @abstractmethod
    def calculate_chunk_size(self, file_size: int, file_type: str) -> int:
        """
        Calculate optimal chunk size for a file.

        Args:
            file_size: Size of file in bytes
            file_type: MIME type or file extension

        Returns:
            Chunk size in bytes
        """
        pass

    @abstractmethod
    def split_strategy(self, file_path: str, chunk_size: int) -> List[tuple]:
        """
        Define how to split a file.

        Args:
            file_path: Path to file
            chunk_size: Size of chunks

        Returns:
            List of (offset, length) tuples
        """
        pass


class EventHandlerPlugin(Plugin):
    """Base class for event handler plugins."""

    @abstractmethod
    def handle_event(self, hook: PluginHook, context: dict) -> Optional[dict]:
        """
        Handle an event.

        Args:
            hook: Event hook
            context: Event context data

        Returns:
            Modified context or None
        """
        pass


class TransformerPlugin(Plugin):
    """Base class for data transformer plugins."""

    @abstractmethod
    def transform_upload(self, data: bytes, metadata: dict) -> bytes:
        """
        Transform data before upload.

        Args:
            data: Original data
            metadata: File metadata

        Returns:
            Transformed data
        """
        pass

    @abstractmethod
    def transform_download(self, data: bytes, metadata: dict) -> bytes:
        """
        Transform data after download.

        Args:
            data: Downloaded data
            metadata: File metadata

        Returns:
            Original data
        """
        pass


class PluginRegistry:
    """Registry for managing plugins."""

    def __init__(self):
        """Initialize plugin registry."""
        self._plugins: Dict[str, Plugin] = {}
        self._plugins_by_type: Dict[PluginType, List[Plugin]] = {
            ptype: [] for ptype in PluginType
        }
        self._hooks: Dict[PluginHook, List[Plugin]] = {hook: [] for hook in PluginHook}
        self._enabled_plugins: set = set()

    def register(self, plugin: Plugin) -> bool:
        """
        Register a plugin.

        Args:
            plugin: Plugin instance

        Returns:
            True if registration succeeded
        """
        try:
            metadata = plugin.get_metadata()
            plugin_id = f"{metadata.plugin_type.value}:{metadata.name}"

            if plugin_id in self._plugins:
                log.warning(f"Plugin already registered: {plugin_id}")
                return False

            # Check dependencies
            if not self._check_dependencies(metadata.dependencies):
                log.error(f"Plugin dependencies not met: {plugin_id}")
                return False

            self._plugins[plugin_id] = plugin
            self._plugins_by_type[metadata.plugin_type].append(plugin)

            # Register event handlers
            if isinstance(plugin, EventHandlerPlugin):
                for hook in PluginHook:
                    self._hooks[hook].append(plugin)

            if metadata.enabled:
                self._enabled_plugins.add(plugin_id)

            log.info(
                f"Registered plugin: {metadata.name} v{metadata.version} "
                f"(type: {metadata.plugin_type.value})"
            )
            return True

        except Exception as e:
            log.error(f"Failed to register plugin: {e}")
            return False

    def unregister(self, plugin_id: str) -> bool:
        """
        Unregister a plugin.

        Args:
            plugin_id: Plugin identifier

        Returns:
            True if unregistration succeeded
        """
        if plugin_id not in self._plugins:
            return False

        plugin = self._plugins[plugin_id]
        metadata = plugin.get_metadata()

        # Remove from type registry
        if plugin in self._plugins_by_type[metadata.plugin_type]:
            self._plugins_by_type[metadata.plugin_type].remove(plugin)

        # Remove from hooks
        if isinstance(plugin, EventHandlerPlugin):
            for hook in PluginHook:
                if plugin in self._hooks[hook]:
                    self._hooks[hook].remove(plugin)

        # Cleanup plugin
        try:
            plugin.cleanup()
        except Exception as e:
            log.warning(f"Error during plugin cleanup: {e}")

        del self._plugins[plugin_id]
        self._enabled_plugins.discard(plugin_id)

        log.info(f"Unregistered plugin: {plugin_id}")
        return True

    def get_plugin(self, plugin_id: str) -> Optional[Plugin]:
        """
        Get a plugin by ID.

        Args:
            plugin_id: Plugin identifier

        Returns:
            Plugin instance or None
        """
        return self._plugins.get(plugin_id)

    def get_plugins_by_type(self, plugin_type: PluginType) -> List[Plugin]:
        """
        Get all plugins of a specific type.

        Args:
            plugin_type: Plugin type

        Returns:
            List of plugins
        """
        return [
            p for p in self._plugins_by_type.get(plugin_type, []) if self._is_enabled(p)
        ]

    def enable_plugin(self, plugin_id: str):
        """
        Enable a plugin.

        Args:
            plugin_id: Plugin identifier
        """
        if plugin_id in self._plugins:
            self._enabled_plugins.add(plugin_id)
            log.info(f"Enabled plugin: {plugin_id}")

    def disable_plugin(self, plugin_id: str):
        """
        Disable a plugin.

        Args:
            plugin_id: Plugin identifier
        """
        self._enabled_plugins.discard(plugin_id)
        log.info(f"Disabled plugin: {plugin_id}")

    def trigger_hook(self, hook: PluginHook, context: dict) -> dict:
        """
        Trigger an event hook.

        Args:
            hook: Event hook
            context: Event context

        Returns:
            Modified context
        """
        for plugin in self._hooks.get(hook, []):
            if self._is_enabled(plugin):
                try:
                    result = plugin.handle_event(hook, context)
                    if result is not None:
                        context = result
                except Exception as e:
                    log.error(f"Error in plugin event handler: {e}")

        return context

    def list_plugins(self) -> List[dict]:
        """
        List all registered plugins.

        Returns:
            List of plugin info dicts
        """
        plugins_info = []

        for plugin_id, plugin in self._plugins.items():
            metadata = plugin.get_metadata()
            plugins_info.append(
                {
                    "id": plugin_id,
                    "name": metadata.name,
                    "version": metadata.version,
                    "author": metadata.author,
                    "description": metadata.description,
                    "type": metadata.plugin_type.value,
                    "enabled": plugin_id in self._enabled_plugins,
                    "dependencies": metadata.dependencies,
                }
            )

        return plugins_info

    def _is_enabled(self, plugin: Plugin) -> bool:
        """
        Check if a plugin is enabled.

        Args:
            plugin: Plugin instance

        Returns:
            True if enabled
        """
        metadata = plugin.get_metadata()
        plugin_id = f"{metadata.plugin_type.value}:{metadata.name}"
        return plugin_id in self._enabled_plugins

    def _check_dependencies(self, dependencies: List[str]) -> bool:
        """
        Check if plugin dependencies are met.

        Args:
            dependencies: List of required dependencies

        Returns:
            True if all dependencies are met
        """
        if not dependencies:
            return True

        for dep in dependencies:
            try:
                importlib.import_module(dep)
            except ImportError:
                log.error(f"Missing dependency: {dep}")
                return False

        return True


class PluginLoader:
    """Loads plugins from files and directories."""

    def __init__(self, registry: PluginRegistry):
        """
        Initialize plugin loader.

        Args:
            registry: PluginRegistry instance
        """
        self.registry = registry

    def load_plugin_file(self, file_path: str, config: dict = None) -> bool:
        """
        Load a plugin from a Python file.

        Args:
            file_path: Path to plugin file
            config: Plugin configuration

        Returns:
            True if loading succeeded
        """
        if not os.path.exists(file_path):
            log.error(f"Plugin file not found: {file_path}")
            return False

        try:
            # Load module from file
            module_name = os.path.splitext(os.path.basename(file_path))[0]
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            # Find plugin classes in module
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, Plugin) and obj is not Plugin:
                    # Instantiate and register plugin
                    plugin = obj()
                    plugin.initialize(config or {})

                    if self.registry.register(plugin):
                        log.info(f"Loaded plugin from {file_path}")
                        return True

            log.warning(f"No plugin class found in {file_path}")
            return False

        except Exception as e:
            log.error(f"Failed to load plugin from {file_path}: {e}")
            return False

    def load_plugins_from_directory(self, directory: str, config: dict = None) -> int:
        """
        Load all plugins from a directory.

        Args:
            directory: Path to plugins directory
            config: Plugin configuration

        Returns:
            Number of plugins loaded
        """
        if not os.path.isdir(directory):
            log.error(f"Plugins directory not found: {directory}")
            return 0

        loaded_count = 0

        for filename in os.listdir(directory):
            if filename.endswith(".py") and not filename.startswith("_"):
                file_path = os.path.join(directory, filename)
                if self.load_plugin_file(file_path, config):
                    loaded_count += 1

        log.info(f"Loaded {loaded_count} plugins from {directory}")
        return loaded_count

    def discover_plugins(self, search_paths: List[str], config: dict = None) -> int:
        """
        Discover and load plugins from multiple paths.

        Args:
            search_paths: List of paths to search
            config: Plugin configuration

        Returns:
            Number of plugins loaded
        """
        total_loaded = 0

        for path in search_paths:
            if os.path.isfile(path):
                if self.load_plugin_file(path, config):
                    total_loaded += 1
            elif os.path.isdir(path):
                total_loaded += self.load_plugins_from_directory(path, config)

        return total_loaded


# Example plugin implementations


class RoundRobinBalancerPlugin(BalancerPlugin):
    """Example: Round-robin balancer plugin."""

    def __init__(self):
        self._index = 0
        self._config = {}

    def get_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="round_robin_balancer",
            version="1.0.0",
            author="rclonepool",
            description="Simple round-robin balancer",
            plugin_type=PluginType.BALANCER,
        )

    def initialize(self, config: dict):
        self._config = config

    def select_remote(self, remotes: List[dict], chunk_size: int) -> str:
        if not remotes:
            return None

        selected = remotes[self._index % len(remotes)]
        self._index += 1
        return selected["name"]


class AdaptiveChunkerPlugin(ChunkerPlugin):
    """Example: Adaptive chunker based on file type."""

    def __init__(self):
        self._config = {}

    def get_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="adaptive_chunker",
            version="1.0.0",
            author="rclonepool",
            description="Adaptive chunk size based on file type",
            plugin_type=PluginType.CHUNKER,
        )

    def initialize(self, config: dict):
        self._config = config

    def calculate_chunk_size(self, file_size: int, file_type: str) -> int:
        # Video files: larger chunks
        if file_type.startswith("video/"):
            return 200 * 1024 * 1024  # 200MB

        # Images: smaller chunks
        if file_type.startswith("image/"):
            return 50 * 1024 * 1024  # 50MB

        # Default
        return 100 * 1024 * 1024  # 100MB

    def split_strategy(self, file_path: str, chunk_size: int) -> List[tuple]:
        file_size = os.path.getsize(file_path)
        chunks = []
        offset = 0

        while offset < file_size:
            length = min(chunk_size, file_size - offset)
            chunks.append((offset, length))
            offset += length

        return chunks


class LoggingEventHandlerPlugin(EventHandlerPlugin):
    """Example: Event logging plugin."""

    def __init__(self):
        self._config = {}

    def get_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="logging_event_handler",
            version="1.0.0",
            author="rclonepool",
            description="Logs all events",
            plugin_type=PluginType.EVENT_HANDLER,
        )

    def initialize(self, config: dict):
        self._config = config

    def handle_event(self, hook: PluginHook, context: dict) -> Optional[dict]:
        log.info(f"Event: {hook.value} - Context: {context}")
        return context
