from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Any

from internal.bgp.anomaly_detector import BgpAnomaly, BgpAnomalyDetector
from internal.bgp.anomaly_prioritizer import (
    BgpAnomalyPrioritizer,
    PrioritizedAnomalyGroup,
)
from internal.bgp.cross_device_correlation import BgpCrossDeviceCorrelator
from internal.bgp.history_query_service import BgpHistoryQueryService
from internal.bgp.history_store import BgpHistoryStore
from internal.bgp.mcp_execution_engine import ExecutionResult, McpExecutionEngine
from internal.bgp.mcp_risk_wrapper import McpRiskWrapper
from internal.bgp.models import BgpPeerRouteSummary
from internal.bgp.remediation_planner import (
    BgpRemediationPlanner,
)
from internal.bgp.remediation_to_intent import RemediationIntentMapper
from internal.bgp.route_state_tracker import BgpRouteStateTracker, build_demo_routes

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class BgpRemediationServiceRequest:
    device: str
    peer: str | None = None
    network_instance: str = "default"
    afi_safi: str = "ipv4_unicast"
    from_timestamp_ms: int | None = None
    to_timestamp_ms: int | None = None
    plan_only: bool = True
    execute: bool = False


@dataclass
class BgpRemediationServiceResponse:
    request: dict[str, Any]
    available_timestamps: list[int]
    raw_anomalies: list[dict[str, Any]]
    prioritized_anomalies: list[dict[str, Any]]
    recommendations: list[dict[str, Any]]
    intents: list[dict[str, Any]]
    governed_intents: list[dict[str, Any]]
    execution_results: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BgpRemediationService:
    """
    Single orchestration entry point for BGP remediation planning and execution.
    """

    def __init__(
        self,
        *,
        tracker: BgpRouteStateTracker,
        history_store: BgpHistoryStore,
    ) -> None:
        self.tracker = tracker
        self.history_store = history_store
        self.history_service = BgpHistoryQueryService(history_store=history_store)
        self.cross_device_correlator = BgpCrossDeviceCorrelator(
            history_store=history_store
        )

        self.detector = BgpAnomalyDetector(
            received_major_drop_pct=20.0,
            received_critical_drop_pct=50.0,
            advertised_major_drop_pct=20.0,
            advertised_critical_drop_pct=50.0,
            churn_event_threshold=3,
        )
        self.prioritizer = BgpAnomalyPrioritizer()
        self.planner = BgpRemediationPlanner(
            history_service=self.history_service,
            cross_device_correlator=self.cross_device_correlator,
        )
        self.intent_mapper = RemediationIntentMapper()
        self.risk_wrapper = McpRiskWrapper()
        self.execution_engine = McpExecutionEngine(
            history_service=self.history_service
        )

    def handle(
        self,
        request: BgpRemediationServiceRequest,
    ) -> BgpRemediationServiceResponse:
        available_timestamps = self.tracker.available_timestamps()
        if len(available_timestamps) < 2:
            raise ValueError(
                "Need at least two snapshots before remediation analysis can run"
            )

        from_ts, to_ts = self._resolve_window(
            available_timestamps=available_timestamps,
            request=request,
        )

        diff = self.tracker.diff_snapshots(from_ts, to_ts)
        current_summaries = self.tracker.peer_summaries_at(to_ts)

        anomalies = self.detector.detect_from_tracker(
            tracker=self.tracker,
            from_timestamp_ms=from_ts,
            to_timestamp_ms=to_ts,
        )
        filtered_anomalies = self._filter_anomalies(
            anomalies=anomalies,
            request=request,
        )

        prioritized_groups = self.prioritizer.prioritize(filtered_anomalies)

        filtered_summaries = self._filter_summaries(
            summaries=current_summaries,
            request=request,
        )

        recommendations = self.planner.plan(
            anomalies=[group.primary_anomaly for group in prioritized_groups],
            current_summaries=filtered_summaries,
            diff=diff,
        )

        intents = [self.intent_mapper.to_intent(item) for item in recommendations]
        governed_intents = [self.risk_wrapper.wrap(item) for item in intents]

        execution_results: list[ExecutionResult] = []
        if request.execute and not request.plan_only:
            execution_results = [
                self.execution_engine.execute(
                    governed,
                    verification_timestamp_ms=to_ts,
                )
                for governed in governed_intents
            ]

        return BgpRemediationServiceResponse(
            request=asdict(request),
            available_timestamps=available_timestamps,
            raw_anomalies=[item.to_dict() for item in filtered_anomalies],
            prioritized_anomalies=[
                self._prioritized_group_to_dict(group)
                for group in prioritized_groups
            ],
            recommendations=[item.to_dict() for item in recommendations],
            intents=[item.to_dict() for item in intents],
            governed_intents=[item.to_dict() for item in governed_intents],
            execution_results=[item.to_dict() for item in execution_results],
        )

    def _resolve_window(
        self,
        *,
        available_timestamps: list[int],
        request: BgpRemediationServiceRequest,
    ) -> tuple[int, int]:
        if (
            request.from_timestamp_ms is not None
            and request.to_timestamp_ms is not None
        ):
            return request.from_timestamp_ms, request.to_timestamp_ms

        if request.to_timestamp_ms is not None:
            earlier = [
                ts for ts in available_timestamps if ts < request.to_timestamp_ms
            ]
            if not earlier:
                raise ValueError(
                    "Could not resolve from_timestamp_ms before the requested to time"
                )
            return max(earlier), request.to_timestamp_ms

        return available_timestamps[-2], available_timestamps[-1]

    def _filter_anomalies(
        self,
        *,
        anomalies: list[BgpAnomaly],
        request: BgpRemediationServiceRequest,
    ) -> list[BgpAnomaly]:
        results: list[BgpAnomaly] = []

        for anomaly in anomalies:
            if anomaly.device != request.device:
                continue
            if anomaly.network_instance != request.network_instance:
                continue
            if anomaly.afi_safi != request.afi_safi:
                continue
            if request.peer is not None and anomaly.peer != request.peer:
                continue
            results.append(anomaly)

        return results

    def _filter_summaries(
        self,
        *,
        summaries: list[BgpPeerRouteSummary],
        request: BgpRemediationServiceRequest,
    ) -> list[BgpPeerRouteSummary]:
        results: list[BgpPeerRouteSummary] = []

        for summary in summaries:
            if summary.device != request.device:
                continue
            if summary.network_instance != request.network_instance:
                continue
            if summary.afi_safi != request.afi_safi:
                continue
            if request.peer is not None and summary.peer != request.peer:
                continue
            results.append(summary)

        return results

    def _prioritized_group_to_dict(
        self,
        group: PrioritizedAnomalyGroup,
    ) -> dict[str, Any]:
        return {
            "primary_anomaly": group.primary_anomaly.to_dict(),
            "supporting_anomalies": [
                anomaly.to_dict() for anomaly in group.supporting_anomalies
            ],
        }


def _build_demo_service() -> BgpRemediationService:
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

    tracker.ingest_snapshot(
        snapshot_1[0].timestamp_ms,
        snapshot_1 + sibling_before,
    )
    tracker.ingest_snapshot(
        snapshot_2[0].timestamp_ms,
        snapshot_2 + sibling_after,
    )

    from_ts = snapshot_1[0].timestamp_ms
    to_ts = snapshot_2[0].timestamp_ms

    summaries = tracker.peer_summaries_at(to_ts)
    events = tracker.route_events_for_diff(from_ts, to_ts)

    anomalies = BgpAnomalyDetector(
        received_major_drop_pct=20.0,
        received_critical_drop_pct=50.0,
        advertised_major_drop_pct=20.0,
        advertised_critical_drop_pct=50.0,
        churn_event_threshold=3,
    ).detect_from_tracker(
        tracker=tracker,
        from_timestamp_ms=from_ts,
        to_timestamp_ms=to_ts,
    )

    history_store = BgpHistoryStore()
    history_store.store_route_snapshot_rows(snapshot_1 + sibling_before)
    history_store.store_route_snapshot_rows(snapshot_2 + sibling_after)
    history_store.store_peer_summary_rows(summaries)
    history_store.store_route_event_rows(events)
    history_store.store_anomaly_rows(anomalies)

    return BgpRemediationService(
        tracker=tracker,
        history_store=history_store,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )

    service = _build_demo_service()

    response = service.handle(
        BgpRemediationServiceRequest(
            device="leaf-01",
            peer="10.0.0.1",
            network_instance="default",
            afi_safi="ipv4_unicast",
            plan_only=False,
            execute=True,
        )
    )

    print(json.dumps(response.to_dict(), indent=2))


if __name__ == "__main__":
    main()
