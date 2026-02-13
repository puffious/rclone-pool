"""
Advanced balancing strategies for rclonepool.
Part of v0.4 Balancing features.

Provides:
- Multiple balancing strategies (least-used, round-robin, weighted, random)
- Rebalancing functionality
- Remote weight/priority configuration
- Auto-rebalance when new remote added
"""

import logging
import random
import time
from typing import List, Dict, Optional, Tuple
from enum import Enum
from dataclasses import dataclass

log = logging.getLogger("rclonepool")


class BalancingStrategy(Enum):
    """Available balancing strategies."""

    LEAST_USED = "least_used"
    ROUND_ROBIN = "round_robin"
    WEIGHTED = "weighted"
    RANDOM = "random"
    ROUND_ROBIN_LEAST_USED = "round_robin_least_used"


@dataclass
class RemoteInfo:
    """Information about a remote."""

    name: str
    used: int
    free: int
    total: int
    weight: float = 1.0
    priority: int = 0
    enabled: bool = True

    @property
    def utilization(self) -> float:
        """Get utilization percentage."""
        if self.total == 0:
            return 0.0
        return (self.used / self.total) * 100

    @property
    def available_space(self) -> int:
        """Get available space in bytes."""
        return self.free


class AdvancedBalancer:
    """Advanced balancer with multiple strategies."""

    def __init__(self, config, backend, strategy: BalancingStrategy = None):
        """
        Initialize advanced balancer.

        Args:
            config: RclonePool configuration
            backend: RcloneBackend instance
            strategy: Balancing strategy to use
        """
        self.config = config
        self.backend = backend
        self.strategy = strategy or BalancingStrategy.LEAST_USED
        self._remote_info: Dict[str, RemoteInfo] = {}
        self._round_robin_index = 0
        self._initialized = False
        self._weights = {}
        self._priorities = {}

    def set_strategy(self, strategy: BalancingStrategy):
        """
        Set the balancing strategy.

        Args:
            strategy: Strategy to use
        """
        self.strategy = strategy
        log.info(f"Balancing strategy set to: {strategy.value}")

    def set_remote_weight(self, remote: str, weight: float):
        """
        Set weight for a remote (used in weighted strategy).

        Args:
            remote: Remote name
            weight: Weight value (higher = more likely to be selected)
        """
        self._weights[remote] = weight
        if remote in self._remote_info:
            self._remote_info[remote].weight = weight
        log.info(f"Set weight for {remote}: {weight}")

    def set_remote_priority(self, remote: str, priority: int):
        """
        Set priority for a remote (higher priority = preferred).

        Args:
            remote: Remote name
            priority: Priority value
        """
        self._priorities[remote] = priority
        if remote in self._remote_info:
            self._remote_info[remote].priority = priority
        log.info(f"Set priority for {remote}: {priority}")

    def enable_remote(self, remote: str, enabled: bool = True):
        """
        Enable or disable a remote.

        Args:
            remote: Remote name
            enabled: Whether to enable the remote
        """
        if remote in self._remote_info:
            self._remote_info[remote].enabled = enabled
            log.info(f"Remote {remote} {'enabled' if enabled else 'disabled'}")

    def initialize(self):
        """Initialize remote information."""
        if self._initialized:
            return

        log.info("Initializing balancer with remote information...")

        for remote in self.config.remotes:
            used, free, total = self.backend.get_space(remote)

            weight = self._weights.get(remote, 1.0)
            priority = self._priorities.get(remote, 0)

            self._remote_info[remote] = RemoteInfo(
                name=remote,
                used=used,
                free=free,
                total=total,
                weight=weight,
                priority=priority,
                enabled=True,
            )

            log.info(
                f"  {remote}: {used:,} used, {free:,} free, "
                f"weight={weight}, priority={priority}"
            )

        self._initialized = True

    def get_next_remote(self) -> str:
        """
        Get the next remote to use based on current strategy.

        Returns:
            Remote name
        """
        self.initialize()

        # Filter enabled remotes
        enabled_remotes = [
            r for r in self._remote_info.values() if r.enabled and r.free > 0
        ]

        if not enabled_remotes:
            log.warning("No enabled remotes with free space available")
            return self.config.remotes[0]

        if self.strategy == BalancingStrategy.LEAST_USED:
            return self._least_used_strategy(enabled_remotes)
        elif self.strategy == BalancingStrategy.ROUND_ROBIN:
            return self._round_robin_strategy(enabled_remotes)
        elif self.strategy == BalancingStrategy.WEIGHTED:
            return self._weighted_strategy(enabled_remotes)
        elif self.strategy == BalancingStrategy.RANDOM:
            return self._random_strategy(enabled_remotes)
        elif self.strategy == BalancingStrategy.ROUND_ROBIN_LEAST_USED:
            return self._round_robin_least_used_strategy(enabled_remotes)
        else:
            return self._least_used_strategy(enabled_remotes)

    def record_usage(self, remote: str, bytes_added: int):
        """
        Update cached usage after uploading.

        Args:
            remote: Remote name
            bytes_added: Bytes added to remote
        """
        if remote in self._remote_info:
            self._remote_info[remote].used += bytes_added
            self._remote_info[remote].free -= bytes_added

    def get_usage_report(self) -> Dict[str, dict]:
        """
        Get detailed usage report for all remotes.

        Returns:
            Dict mapping remote names to usage info
        """
        self.initialize()

        report = {}
        for remote, info in self._remote_info.items():
            report[remote] = {
                "used": info.used,
                "free": info.free,
                "total": info.total,
                "utilization": info.utilization,
                "weight": info.weight,
                "priority": info.priority,
                "enabled": info.enabled,
            }

        return report

    def _least_used_strategy(self, remotes: List[RemoteInfo]) -> str:
        """
        Select remote with least used space.

        Args:
            remotes: List of available remotes

        Returns:
            Remote name
        """
        # Sort by priority (descending), then by used space (ascending)
        sorted_remotes = sorted(remotes, key=lambda r: (-r.priority, r.used, r.name))
        selected = sorted_remotes[0]
        log.debug(f"Least-used strategy selected: {selected.name}")
        return selected.name

    def _round_robin_strategy(self, remotes: List[RemoteInfo]) -> str:
        """
        Select remote in round-robin fashion.

        Args:
            remotes: List of available remotes

        Returns:
            Remote name
        """
        # Sort by priority first, then round-robin within same priority
        sorted_remotes = sorted(remotes, key=lambda r: (-r.priority, r.name))

        selected = sorted_remotes[self._round_robin_index % len(sorted_remotes)]
        self._round_robin_index += 1

        log.debug(f"Round-robin strategy selected: {selected.name}")
        return selected.name

    def _weighted_strategy(self, remotes: List[RemoteInfo]) -> str:
        """
        Select remote based on weights (higher weight = more likely).

        Args:
            remotes: List of available remotes

        Returns:
            Remote name
        """
        # Sort by priority first
        sorted_remotes = sorted(remotes, key=lambda r: -r.priority)

        # Get highest priority
        highest_priority = sorted_remotes[0].priority

        # Filter to only highest priority remotes
        priority_remotes = [r for r in sorted_remotes if r.priority == highest_priority]

        # Calculate weighted selection
        total_weight = sum(r.weight for r in priority_remotes)
        if total_weight == 0:
            return priority_remotes[0].name

        rand_val = random.uniform(0, total_weight)
        cumulative = 0

        for remote in priority_remotes:
            cumulative += remote.weight
            if rand_val <= cumulative:
                log.debug(f"Weighted strategy selected: {remote.name}")
                return remote.name

        # Fallback
        return priority_remotes[0].name

    def _random_strategy(self, remotes: List[RemoteInfo]) -> str:
        """
        Select remote randomly.

        Args:
            remotes: List of available remotes

        Returns:
            Remote name
        """
        # Sort by priority first
        sorted_remotes = sorted(remotes, key=lambda r: -r.priority)

        # Get highest priority
        highest_priority = sorted_remotes[0].priority

        # Filter to only highest priority remotes
        priority_remotes = [r for r in sorted_remotes if r.priority == highest_priority]

        selected = random.choice(priority_remotes)
        log.debug(f"Random strategy selected: {selected.name}")
        return selected.name

    def _round_robin_least_used_strategy(self, remotes: List[RemoteInfo]) -> str:
        """
        Round-robin with least-used tiebreaker.

        Args:
            remotes: List of available remotes

        Returns:
            Remote name
        """
        # Sort by priority first
        sorted_remotes = sorted(remotes, key=lambda r: (-r.priority, r.name))

        # Get highest priority
        highest_priority = sorted_remotes[0].priority

        # Filter to only highest priority remotes
        priority_remotes = [r for r in sorted_remotes if r.priority == highest_priority]

        # Round-robin selection
        selected = priority_remotes[self._round_robin_index % len(priority_remotes)]
        self._round_robin_index += 1

        # Check if there's a significantly less-used remote (>10% difference)
        least_used = min(priority_remotes, key=lambda r: r.utilization)
        if (selected.utilization - least_used.utilization) > 10.0:
            log.debug(
                f"Round-robin selected {selected.name}, but switching to "
                f"least-used {least_used.name} (utilization difference: "
                f"{selected.utilization - least_used.utilization:.1f}%)"
            )
            selected = least_used

        log.debug(f"Round-robin-least-used strategy selected: {selected.name}")
        return selected.name


class Rebalancer:
    """Handles rebalancing of chunks across remotes."""

    def __init__(self, config, backend, manifest_mgr, chunker):
        """
        Initialize rebalancer.

        Args:
            config: RclonePool configuration
            backend: RcloneBackend instance
            manifest_mgr: ManifestManager instance
            chunker: Chunker instance
        """
        self.config = config
        self.backend = backend
        self.manifest_mgr = manifest_mgr
        self.chunker = chunker

    def analyze_balance(self) -> Dict[str, any]:
        """
        Analyze current balance across remotes.

        Returns:
            Dict with balance analysis
        """
        log.info("Analyzing balance across remotes...")

        remote_usage = {}
        for remote in self.config.remotes:
            used, free, total = self.backend.get_space(remote)
            remote_usage[remote] = {
                "used": used,
                "free": free,
                "total": total,
                "utilization": (used / total * 100) if total > 0 else 0,
                "chunk_count": 0,
            }

        # Count chunks per remote
        manifests = self.manifest_mgr.list_manifests("/", recursive=True)
        for manifest in manifests:
            for chunk in manifest.get("chunks", []):
                remote = chunk.get("remote")
                if remote in remote_usage:
                    remote_usage[remote]["chunk_count"] += 1

        # Calculate balance metrics
        utilizations = [r["utilization"] for r in remote_usage.values()]
        avg_utilization = sum(utilizations) / len(utilizations) if utilizations else 0
        max_utilization = max(utilizations) if utilizations else 0
        min_utilization = min(utilizations) if utilizations else 0
        balance_variance = max_utilization - min_utilization

        analysis = {
            "remote_usage": remote_usage,
            "avg_utilization": avg_utilization,
            "max_utilization": max_utilization,
            "min_utilization": min_utilization,
            "balance_variance": balance_variance,
            "is_balanced": balance_variance < 10.0,  # Within 10% is considered balanced
        }

        log.info(f"  Average utilization: {avg_utilization:.1f}%")
        log.info(f"  Balance variance: {balance_variance:.1f}%")
        log.info(f"  Status: {'Balanced' if analysis['is_balanced'] else 'Unbalanced'}")

        return analysis

    def rebalance(
        self, target_variance: float = 5.0, dry_run: bool = False
    ) -> Dict[str, any]:
        """
        Rebalance chunks across remotes.

        Args:
            target_variance: Target variance in utilization percentage
            dry_run: If True, only simulate rebalancing

        Returns:
            Dict with rebalancing results
        """
        log.info(
            f"Starting rebalance (target variance: {target_variance}%, dry_run: {dry_run})..."
        )

        analysis = self.analyze_balance()

        if analysis["is_balanced"]:
            log.info("Pool is already balanced, no action needed")
            return {"status": "already_balanced", "moves": []}

        # Identify over-utilized and under-utilized remotes
        avg_util = analysis["avg_utilization"]
        over_utilized = []
        under_utilized = []

        for remote, info in analysis["remote_usage"].items():
            if info["utilization"] > avg_util + target_variance:
                over_utilized.append((remote, info))
            elif info["utilization"] < avg_util - target_variance:
                under_utilized.append((remote, info))

        log.info(f"  Over-utilized remotes: {len(over_utilized)}")
        log.info(f"  Under-utilized remotes: {len(under_utilized)}")

        if not over_utilized or not under_utilized:
            log.info("No rebalancing needed")
            return {"status": "no_action_needed", "moves": []}

        # Plan chunk moves
        moves = self._plan_moves(over_utilized, under_utilized, analysis)

        log.info(f"  Planned {len(moves)} chunk moves")

        if dry_run:
            log.info("Dry run - no actual moves performed")
            return {"status": "dry_run", "moves": moves}

        # Execute moves
        executed_moves = self._execute_moves(moves)

        log.info(f"Rebalancing complete: {len(executed_moves)} chunks moved")

        return {"status": "completed", "moves": executed_moves}

    def _plan_moves(
        self,
        over_utilized: List[Tuple[str, dict]],
        under_utilized: List[Tuple[str, dict]],
        analysis: dict,
    ) -> List[dict]:
        """
        Plan which chunks to move.

        Args:
            over_utilized: List of over-utilized remotes
            under_utilized: List of under-utilized remotes
            analysis: Balance analysis

        Returns:
            List of move plans
        """
        moves = []

        # Get all manifests
        manifests = self.manifest_mgr.list_manifests("/", recursive=True)

        # For each over-utilized remote, find chunks to move
        for source_remote, source_info in over_utilized:
            # Find chunks on this remote
            chunks_on_remote = []
            for manifest in manifests:
                for chunk in manifest.get("chunks", []):
                    if chunk.get("remote") == source_remote:
                        chunks_on_remote.append(
                            {
                                "manifest": manifest,
                                "chunk": chunk,
                            }
                        )

            # Sort by size (move larger chunks first for efficiency)
            chunks_on_remote.sort(key=lambda x: x["chunk"]["size"], reverse=True)

            # Plan moves to under-utilized remotes
            for chunk_info in chunks_on_remote:
                if not under_utilized:
                    break

                # Select target remote (least utilized)
                target_remote, target_info = min(
                    under_utilized, key=lambda x: x[1]["utilization"]
                )

                moves.append(
                    {
                        "file_path": chunk_info["manifest"]["file_path"],
                        "chunk_index": chunk_info["chunk"]["index"],
                        "source_remote": source_remote,
                        "target_remote": target_remote,
                        "chunk_path": chunk_info["chunk"]["path"],
                        "size": chunk_info["chunk"]["size"],
                    }
                )

                # Update simulated utilization
                source_info["used"] -= chunk_info["chunk"]["size"]
                target_info["used"] += chunk_info["chunk"]["size"]
                source_info["utilization"] = (
                    (source_info["used"] / source_info["total"] * 100)
                    if source_info["total"] > 0
                    else 0
                )
                target_info["utilization"] = (
                    (target_info["used"] / target_info["total"] * 100)
                    if target_info["total"] > 0
                    else 0
                )

                # Check if we've balanced enough
                if abs(source_info["utilization"] - target_info["utilization"]) < 5.0:
                    break

        return moves

    def _execute_moves(self, moves: List[dict]) -> List[dict]:
        """
        Execute planned chunk moves.

        Args:
            moves: List of move plans

        Returns:
            List of executed moves
        """
        executed = []

        for move in moves:
            log.info(
                f"  Moving chunk {move['chunk_index']} of {move['file_path']} "
                f"from {move['source_remote']} to {move['target_remote']}"
            )

            try:
                # Download chunk from source
                data = self.backend.download_bytes(
                    move["source_remote"], move["chunk_path"], suppress_errors=True
                )

                if not data:
                    log.error(
                        f"  Failed to download chunk from {move['source_remote']}"
                    )
                    continue

                # Upload to target
                success = self.backend.upload_bytes(
                    data, move["target_remote"], move["chunk_path"]
                )

                if not success:
                    log.error(f"  Failed to upload chunk to {move['target_remote']}")
                    continue

                # Delete from source
                self.backend.delete_file(move["source_remote"], move["chunk_path"])

                # Update manifest
                manifest = self.manifest_mgr.load_manifest_for_file(move["file_path"])
                if manifest:
                    for chunk in manifest["chunks"]:
                        if chunk["index"] == move["chunk_index"]:
                            chunk["remote"] = move["target_remote"]
                            break
                    self.manifest_mgr.save_manifest(manifest)

                executed.append(move)
                log.info(f"  ✓ Chunk moved successfully")

            except Exception as e:
                log.error(f"  Error moving chunk: {e}")
                continue

        return executed
