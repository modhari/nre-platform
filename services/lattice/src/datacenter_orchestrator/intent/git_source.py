"""
Git intent source.

Reads intent json files from a local git working directory.

Default folder
intents directory at repo root. Each json file is one IntentChange.

This is a basic GitOps style workflow:
Users commit an intent file, the runner reads it, runs it, then later you can
extend this to mark it done by writing a status file or creating a commit.

We do not modify git state in this checkin.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from datacenter_orchestrator.core.types import IntentChange
from datacenter_orchestrator.intent.base import IntentSource
from datacenter_orchestrator.intent.static_source import StaticIntentSource


@dataclass(frozen=True)
class GitIntentSource(IntentSource):
    """
    Load intents from json files inside a local git working directory.
    """

    repo_dir: Path
    intents_rel_dir: Path = Path("intents")

    def fetch(self) -> list[IntentChange]:
        intents_dir = self.repo_dir / self.intents_rel_dir
        if not intents_dir.exists():
            return []

        intents: list[IntentChange] = []
        for p in sorted(intents_dir.glob("*.json")):
            intents.extend(StaticIntentSource(path=p).fetch())

        return intents
