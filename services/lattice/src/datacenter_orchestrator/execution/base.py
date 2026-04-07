"""
Execution interfaces.

Goal
Define stable interfaces for plan execution without binding the engine to a
specific vendor or transport.

Design notes
The engine expects apply_plan to return:
1) observed_state: device to path to value after apply
2) pre_snapshot: device to path to value before apply

This makes rollback deterministic and auditable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from datacenter_orchestrator.core.types import ChangePlan


class GnmiClient(Protocol):
    """
    Minimal gNMI shaped client interface.

    Real implementations will wrap a real gNMI library.
    We keep the interface narrow for testability.

    get
    Returns a mapping of requested paths to their current values.

    set_update
    Applies updates for the provided paths.
    """

    def get(self, paths: list[str]) -> dict[str, Any]:
        """Read device state for a list of model paths."""

    def set_update(self, updates: dict[str, Any]) -> None:
        """Apply updates for model paths."""


class GnmiClientFactory(Protocol):
    """
    Create a gNMI client for a device.

    This decouples the executor from transport details such as TLS, credentials,
    timeouts, and per vendor capabilities.
    """

    def for_device(self, device: str) -> GnmiClient:
        """Return a connected client for the given device name."""


@dataclass(frozen=True)
class ExecutorConfig:
    """
    Executor configuration.

    read_after_write
    If True we always do a get after set and return that as observed state.

    When False, a simple executor could assume the desired state is observed.
    For orchestration safety, default is True.
    """

    read_after_write: bool = True


class PlanExecutor(Protocol):
    """
    Execution interface expected by the orchestration engine.

    Return values
    observed_state: device to path to value after apply
    pre_snapshot: device to path to value before apply
    """

    def apply_plan(
        self,
        plan: ChangePlan,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        """Apply the plan and return observed and pre snapshot state."""
