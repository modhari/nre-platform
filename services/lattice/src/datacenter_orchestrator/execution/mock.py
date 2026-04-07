"""
In memory executor.

This executor is used for tests and local simulations.
It behaves like a device state database keyed by device name and model path.

Features
- Captures a pre snapshot for paths touched by the plan
- Applies updates into internal state
- Can inject mismatches into observed state for verification testing
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from datacenter_orchestrator.core.types import ChangePlan
from datacenter_orchestrator.execution.base import PlanExecutor


@dataclass
class InMemoryExecutor(PlanExecutor):
    """
    In memory executor.

    mismatch
    Optional mapping of device to path to value.
    When set, observed state will return the mismatch value even though
    internal state has the desired value.

    This simulates cases where the device did not converge or rejected config.
    """

    mismatch: dict[str, dict[str, Any]] = field(default_factory=dict)
    state: dict[str, dict[str, Any]] = field(default_factory=dict)

    def apply_plan(
        self,
        plan: ChangePlan,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        """
        Apply plan updates to internal state.

        Returns
        observed_state: internal state plus any mismatch injection
        pre_snapshot: values of touched paths before apply
        """

        observed_state: dict[str, dict[str, Any]] = {}
        pre_snapshot: dict[str, dict[str, Any]] = {}

        for action in plan.actions:
            device = action.device
            device_state = self.state.setdefault(device, {})
            device_pre: dict[str, Any] = {}
            device_obs: dict[str, Any] = {}

            for path in action.model_paths.keys():
                if path in device_state:
                    device_pre[path] = device_state[path]
                else:
                    device_pre[path] = None

            for path, value in action.model_paths.items():
                device_state[path] = value

            for path in action.model_paths.keys():
                device_obs[path] = device_state.get(path)

            if device in self.mismatch:
                for path, bad_value in self.mismatch[device].items():
                    device_obs[path] = bad_value

            pre_snapshot[device] = device_pre
            observed_state[device] = device_obs

        return observed_state, pre_snapshot
