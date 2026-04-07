"""
Execution guard.

Purpose
Convert risk assessment into an execution decision.

This is where you enforce safety rules that protect the fabric from unsafe
agent proposals.

The agent can propose changes.
The guard decides whether execution is allowed and under what mode.
"""

from __future__ import annotations

from dataclasses import dataclass

from datacenter_orchestrator.agent.execution_mode import ExecutionMode
from datacenter_orchestrator.planner.risk import PlanRiskAssessment, RiskLevel


@dataclass(frozen=True)
class GuardDecision:
    """
    Guard decision.

    mode
    apply, simulate, or dry_run

    allowed
    If False, engine must not proceed with apply.

    reasons
    Human readable reasons suitable for an alert.
    """

    mode: ExecutionMode
    allowed: bool
    reasons: list[str]


@dataclass(frozen=True)
class GuardConfig:
    """
    Guard configuration.

    default_mode
    The mode used when risk is low or medium.

    high_risk_mode
    The mode used when risk is high.

    require_approval_blocks_apply
    When True, requires_approval always disables apply.
    """

    default_mode: ExecutionMode = ExecutionMode.apply
    high_risk_mode: ExecutionMode = ExecutionMode.dry_run
    require_approval_blocks_apply: bool = True


class ExecutionGuard:
    """Decide execution mode from a risk assessment."""

    def __init__(self, config: GuardConfig | None = None) -> None:
        self._config = config or GuardConfig()

    def decide(self, risk: PlanRiskAssessment) -> GuardDecision:
        """
        Decide how the engine should proceed.

        Rules
        1) high risk defaults to dry_run
        2) requires approval can block apply
        3) low and medium follow default mode
        """

        reasons: list[str] = list(risk.reasons)

        if risk.risk_level == RiskLevel.high:
            mode = self._config.high_risk_mode
            allowed = mode == ExecutionMode.apply
            reasons.append("high risk plan guarded by high risk mode")
            return GuardDecision(mode=mode, allowed=allowed, reasons=reasons)

        if self._config.require_approval_blocks_apply and risk.requires_approval:
            reasons.append("plan requires approval so apply is blocked")
            return GuardDecision(mode=ExecutionMode.dry_run, allowed=False, reasons=reasons)

        mode = self._config.default_mode
        allowed = mode == ExecutionMode.apply
        if mode == ExecutionMode.simulate:
            allowed = False
            reasons.append("default mode is simulate so apply is not performed")
        if mode == ExecutionMode.dry_run:
            allowed = False
            reasons.append("default mode is dry_run so apply is not performed")

        return GuardDecision(mode=mode, allowed=allowed, reasons=reasons)
