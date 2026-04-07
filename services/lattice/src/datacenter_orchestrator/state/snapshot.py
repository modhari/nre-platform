"""
Snapshot helpers.

These helpers operate on a client interface rather than a transport library.
They are shared by real executors and test doubles.
"""

from __future__ import annotations

from typing import Any

from datacenter_orchestrator.execution.base import GnmiClient


def collect_paths_snapshot(
    client: GnmiClient,
    paths: list[str],
) -> dict[str, Any]:
    """
    Collect a snapshot for a set of paths.

    We return a dict mapping each requested path to a value.
    If the client omits a path, we keep it absent rather than inventing None.

    That preserves information about missing telemetry.
    """
    if not paths:
        return {}

    return client.get(paths)


def collect_paths_observed(
    client: GnmiClient,
    paths: list[str],
) -> dict[str, Any]:
    """
    Collect observed state for a set of paths after apply.

    This is the same operation as snapshot today, but keeping it separate makes
    future changes easier such as retries or convergence waiting.
    """
    if not paths:
        return {}

    return client.get(paths)
