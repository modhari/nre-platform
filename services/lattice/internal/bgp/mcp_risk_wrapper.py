from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from internal.bgp.remediation_scenarios_demo import (
    build_advertised_route_zero_scenario,
    build_received_route_slash_scenario,
    build_received_route_zero_scenario,
    build_route_churn_scenario,
)
from internal.bgp.remediation_to_intent import (
    McpIntentRequest,
    RemediationIntentMapper,
    build_recommendations_for_scenario,
)

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class McpApprovalPolicy:
    requires_approval: bool
    approver_scope: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class McpVerificationPolicy:
    steps: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    observation_window_seconds: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class McpRollbackPolicy:
    strategy: str
    trigger_conditions: list[str] = field(default_factory=list)
    hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class McpGovernedIntent:
    """
    MCP ready governed intent with risk, approval, verification, and rollback.
    """

    intent: McpIntentRequest
    risk_category: str
    execution_mode: str
    approval_policy: McpApprovalPolicy
    verification_policy: McpVerificationPolicy
    rollback_policy: McpRollbackPolicy

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent.to_dict(),
            "risk_category": self.risk_category,
            "execution_mode": self.execution_mode,
            "approval_policy": self.approval_policy.to_dict(),
            "verification_policy": self.verification_policy.to_dict(),
            "rollback_policy": self.rollback_policy.to_dict(),
        }


class McpRiskWrapper:
    """
    Attach MCP governance policy to remediation intents.

    This is where intent generation becomes execution ready,
    while still respecting risk controls.
    """

    def wrap(self, intent: McpIntentRequest) -> McpGovernedIntent:
        risk_category = self._risk_category(intent)
        execution_mode = self._execution_mode(intent, risk_category)
        approval_policy = self._approval_policy(intent, risk_category)
        verification_policy = self._verification_policy(intent)
        rollback_policy = self._rollback_policy(intent)

        return McpGovernedIntent(
            intent=intent,
            risk_category=risk_category,
            execution_mode=execution_mode,
            approval_policy=approval_policy,
            verification_policy=verification_policy,
            rollback_policy=rollback_policy,
        )

    def _risk_category(self, intent: McpIntentRequest) -> str:
        if intent.intent_name in {"bgp_observe_only", "bgp_escalate_only"}:
            return "informational"

        if intent.intent_name == "bgp_route_refresh":
            return "low"

        if intent.intent_name in {
            "bgp_soft_clear_in",
            "bgp_soft_clear_out",
            "bgp_validate_policy_then_soft_clear_out",
        }:
            return "medium"

        return "high"

    def _execution_mode(self, intent: McpIntentRequest, risk_category: str) -> str:
        if risk_category == "informational":
            return "observe_only"

        if risk_category == "low":
            return "auto_with_verification"

        if risk_category == "medium":
            return "guarded_auto"

        return "approval_required"

    def _approval_policy(
        self,
        intent: McpIntentRequest,
        risk_category: str,
    ) -> McpApprovalPolicy:
        if risk_category == "informational":
            return McpApprovalPolicy(
                requires_approval=False,
                approver_scope="none",
                reason="No device state change will be executed.",
            )

        if risk_category == "low":
            return McpApprovalPolicy(
                requires_approval=False,
                approver_scope="none",
                reason="Low risk control plane refresh with explicit verification.",
            )

        if risk_category == "medium":
            return McpApprovalPolicy(
                requires_approval=True,
                approver_scope="network_operator",
                reason="Medium risk BGP action should be approved before execution.",
            )

        return McpApprovalPolicy(
            requires_approval=True,
            approver_scope="network_operator_or_manager",
            reason="High risk or unknown action requires explicit human approval.",
        )

    def _verification_policy(self, intent: McpIntentRequest) -> McpVerificationPolicy:
        success_criteria = []

        if intent.intent_name == "bgp_route_refresh":
            success_criteria = [
                "received_route_count_recovers",
                "peer_session_remains_established",
            ]
            observation_window_seconds = 120
        elif intent.intent_name in {"bgp_soft_clear_in", "bgp_soft_clear_out"}:
            success_criteria = [
                "route_count_recovers",
                "no_blast_radius_expansion",
            ]
            observation_window_seconds = 180
        elif intent.intent_name == "bgp_validate_policy_then_soft_clear_out":
            success_criteria = [
                "policy_validation_passes",
                "advertised_routes_recover",
            ]
            observation_window_seconds = 180
        else:
            success_criteria = ["operator_review_complete"]
            observation_window_seconds = 300

        return McpVerificationPolicy(
            steps=intent.verification_steps,
            success_criteria=success_criteria,
            observation_window_seconds=observation_window_seconds,
        )

    def _rollback_policy(self, intent: McpIntentRequest) -> McpRollbackPolicy:
        if intent.intent_name == "bgp_route_refresh":
            return McpRollbackPolicy(
                strategy="none",
                trigger_conditions=[],
                hint="No rollback required for route refresh.",
            )

        if intent.intent_name in {"bgp_soft_clear_in", "bgp_soft_clear_out"}:
            return McpRollbackPolicy(
                strategy="escalate_if_unsuccessful",
                trigger_conditions=[
                    "route_count_does_not_recover",
                    "peer_session_degrades",
                ],
                hint=intent.rollback_hint,
            )

        if intent.intent_name == "bgp_validate_policy_then_soft_clear_out":
            return McpRollbackPolicy(
                strategy="rollback_recent_policy_change",
                trigger_conditions=[
                    "validation_finds_policy_regression",
                    "advertised_routes_fail_to_recover",
                ],
                hint=intent.rollback_hint,
            )

        return McpRollbackPolicy(
            strategy="manual_review",
            trigger_conditions=["operator_requests_review"],
            hint=intent.rollback_hint,
        )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )

    scenarios = [
        ("received_route_zero", build_received_route_zero_scenario()),
        ("received_route_slash", build_received_route_slash_scenario()),
        ("advertised_route_zero", build_advertised_route_zero_scenario()),
        ("route_churn_spike", build_route_churn_scenario()),
    ]

    mapper = RemediationIntentMapper()
    wrapper = McpRiskWrapper()
    results: list[dict[str, Any]] = []

    for scenario_name, scenario in scenarios:
        recommendations = build_recommendations_for_scenario(scenario)
        intents = [mapper.to_intent(item) for item in recommendations]
        governed = [wrapper.wrap(intent) for intent in intents]

        results.append(
            {
                "scenario": scenario_name,
                "governed_intents": [item.to_dict() for item in governed],
            }
        )

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
