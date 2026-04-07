"""
Rollback builder.

Purpose
If verification fails, we need a safe path back to the prior state.
This module builds a rollback ChangePlan using a pre change snapshot.

Snapshot format
pre_snapshot is a dict:
  device name -> dict of model path -> value

We only rollback the paths that were modified by the original plan.
This keeps rollback minimal and reduces blast radius.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from datacenter_orchestrator.core.types import (
    ChangeAction,
    ChangePlan,
    RollbackSpec,
    VerificationSpec,
)


@dataclass
class RollbackBuildResult:
    """
    Output of rollback construction.

    plan
    A ChangePlan intended to restore pre change values.

    missing_paths
    Paths that were in the original plan but missing from the snapshot.
    Those paths cannot be rolled back reliably.
    """

    plan: ChangePlan
    missing_paths: list[str]


def build_rollback_plan(
    original_plan: ChangePlan,
    pre_snapshot: dict[str, dict[str, Any]],
) -> RollbackBuildResult:
    """
    Build a rollback plan from the original plan and the pre change snapshot.

    We keep verification for rollback minimal.
    A rollback should verify that rolled back paths match snapshot values.
    """

    rollback_actions: list[ChangeAction] = []
    missing: list[str] = []

    for act in original_plan.actions:
        device_snapshot = pre_snapshot.get(act.device, {})
        rollback_model_paths: dict[str, Any] = {}

        for path in act.model_paths:
            if path not in device_snapshot:
                missing.append(f"{act.device}:{path}")
                continue

            rollback_model_paths[path] = device_snapshot[path]

        if rollback_model_paths:
            rollback_actions.append(
                ChangeAction(
                    device=act.device,
                    model_paths=rollback_model_paths,
                    reason="rollback to pre change snapshot",
                )
            )

    checks: list[dict[str, Any]] = []

    for act in rollback_actions:
        for path, expected in act.model_paths.items():
            checks.append(
                {
                    "type": "path_equals",
                    "device": act.device,
                    "path": str(path),
                    "expected": expected,
                }
            )

    rollback_verification = VerificationSpec(
        checks=checks,
        probes=[],
        window_seconds=30,
    )

    rollback_spec = RollbackSpec(
        enabled=False,
        triggers=[],
    )

    explanation = (
        "Rollback plan built from pre change snapshot. "
        f"Actions {len(rollback_actions)}. "
        f"Missing paths {len(missing)}."
    )

    rollback_plan = ChangePlan(
        plan_id=f"{original_plan.plan_id}_rollback",
        actions=rollback_actions,
        verification=rollback_verification,
        rollback=rollback_spec,
        risk="high",
        explanation=explanation,
    )

    return RollbackBuildResult(
        plan=rollback_plan,
        missing_paths=missing,
    )
