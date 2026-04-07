from __future__ import annotations

import json
import logging
from pathlib import Path

from internal.bgp.anomaly_detector import BgpAnomalyDetector
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

    events = tracker.route_events_for_diff(
        snapshot_1[0].timestamp_ms,
        snapshot_2[0].timestamp_ms,
    )
    summaries = tracker.peer_summaries_at(snapshot_2[0].timestamp_ms)

    detector = BgpAnomalyDetector(
        received_major_drop_pct=20.0,
        received_critical_drop_pct=50.0,
        advertised_major_drop_pct=20.0,
        advertised_critical_drop_pct=50.0,
        churn_event_threshold=3,
    )
    anomalies = detector.detect_from_tracker(
        tracker=tracker,
        from_timestamp_ms=snapshot_1[0].timestamp_ms,
        to_timestamp_ms=snapshot_2[0].timestamp_ms,
    )

    store = BgpHistoryStore()
    store.store_route_snapshot_rows(snapshot_1)
    store.store_route_snapshot_rows(snapshot_2)
    store.store_peer_summary_rows(summaries)
    store.store_route_event_rows(events)
    store.store_anomaly_rows(anomalies)

    latest_received = store.routes_at_or_before(
        timestamp_ms=snapshot_2[0].timestamp_ms,
        peer="10.0.0.1",
        direction="received",
        afi_safi="ipv4_unicast",
    )
    removed = store.route_events_between(
        start_ts=snapshot_1[0].timestamp_ms,
        end_ts=snapshot_2[0].timestamp_ms,
        peer="10.0.0.1",
        direction="received",
        afi_safi="ipv4_unicast",
        event_type="route_removed",
    )

    print("LATEST RECEIVED ROUTES")
    print(json.dumps([row.to_dict() for row in latest_received], indent=2))
    print()

    print("REMOVED ROUTES IN WINDOW")
    print(json.dumps([row.to_dict() for row in removed], indent=2))
    print()

    output_dir = Path("data/generated/bgp_history")
    store.write_json_artifacts(output_dir)
    print(f"WROTE: {output_dir}")


if __name__ == "__main__":
    main()
