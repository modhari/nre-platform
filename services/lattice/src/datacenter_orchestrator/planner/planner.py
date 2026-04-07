"""
Deterministic planner.

Purpose
Convert an IntentChange into a structured ChangePlan that the orchestration
engine can execute safely.

Design
This planner is strict and predictable. It does not call external models.
An agentic layer can propose intent, but the final plan must be deterministic,
auditable, and repeatable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from datacenter_orchestrator.core.types import (
    ChangeAction,
    ChangePlan,
    IntentChange,
    RollbackSpec,
    VerificationSpec,
)
from datacenter_orchestrator.inventory.store import InventoryStore


@dataclass
class PlannerConfig:
    """
    Planner configuration.

    max_devices_low_risk
    If a plan touches no more than this many devices, it is low risk by default.

    verification_window_seconds
    How long verification should consider the post change state stable.
    """

    max_devices_low_risk: int = 2
    verification_window_seconds: int = 60


class DeterministicPlanner:
    """
    Strict planner that produces a ChangePlan from an IntentChange.

    The caller supplies inventory so we can sanity check device names and avoid
    pushing to unknown devices.
    """

    def __init__(self, config: PlannerConfig | None = None) -> None:
        self._config = config or PlannerConfig()

    def plan_change(self, intent: IntentChange, inventory: InventoryStore) -> ChangePlan:
        """
        Convert intent into an executable ChangePlan.

        Expected desired formats
        Format A
        desired["actions"] is a list of dicts with:
        device, model_paths, optional reason

        Format B
        desired has:
        device, model_paths, optional reason
        """

        actions = self._parse_actions(intent.desired)
        self._validate_actions_exist_in_inventory(actions, inventory)

        risk = self._compute_risk(actions)
        verification = self._build_verification(intent, actions)
        rollback = self._build_rollback_spec(intent, actions)

        explanation = (
            "Plan created from declarative intent. "
            f"Device count {len(actions)}. "
            f"Risk {risk}. "
            f"Verification checks {len(verification.checks)}."
        )

        return ChangePlan(
            plan_id=intent.change_id,
            actions=actions,
            verification=verification,
            rollback=rollback,
            risk=risk,
            explanation=explanation,
        )

    def _parse_actions(self, desired: dict[str, Any]) -> list[ChangeAction]:
        """
        Parse actions from desired intent.

        Raises ValueError when shape is invalid so the caller can alert clearly.
        """

        if "actions" in desired:
            raw_actions = desired["actions"]
            if not isinstance(raw_actions, list):
                raise ValueError("desired.actions must be a list")

            actions: list[ChangeAction] = []
            for idx, raw in enumerate(raw_actions):
                if not isinstance(raw, dict):
                    raise ValueError(f"desired.actions item {idx} must be a dict")

                device = raw.get("device")
                model_paths = raw.get("model_paths")
                reason = raw.get("reason", "intent action")

                if not isinstance(device, str) or not device:
                    raise ValueError(f"desired.actions item {idx} missing device str")

                if not isinstance(model_paths, dict) or not model_paths:
                    raise ValueError(f"desired.actions item {idx} missing model_paths dict")

                actions.append(
                    ChangeAction(
                        device=device,
                        model_paths=model_paths,
                        reason=str(reason),
                    )
                )

            return actions

        device = desired.get("device")
        model_paths = desired.get("model_paths")
        reason = desired.get("reason", "intent action")

        if isinstance(device, str) and isinstance(model_paths, dict) and model_paths:
            return [
                ChangeAction(
                    device=device,
                    model_paths=model_paths,
                    reason=str(reason),
                )
            ]

        raise ValueError("desired must include actions list or device and model_paths")

    def _validate_actions_exist_in_inventory(
        self,
        actions: list[ChangeAction],
        inventory: InventoryStore,
    ) -> None:
        """Ensure every device referenced by the plan exists in inventory."""

        missing: list[str] = []
        for act in actions:
            if inventory.get(act.device) is None:
                missing.append(act.device)

        if missing:
            missing_sorted = ", ".join(sorted(set(missing)))
            raise ValueError(f"plan references devices not present in inventory: {missing_sorted}")

    def _compute_risk(self, actions: list[ChangeAction]) -> str:
        """
        Compute a coarse risk level.

        This is intentionally simple. Policy gates can add stricter rules later.
        """

        if len(actions) <= self._config.max_devices_low_risk:
            return "low"
        if len(actions) <= 10:
            return "medium"
        return "high"

    def _build_verification(
        self,
        intent: IntentChange,
        actions: list[ChangeAction],
    ) -> VerificationSpec:
        """
        Build a verification spec.

        Default behavior
        For every model path written, verify the device reports the expected value.
        """

        _ = intent

        checks: list[dict[str, Any]] = []
        for act in actions:
            for path, expected in act.model_paths.items():
                checks.append(
                    {
                        "type": "path_equals",
                        "device": act.device,
                        "path": str(path),
                        "expected": expected,
                    }
                )

        return VerificationSpec(
            checks=checks,
            probes=[],
            window_seconds=self._config.verification_window_seconds,
        )

    def _build_rollback_spec(
        self,
        intent: IntentChange,
        actions: list[ChangeAction],
    ) -> RollbackSpec:
        """
        Build a rollback spec.

        Default
        Rollback enabled and triggered by any verification failure.
        """

        _ = intent
        _ = actions

        return RollbackSpec(
            enabled=True,
            triggers=["any_verification_failure"],
        )
