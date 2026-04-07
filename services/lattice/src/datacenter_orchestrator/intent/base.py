"""
Intent source interfaces.

Goal
Provide pluggable intent ingestion.

Intent sources return IntentChange objects, which the engine can execute.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from datacenter_orchestrator.core.types import IntentChange


class IntentSource(Protocol):
    """
    Intent source interface.

    fetch returns a list of IntentChange objects.
    A source may return an empty list when there are no new intents.
    """

    def fetch(self) -> list[IntentChange]:
        """Fetch new intents."""


@dataclass(frozen=True)
class IntentFetchResult:
    """
    Optional result type if you want evidence.

    intents are the normalized intents.
    evidence contains structured metadata such as file names.
    """

    intents: list[IntentChange]
    evidence: dict[str, object]
