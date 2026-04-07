"""
Static intent source.

Reads a local json file containing either:
1) a single intent object
2) or a list of intent objects under "intents"

Schema example
{
  "intents": [
    {
      "change_id": "c1",
      "scope": "fabric",
      "desired": {"actions": [{"device": "leaf1", "model_paths": {"/path": 1}}]},
      "current": {},
      "diff_summary": "demo"
    }
  ]
}
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from datacenter_orchestrator.core.types import IntentChange
from datacenter_orchestrator.intent.base import IntentSource


def _intent_from_dict(obj: dict[str, Any]) -> IntentChange:
    """Convert a dict into IntentChange."""
    return IntentChange(
        change_id=str(obj.get("change_id", "")),
        scope=str(obj.get("scope", "")),
        desired=dict(obj.get("desired", {}) or {}),
        current=dict(obj.get("current", {}) or {}),
        diff_summary=str(obj.get("diff_summary", "")),
    )


@dataclass(frozen=True)
class StaticIntentSource(IntentSource):
    """Load intents from a local json file."""

    path: Path

    def fetch(self) -> list[IntentChange]:
        data = json.loads(self.path.read_text(encoding="utf-8"))

        if isinstance(data, dict) and "intents" in data:
            raw = data.get("intents", [])
            if isinstance(raw, list):
                return [_intent_from_dict(x) for x in raw if isinstance(x, dict)]
            return []

        if isinstance(data, dict):
            return [_intent_from_dict(data)]

        return []
