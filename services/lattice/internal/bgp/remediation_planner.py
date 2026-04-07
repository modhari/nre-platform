from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from internal.bgp.anomaly_detector import BgpAnomaly, BgpAnomalyDetector
from internal.bgp.anomaly_prioritizer import BgpAnomalyPrioritizer
from internal.bgp.cross_device_correlation import (
    BgpCrossDeviceCorrelator,
    CrossDeviceCorrelationResult,
)
from internal.bgp.history_query_service import (
    BgpHistoryQueryRequest,
    BgpHistoryQueryService,
)
from internal.bgp.history_store import BgpHistoryStore
from internal.bgp.models import BgpPeerRouteSummary, SnapshotDiff
from internal.bgp.route_state_tracker import BgpRouteStateTracker, build_demo_routes

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class RemediationRecommendation:
    timestamp_ms: int
    anomaly_type: str
    device: str
    network_instance: str
    peer: str
    afi_safi: str
    recommended_action: str
    confidence: str
    safe: bool
    severity: str
    blast_radius: str
    reason: str
    follow_up_actions: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BgpRemediationPlanner:
    """
    History aware and cross device aware remediation planner.
    """

    def __init__(
        self,
        history_service: BgpHistoryQueryService | None = None,
        cross_device_correlator: BgpCrossDeviceCorrelator | None = None,
    ) -> None:
        self.history_service = history_service
        self.cross_device_correlator = cross_device_correlator

    def plan(
        self,
        anomalies: list[BgpAnomaly],
        current_summaries: list[BgpPeerRouteSummary],
        diff: SnapshotDiff,
    ) -> list[RemediationRecommendation]:
        recommendations: list[RemediationRecommendation] = []
        summaries_by_key = {
            self._peer_key(summary): summary
            for summary in current_summaries
        }

        for anomaly in anomalies:
            current_summary = summaries_by_key.get(self._anomaly_key(anomaly))
            history_context = self._build_history_context(anomaly, diff)
            correlation = self._build_cross_device_context(
                anomaly=anomaly,
                diff=diff,
                history_context=history_context,
            )

            recommendation = self._plan_one(
                anomaly=anomaly,
                current_summary=current_summary,
                diff=diff,
                history_context=history_context,
                correlation=correlation,
            )
            recommendations.append(recommendation)

        return recommendations

    def _plan_one(
        self,
        anomaly: BgpAnomaly,
        current_summary: BgpPeerRouteSummary | None,
        diff: SnapshotDiff,
        history_context: dict[str, Any],
        correlation: CrossDeviceCorrelationResult | None,
    ) -> RemediationRecommendation:
        del current_summary

        anomaly_type = anomaly.anomaly_type
        removed_prefixes = history_context.get("removed_prefixes", [])
        removed_prefix_count = len(removed_prefixes)
        sample_prefixes = removed_prefixes[:5]

        present_elsewhere_count = 0
        missing_everywhere_count = 0
        if correlation is not None:
            present_elsewhere_count = len(correlation.prefixes_present_anywhere_else)
            missing_everywhere_count = len(correlation.prefixes_missing_everywhere_checked)

        shared_scope = present_elsewhere_count == 0 and missing_everywhere_count > 0
        local_scope = present_elsewhere_count > 0

        if anomaly_type == "received_route_zero":
            if shared_scope:
                reason = (
                    f"Received routes dropped to zero and {missing_everywhere_count} "
                    "removed prefixes are also absent on sibling devices. This points "
                    "to broader scope, so escalate before stronger local recovery."
                )
                action = "escalate_only"
                follow_up_actions = [
                    "compare_sibling_devices",
                    "check_upstream_scope",
                ]
            elif local_scope:
                reason = (
                    f"Received routes dropped to zero and {present_elsewhere_count} "
                    "removed prefixes still exist on sibling devices. This looks "
                    "local, so use targeted recovery first."
                )
                action = "route_refresh"
                follow_up_actions = [
                    "verify_received_routes",
                    "soft_clear_in_if_unchanged",
                ]
            elif removed_prefix_count < 10:
                reason = (
                    f"Received routes dropped to zero and {removed_prefix_count} "
                    "removed prefixes were identified. Use targeted recovery first."
                )
                action = "route_refresh"
                follow_up_actions = [
                    "verify_received_routes",
                    "soft_clear_in_if_unchanged",
                ]
            else:
                reason = (
                    f"Received routes dropped to zero and {removed_prefix_count} "
                    "removed prefixes suggest broader impact. Start conservatively "
                    "and compare siblings immediately."
                )
                action = "route_refresh"
                follow_up_actions = [
                    "verify_received_routes",
                    "soft_clear_in_if_unchanged",
                    "compare_sibling_devices",
                ]

            return self._build_recommendation(
                anomaly=anomaly,
                action=action,
                confidence="high",
                reason=reason,
                follow_up_actions=follow_up_actions,
                details=self._build_details(
                    anomaly=anomaly,
                    diff=diff,
                    removed_prefix_count=removed_prefix_count,
                    sample_prefixes=sample_prefixes,
                    correlation=correlation,
                ),
            )

        if anomaly_type == "received_route_slash":
            widespread = self._is_widespread(diff, direction="received")
            if widespread or shared_scope:
                return self._build_recommendation(
                    anomaly=anomaly,
                    action="escalate_only",
                    confidence="high",
                    reason=(
                        "Received route slash appears broader than one isolated peer "
                        "or device, or missing prefixes are absent on sibling devices. "
                        "Avoid stronger local remediation and escalate."
                    ),
                    follow_up_actions=[
                        "compare_sibling_devices",
                        "check_upstream_scope",
                    ],
                    details=self._build_details(
                        anomaly=anomaly,
                        diff=diff,
                        removed_prefix_count=removed_prefix_count,
                        sample_prefixes=sample_prefixes,
                        correlation=correlation,
                    ),
                    blast_radius="wider_than_peer",
                )

            if local_scope:
                action = "route_refresh"
                reason = (
                    f"Received route count dropped sharply and {present_elsewhere_count} "
                    "missing prefixes still exist on sibling devices. This points to "
                    "a local issue, so route refresh is the right first action."
                )
                follow_up_actions = [
                    "verify_received_routes",
                    "soft_clear_in_if_unchanged",
                ]
            elif removed_prefix_count >= 10:
                action = "soft_clear_in"
                reason = (
                    f"Received route count dropped sharply and {removed_prefix_count} "
                    "removed prefixes were identified. The impact is broad enough to "
                    "justify stronger inbound recovery."
                )
                follow_up_actions = [
                    "verify_received_routes",
                    "compare_sibling_devices",
                ]
            else:
                action = "route_refresh"
                reason = (
                    f"Received route count dropped sharply and {removed_prefix_count} "
                    "removed prefixes were identified. Use route refresh first, then "
                    "consider soft clear inbound if recovery does not happen."
                )
                follow_up_actions = [
                    "verify_received_routes",
                    "soft_clear_in_if_unchanged",
                ]

            return self._build_recommendation(
                anomaly=anomaly,
                action=action,
                confidence="medium",
                reason=reason,
                follow_up_actions=follow_up_actions,
                details=self._build_details(
                    anomaly=anomaly,
                    diff=diff,
                    removed_prefix_count=removed_prefix_count,
                    sample_prefixes=sample_prefixes,
                    correlation=correlation,
                ),
            )

        if anomaly_type == "advertised_route_zero":
            if shared_scope:
                action = "escalate_only"
                reason = (
                    "Advertised routes dropped to zero and expected prefixes are also "
                    "absent on sibling devices. Escalate for wider policy or upstream scope."
                )
                follow_up_actions = [
                    "compare_sibling_devices",
                    "validate_export_policy",
                ]
            else:
                action = "soft_clear_out"
                reason = (
                    "Advertised route count dropped to zero. Validate export policy and "
                    "refresh outbound advertisement state with a bounded action."
                )
                follow_up_actions = [
                    "validate_export_policy",
                    "verify_advertised_routes",
                ]

            return self._build_recommendation(
                anomaly=anomaly,
                action=action,
                confidence="medium",
                reason=reason,
                follow_up_actions=follow_up_actions,
                details=self._build_details(
                    anomaly=anomaly,
                    diff=diff,
                    removed_prefix_count=removed_prefix_count,
                    sample_prefixes=sample_prefixes,
                    correlation=correlation,
                ),
            )

        if anomaly_type == "advertised_route_slash":
            if shared_scope:
                action = "escalate_only"
                reason = (
                    "Advertised route slash appears broader than a single device, so "
                    "validate wider policy scope before local action."
                )
                follow_up_actions = [
                    "compare_sibling_devices",
                    "validate_export_policy",
                ]
            else:
                action = "validate_policy_then_soft_clear_out"
                reason = (
                    "Advertised route count dropped sharply. Validate export policy or "
                    "local route availability before refreshing outbound advertisements."
                )
                follow_up_actions = [
                    "validate_export_policy",
                    "verify_advertised_routes",
                ]

            return self._build_recommendation(
                anomaly=anomaly,
                action=action,
                confidence="medium",
                reason=reason,
                follow_up_actions=follow_up_actions,
                details=self._build_details(
                    anomaly=anomaly,
                    diff=diff,
                    removed_prefix_count=removed_prefix_count,
                    sample_prefixes=sample_prefixes,
                    correlation=correlation,
                ),
            )

        if anomaly_type == "route_churn_spike":
            return self._build_recommendation(
                anomaly=anomaly,
                action="observe",
                confidence="medium",
                reason=(
                    "Route churn increased but counts did not indicate clear slash or "
                    "full route loss. Observe, compare siblings, and raise sensitivity."
                ),
                follow_up_actions=[
                    "increase_sampling",
                    "compare_sibling_devices",
                ],
                details=self._build_details(
                    anomaly=anomaly,
                    diff=diff,
                    removed_prefix_count=removed_prefix_count,
                    sample_prefixes=sample_prefixes,
                    correlation=correlation,
                ),
            )

        return self._build_recommendation(
            anomaly=anomaly,
            action="escalate_only",
            confidence="low",
            reason="No explicit remediation rule matched. Escalate for operator review.",
            follow_up_actions=[],
            details=self._build_details(
                anomaly=anomaly,
                diff=diff,
                removed_prefix_count=removed_prefix_count,
                sample_prefixes=sample_prefixes,
                correlation=correlation,
            ),
        )

    def _build_history_context(
        self,
        anomaly: BgpAnomaly,
        diff: SnapshotDiff,
    ) -> dict[str, Any]:
        context: dict[str, Any] = {
            "removed_prefixes": [],
        }

        if self.history_service is None:
            return context

        try:
            response = self.history_service.handle(
                BgpHistoryQueryRequest(
                    device=anomaly.device,
                    peer=anomaly.peer,
                    network_instance=anomaly.network_instance,
                    direction="received",
                    afi_safi=anomaly.afi_safi,
                    start_ts=diff.from_timestamp_ms,
                    end_ts=diff.to_timestamp_ms,
                    query_type="removed_routes_between",
                )
            )
            context["removed_prefixes"] = [item["prefix"] for item in response.results]
        except Exception:
            context["removed_prefixes"] = []

        return context

    def _build_cross_device_context(
        self,
        *,
        anomaly: BgpAnomaly,
        diff: SnapshotDiff,
        history_context: dict[str, Any],
    ) -> CrossDeviceCorrelationResult | None:
        if self.cross_device_correlator is None:
            return None

        missing_prefixes = history_context.get("removed_prefixes", [])
        if not missing_prefixes:
            return None

        try:
            return self.cross_device_correlator.correlate_missing_prefixes(
                source_device=anomaly.device,
                peer=anomaly.peer,
                network_instance=anomaly.network_instance,
                afi_safi=anomaly.afi_safi,
                direction="received",
                timestamp_ms=diff.to_timestamp_ms,
                missing_prefixes=missing_prefixes,
            )
        except Exception:
            return None

    def _build_recommendation(
        self,
        *,
        anomaly: BgpAnomaly,
        action: str,
        confidence: str,
        reason: str,
        follow_up_actions: list[str],
        details: dict[str, Any],
        blast_radius: str | None = None,
    ) -> RemediationRecommendation:
        return RemediationRecommendation(
            timestamp_ms=anomaly.timestamp_ms,
            anomaly_type=anomaly.anomaly_type,
            device=anomaly.device,
            network_instance=anomaly.network_instance,
            peer=anomaly.peer,
            afi_safi=anomaly.afi_safi,
            recommended_action=action,
            confidence=confidence,
            safe=True,
            severity=anomaly.severity,
            blast_radius=blast_radius or anomaly.blast_radius,
            reason=reason,
            follow_up_actions=follow_up_actions,
            details=details,
        )

    def _build_details(
        self,
        *,
        anomaly: BgpAnomaly,
        diff: SnapshotDiff,
        removed_prefix_count: int,
        sample_prefixes: list[str],
        correlation: CrossDeviceCorrelationResult | None,
    ) -> dict[str, Any]:
        details: dict[str, Any] = {
            **anomaly.details,
            "removed_prefix_count": removed_prefix_count,
            "sample_prefixes": sample_prefixes,
        }

        if anomaly.anomaly_type == "route_churn_spike":
            details["added_routes"] = len(diff.added_routes)
            details["removed_routes"] = len(diff.removed_routes)
            details["changed_routes"] = len(diff.changed_routes)

        if correlation is not None:
            details["cross_device_correlation"] = correlation.to_dict()

        return details

    def _is_widespread(self, diff: SnapshotDiff, direction: str) -> bool:
        peers = set()
        devices = set()

        for route in diff.added_routes + diff.removed_routes:
            if route.direction != direction:
                continue
            peers.add(route.peer)
            devices.add(route.device)

        for event in diff.changed_routes:
            if event.direction != direction:
                continue
            peers.add(event.peer)
            devices.add(event.device)

        return len(peers) > 1 or len(devices) > 1

    def _peer_key(self, summary: BgpPeerRouteSummary) -> str:
        return "|".join(
            [
                summary.device,
                summary.network_instance,
                summary.peer,
                summary.afi_safi,
            ]
        )

    def _anomaly_key(self, anomaly: BgpAnomaly) -> str:
        return "|".join(
            [
                anomaly.device,
                anomaly.network_instance,
                anomaly.peer,
                anomaly.afi_safi,
            ]
        )


def _build_demo_store_with_siblings() -> tuple[
    BgpRouteStateTracker,
    BgpHistoryStore,
    list[BgpAnomaly],
    list[BgpPeerRouteSummary],
    list[Any],
    SnapshotDiff,
]:
    tracker = BgpRouteStateTracker()
    snapshot_1, snapshot_2 = build_demo_routes()

    sibling_before = [
        item.__class__(
            **{
                **item.to_dict(),
                "device": "leaf-02",
            }
        )
        for item in snapshot_1
    ]
    sibling_after = [
        item.__class__(
            **{
                **item.to_dict(),
                "device": "leaf-02",
            }
        )
        for item in snapshot_2
        if item.prefix != "10.20.0.0/24"
    ]

    tracker.ingest_snapshot(snapshot_1[0].timestamp_ms, snapshot_1 + sibling_before)
    tracker.ingest_snapshot(snapshot_2[0].timestamp_ms, snapshot_2 + sibling_after)

    from_ts = snapshot_1[0].timestamp_ms
    to_ts = snapshot_2[0].timestamp_ms

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

    store = BgpHistoryStore()
    store.store_route_snapshot_rows(snapshot_1 + sibling_before)
    store.store_route_snapshot_rows(snapshot_2 + sibling_after)
    store.store_peer_summary_rows(summaries)
    store.store_route_event_rows(events)
    store.store_anomaly_rows(anomalies)

    return tracker, store, anomalies, summaries, events, diff


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )

    tracker, store, anomalies, summaries, _, diff = _build_demo_store_with_siblings()

    prioritizer = BgpAnomalyPrioritizer()
    groups = prioritizer.prioritize(anomalies)

    history_service = BgpHistoryQueryService(history_store=store)
    correlator = BgpCrossDeviceCorrelator(history_store=store)

    planner = BgpRemediationPlanner(
        history_service=history_service,
        cross_device_correlator=correlator,
    )

    filtered_anomalies = [
        group.primary_anomaly
        for group in groups
        if group.primary_anomaly.device == "leaf-01"
    ]
    filtered_summaries = [
        summary
        for summary in summaries
        if summary.device == "leaf-01"
    ]

    recommendations = planner.plan(
        anomalies=filtered_anomalies,
        current_summaries=filtered_summaries,
        diff=diff,
    )

    print(json.dumps([item.to_dict() for item in recommendations], indent=2))


if __name__ == "__main__":
    main()
