from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from internal.bgp.anomaly_detector import BgpAnomalyDetector
from internal.bgp.anomaly_prioritizer import BgpAnomalyPrioritizer
from internal.bgp.history_query_service import BgpHistoryQueryService
from internal.bgp.history_store import BgpHistoryStore
from internal.bgp.remediation_planner import (
    BgpRemediationPlanner,
    RemediationRecommendation,
)
from internal.bgp.remediation_scenarios_demo import (
    build_advertised_route_zero_scenario,
    build_received_route_slash_scenario,
    build_received_route_zero_scenario,
    build_route_churn_scenario,
)
from internal.bgp.route_state_tracker import BgpRouteStateTracker

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class McpIntentRequest:
    """
    Structured action request ready to hand to MCP planning and risk evaluation.
    """

    intent_name: str
    target_device: str
    parameters: dict[str, Any]
    risk_level: str
    requires_approval: bool
    verification_steps: list[str] = field(default_factory=list)
    rollback_hint: str | None = None
    source_anomaly_type: str | None = None
    confidence: str | None = None
    reasoning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RemediationIntentMapper:
    """
    Convert remediation recommendations into MCP compatible intent requests.
    """

    def to_intent(
        self,
        recommendation: RemediationRecommendation,
    ) -> McpIntentRequest:
        action = recommendation.recommended_action
        context = {
            "removed_prefix_count": recommendation.details.get(
                "removed_prefix_count"
            ),
            "sample_prefixes": recommendation.details.get("sample_prefixes", []),
        }

        if action == "route_refresh":
            return McpIntentRequest(
                intent_name="bgp_route_refresh",
                target_device=recommendation.device,
                parameters={
                    "peer": recommendation.peer,
                    "network_instance": recommendation.network_instance,
                    "afi_safi": recommendation.afi_safi,
                    "context": context,
                },
                risk_level="low",
                requires_approval=False,
                verification_steps=[
                    "verify_peer_session_state",
                    "verify_received_route_count",
                    "compare_with_previous_baseline",
                ],
                rollback_hint="No rollback needed for route refresh",
                source_anomaly_type=recommendation.anomaly_type,
                confidence=recommendation.confidence,
                reasoning=recommendation.reason,
            )

        if action == "soft_clear_in":
            return McpIntentRequest(
                intent_name="bgp_soft_clear_in",
                target_device=recommendation.device,
                parameters={
                    "peer": recommendation.peer,
                    "network_instance": recommendation.network_instance,
                    "afi_safi": recommendation.afi_safi,
                    "context": context,
                },
                risk_level="medium",
                requires_approval=False,
                verification_steps=[
                    "verify_received_route_count",
                    "verify_route_recovery_for_removed_prefixes",
                    "confirm_no_broad_blast_radius_expansion",
                ],
                rollback_hint="Escalate if no recovery after soft clear inbound",
                source_anomaly_type=recommendation.anomaly_type,
                confidence=recommendation.confidence,
                reasoning=recommendation.reason,
            )

        if action == "soft_clear_out":
            return McpIntentRequest(
                intent_name="bgp_soft_clear_out",
                target_device=recommendation.device,
                parameters={
                    "peer": recommendation.peer,
                    "network_instance": recommendation.network_instance,
                    "afi_safi": recommendation.afi_safi,
                    "context": context,
                },
                risk_level="medium",
                requires_approval=False,
                verification_steps=[
                    "verify_advertised_route_count",
                    "validate_export_policy_result",
                    "confirm_expected_prefixes_are_advertised",
                ],
                rollback_hint=(
                    "Rollback recent export policy changes if advertisement "
                    "does not recover"
                ),
                source_anomaly_type=recommendation.anomaly_type,
                confidence=recommendation.confidence,
                reasoning=recommendation.reason,
            )

        if action == "validate_policy_then_soft_clear_out":
            return McpIntentRequest(
                intent_name="bgp_validate_policy_then_soft_clear_out",
                target_device=recommendation.device,
                parameters={
                    "peer": recommendation.peer,
                    "network_instance": recommendation.network_instance,
                    "afi_safi": recommendation.afi_safi,
                    "validation_scope": "export_policy_and_local_rib",
                    "context": context,
                },
                risk_level="medium",
                requires_approval=False,
                verification_steps=[
                    "validate_export_policy",
                    "verify_local_rib_population",
                    "verify_advertised_route_count_after_action",
                ],
                rollback_hint=(
                    "Rollback export policy if validation shows recent regression"
                ),
                source_anomaly_type=recommendation.anomaly_type,
                confidence=recommendation.confidence,
                reasoning=recommendation.reason,
            )

        if action == "observe":
            return McpIntentRequest(
                intent_name="bgp_observe_only",
                target_device=recommendation.device,
                parameters={
                    "peer": recommendation.peer,
                    "network_instance": recommendation.network_instance,
                    "afi_safi": recommendation.afi_safi,
                    "observation_window_seconds": 300,
                    "context": context,
                },
                risk_level="none",
                requires_approval=False,
                verification_steps=[
                    "increase_sampling",
                    "compare_sibling_devices",
                    "reevaluate_after_observation_window",
                ],
                rollback_hint=None,
                source_anomaly_type=recommendation.anomaly_type,
                confidence=recommendation.confidence,
                reasoning=recommendation.reason,
            )

        if action == "escalate_only":
            return McpIntentRequest(
                intent_name="bgp_escalate_only",
                target_device=recommendation.device,
                parameters={
                    "peer": recommendation.peer,
                    "network_instance": recommendation.network_instance,
                    "afi_safi": recommendation.afi_safi,
                    "severity": recommendation.severity,
                    "blast_radius": recommendation.blast_radius,
                    "context": context,
                },
                risk_level="none",
                requires_approval=False,
                verification_steps=[
                    "attach_route_diff_context",
                    "attach_peer_summary_context",
                    "notify_operator",
                ],
                rollback_hint=None,
                source_anomaly_type=recommendation.anomaly_type,
                confidence=recommendation.confidence,
                reasoning=recommendation.reason,
            )

        return McpIntentRequest(
            intent_name="bgp_manual_review",
            target_device=recommendation.device,
            parameters={
                "peer": recommendation.peer,
                "network_instance": recommendation.network_instance,
                "afi_safi": recommendation.afi_safi,
                "context": context,
            },
            risk_level="unknown",
            requires_approval=True,
            verification_steps=[
                "manual_operator_review",
            ],
            rollback_hint=None,
            source_anomaly_type=recommendation.anomaly_type,
            confidence=recommendation.confidence,
            reasoning=recommendation.reason,
        )


def build_recommendations_for_scenario(
    scenario: Any,
) -> list[RemediationRecommendation]:
    tracker = BgpRouteStateTracker()
    tracker.ingest_snapshot(
        scenario.before_routes[0].timestamp_ms,
        scenario.before_routes,
    )
    tracker.ingest_snapshot(
        scenario.after_routes[0].timestamp_ms,
        scenario.after_routes,
    )

    from_ts = scenario.before_routes[0].timestamp_ms
    to_ts = scenario.after_routes[0].timestamp_ms

    diff = tracker.diff_snapshots(from_ts, to_ts)
    summaries = tracker.peer_summaries_at(to_ts)
    events = tracker.route_events_for_diff(from_ts, to_ts)

    detector = BgpAnomalyDetector(
        received_major_drop_pct=20.0,
        received_critical_drop_pct=50.0,
        advertised_major_drop_pct=20.0,
        advertised_critical_drop_pct=50.0,
        churn_event_threshold=3,
    )
    anomalies = detector.detect_from_tracker(
        tracker=tracker,
        from_timestamp_ms=from_ts,
        to_timestamp_ms=to_ts,
    )

    prioritizer = BgpAnomalyPrioritizer()
    prioritized = prioritizer.prioritize(anomalies)

    store = BgpHistoryStore()
    store.store_route_snapshot_rows(scenario.before_routes)
    store.store_route_snapshot_rows(scenario.after_routes)
    store.store_peer_summary_rows(summaries)
    store.store_route_event_rows(events)
    store.store_anomaly_rows(anomalies)

    history_service = BgpHistoryQueryService(history_store=store)

    planner = BgpRemediationPlanner(history_service=history_service)
    return planner.plan(
        anomalies=[group.primary_anomaly for group in prioritized],
        current_summaries=summaries,
        diff=diff,
    )


def main() -> None:
    from internal.bgp.mcp_execution_engine import McpExecutionEngine
    from internal.bgp.mcp_risk_wrapper import McpGovernedIntent, McpRiskWrapper

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
    engine = McpExecutionEngine()
    results: list[dict[str, Any]] = []

    for scenario_name, scenario in scenarios:
        recommendations = build_recommendations_for_scenario(scenario)
        intents = [mapper.to_intent(item) for item in recommendations]
        governed: list[McpGovernedIntent] = [
            wrapper.wrap(item) for item in intents
        ]
        execution_results = [engine.execute(item).to_dict() for item in governed]

        results.append(
            {
                "scenario": scenario_name,
                "recommendations": [item.to_dict() for item in recommendations],
                "mcp_intents": [item.to_dict() for item in intents],
                "governed_intents": [item.to_dict() for item in governed],
                "execution_results": execution_results,
            }
        )

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
