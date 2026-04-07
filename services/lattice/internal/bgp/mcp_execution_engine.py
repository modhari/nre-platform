from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Any

from internal.bgp.history_query_service import BgpHistoryQueryService
from internal.bgp.history_store import BgpHistoryStore
from internal.bgp.mcp_risk_wrapper import McpGovernedIntent, McpRiskWrapper
from internal.bgp.prefix_verifier import BgpPrefixVerifier
from internal.bgp.remediation_progression import BgpRemediationProgression
from internal.bgp.remediation_scenarios_demo import (
    build_advertised_route_zero_scenario,
    build_received_route_slash_scenario,
    build_received_route_zero_scenario,
    build_route_churn_scenario,
)
from internal.bgp.remediation_to_intent import (
    RemediationIntentMapper,
    build_recommendations_for_scenario,
)

LOG = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    status: str
    executed: bool
    approval_required: bool
    verification_passed: bool
    message: str
    next_step: str | None = None
    verification_details: dict[str, Any] | None = None
    progression: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class McpExecutionEngine:
    """
    Simulated execution engine for MCP governed intents.

    This does not execute real network changes.
    It simulates approval, execution, verification, and staged progression.
    """

    def __init__(
        self,
        history_service: BgpHistoryQueryService | None = None,
    ) -> None:
        self.history_service = history_service
        self.prefix_verifier = (
            BgpPrefixVerifier(history_service=history_service)
            if history_service is not None
            else None
        )
        self.progression = BgpRemediationProgression()

    def execute(
        self,
        governed: McpGovernedIntent,
        verification_timestamp_ms: int | None = None,
    ) -> ExecutionResult:
        intent = governed.intent

        if governed.approval_policy.requires_approval:
            return ExecutionResult(
                status="blocked",
                executed=False,
                approval_required=True,
                verification_passed=False,
                message="Execution blocked pending approval",
                next_step="awaiting_operator_approval",
                verification_details=None,
                progression=None,
            )

        LOG.info(
            "Executing intent %s on device %s",
            intent.intent_name,
            intent.target_device,
        )

        verification = self._simulate_verification(
            intent=intent,
            verification_timestamp_ms=verification_timestamp_ms,
        )

        if verification["passed"]:
            return ExecutionResult(
                status="success",
                executed=True,
                approval_required=False,
                verification_passed=True,
                message="Execution successful and verified",
                next_step=None,
                verification_details=verification,
                progression=None,
            )

        next_step_decision = self.progression.next_step(
            current_intent=intent,
            verification_details=verification,
        )

        return ExecutionResult(
            status="partial_failure",
            executed=True,
            approval_required=False,
            verification_passed=False,
            message="Execution completed but verification failed",
            next_step="escalate_or_try_next_remediation_step",
            verification_details=verification,
            progression=next_step_decision.to_dict(),
        )

    def _simulate_verification(
        self,
        *,
        intent,
        verification_timestamp_ms: int | None,
    ) -> dict[str, Any]:
        if intent.intent_name == "bgp_observe_only":
            return {
                "passed": True,
                "mode": "observe_only",
                "prefix_verification": None,
            }

        if intent.intent_name == "bgp_route_refresh":
            return self._verify_prefix_recovery(
                intent=intent,
                verification_timestamp_ms=verification_timestamp_ms,
                direction="received",
            )

        if intent.intent_name == "bgp_soft_clear_in":
            return self._verify_prefix_recovery(
                intent=intent,
                verification_timestamp_ms=verification_timestamp_ms,
                direction="received",
            )

        if intent.intent_name in {
            "bgp_soft_clear_out",
            "bgp_validate_policy_then_soft_clear_out",
        }:
            return self._verify_prefix_recovery(
                intent=intent,
                verification_timestamp_ms=verification_timestamp_ms,
                direction="advertised",
            )

        if intent.intent_name == "bgp_escalate_only":
            return {
                "passed": False,
                "mode": "escalation_only",
                "prefix_verification": None,
            }

        return {
            "passed": False,
            "mode": "unknown",
            "prefix_verification": None,
        }

    def _verify_prefix_recovery(
        self,
        *,
        intent,
        verification_timestamp_ms: int | None,
        direction: str,
    ) -> dict[str, Any]:
        context = intent.parameters.get("context", {})
        expected_prefixes = context.get("sample_prefixes", [])

        if self.prefix_verifier is None or verification_timestamp_ms is None:
            return {
                "passed": True,
                "mode": "fallback_without_history",
                "prefix_verification": {
                    "checked_prefixes": expected_prefixes,
                    "recovered_prefixes": expected_prefixes,
                    "missing_prefixes": [],
                },
            }

        result = self.prefix_verifier.verify_expected_prefixes_present(
            device=intent.target_device,
            peer=intent.parameters["peer"],
            network_instance=intent.parameters["network_instance"],
            afi_safi=intent.parameters["afi_safi"],
            direction=direction,
            timestamp_ms=verification_timestamp_ms,
            expected_prefixes=expected_prefixes,
        )

        return {
            "passed": result.recovered,
            "mode": "prefix_level_verification",
            "prefix_verification": result.to_dict(),
        }


def _build_history_service_for_scenario(
    scenario: Any,
) -> tuple[BgpHistoryQueryService, int]:
    store = BgpHistoryStore()
    store.store_route_snapshot_rows(scenario.before_routes)
    store.store_route_snapshot_rows(scenario.after_routes)
    history_service = BgpHistoryQueryService(history_store=store)
    verification_timestamp_ms = scenario.after_routes[0].timestamp_ms
    return history_service, verification_timestamp_ms


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
        governed_intents = [wrapper.wrap(item) for item in intents]

        history_service, verification_timestamp_ms = (
            _build_history_service_for_scenario(scenario)
        )
        engine = McpExecutionEngine(history_service=history_service)

        execution_results = [
            engine.execute(
                governed,
                verification_timestamp_ms=verification_timestamp_ms,
            )
            for governed in governed_intents
        ]

        results.append(
            {
                "scenario": scenario_name,
                "executions": [
                    {
                        "intent": governed.intent.intent_name,
                        "risk": governed.risk_category,
                        "execution_mode": governed.execution_mode,
                        "result": result.to_dict(),
                    }
                    for governed, result in zip(
                        governed_intents,
                        execution_results,
                    )
                ],
            }
        )

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
