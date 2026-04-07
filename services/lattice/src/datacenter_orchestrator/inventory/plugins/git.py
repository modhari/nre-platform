"""
Git inventory plugin.

This plugin reads inventory from a local git working directory.
It does not require network access. It simply reads a file path inside a repo.

You can optionally run a git pull outside this process.
Keeping git operations outside makes this safer and more predictable.

Default file
inventory.json at repo root, but configurable.

Format
Same as StaticInventoryPlugin.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from datacenter_orchestrator.inventory.plugins.base import InventoryPlugin
from datacenter_orchestrator.inventory.plugins.static import StaticInventoryPlugin
from datacenter_orchestrator.inventory.store import InventoryStore


@dataclass(frozen=True)
class GitInventoryPlugin(InventoryPlugin):
    """
    Load inventory from a json file inside a local git working directory.
    """

    repo_dir: Path
    inventory_relpath: Path = Path("inventory.json")

    def load(self) -> InventoryStore:
        inv_path = self.repo_dir / self.inventory_relpath
        return StaticInventoryPlugin(path=inv_path).load()
