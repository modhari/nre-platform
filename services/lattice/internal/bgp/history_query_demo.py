from __future__ import annotations

import json
import logging

from internal.bgp.anomaly_detector import BgpAnomalyDetector
from internal.bgp.history_query_service import (
    BgpHistoryQueryRequest,
    BgpHistoryQueryService,
)
from internal.bgp.history_store import BgpHistoryStore
from internal.bgp.route_state_tracker import BgpRouteStateTracker, build_demo_routes


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )

    tracker = BgpRouteStateTracker()
    snapshot_1, snapshot_2 = build_demo_routes()

    tracker.ingest_snapshot(snapshot_1[0].timestamp_ms, snapshot_1)
    tracker.ingest_snapshot(snapshot_2[0].timestamp_ms, snapshot_2)

    from_ts = snapshot_1[0].timestamp_ms
    to_ts = snapshot_2[0].timestamp_ms

    events = tracker.route_events_for_diff(from_ts, to_ts)
    summaries = tracker.peer_summaries_at(to_ts)

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
    store.store_route_snapshot_rows(snapshot_1)
    store.store_route_snapshot_rows(snapshot_2)
    store.store_peer_summary_rows(summaries)
    store.store_route_event_rows(events)
    store.store_anomaly_rows(anomalies)

    service = BgpHistoryQueryService(history_store=store)

    requests = [
        BgpHistoryQueryRequest(
            device="leaf-01",
            peer="10.0.0.1",
            direction="received",
            afi_safi="ipv4_unicast",
            timestamp_ms=to_ts,
            query_type="routes_at_time",
        ),
        BgpHistoryQueryRequest(
            device="leaf-01",
            peer="10.0.0.1",
            direction="received",
            afi_safi="ipv4_unicast",
            start_ts=from_ts,
            end_ts=to_ts,
            query_type="removed_routes_between",
        ),
        BgpHistoryQueryRequest(
            device="leaf-01",
            peer="10.0.0.1",
            afi_safi="ipv4_unicast",
            timestamp_ms=to_ts,
            query_type="peer_summaries_at_time",
        ),
        BgpHistoryQueryRequest(
            device="leaf-01",
            peer="10.0.0.1",
            start_ts=from_ts,
            end_ts=to_ts,
            query_type="anomalies_between",
        ),
    ]

    responses = [service.handle(request).to_dict() for request in requests]
    print(json.dumps(responses, indent=2))


if __name__ == "__main__":
    main()
