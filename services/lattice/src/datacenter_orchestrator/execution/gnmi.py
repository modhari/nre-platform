"""
gNMI executor.

This executor applies ChangePlan actions using a gNMI shaped client.

Important
This file does not import a real gNMI library.
Instead it relies on a small GnmiClient interface so you can plug in any
implementation later.

Behavior
For each device in the plan:
1) Read pre snapshot for exactly the paths we intend to modify
2) Apply updates using set_update
3) Read observed state for the same paths and return it

This is vendor agnostic because the paths are OpenConfig model paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from datacenter_orchestrator.core.types import ChangePlan
from datacenter_orchestrator.execution.base import ExecutorConfig, GnmiClientFactory, PlanExecutor
from datacenter_orchestrator.state.snapshot import collect_paths_observed, collect_paths_snapshot


@dataclass
class GnmiExecutor(PlanExecutor):
    """
    gNMI based plan executor.

    client_factory
    Creates clients by device name. A real factory can use inventory to map
    device name to host and port.

    config
    Controls whether we read after write.
    """

    client_factory: GnmiClientFactory
    config: ExecutorConfig = ExecutorConfig()

    def apply_plan(
        self,
        plan: ChangePlan,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        """
        Apply a ChangePlan via gNMI.

        Returns
        observed_state: device to path to value after apply
        pre_snapshot: device to path to value before apply
        """

        observed_state: dict[str, dict[str, Any]] = {}
        pre_snapshot: dict[str, dict[str, Any]] = {}

        for action in plan.actions:
            device = action.device
            paths = [str(p) for p in action.model_paths.keys()]

            client = self.client_factory.for_device(device)

            before = collect_paths_snapshot(client, paths)
            pre_snapshot[device] = before

            client.set_update(action.model_paths)

            if self.config.read_after_write:
                after = collect_paths_observed(client, paths)
            else:
                after = dict(action.model_paths)

            observed_state[device] = after

        return observed_state, pre_snapshot
