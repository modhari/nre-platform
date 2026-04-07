from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from internal.bgp.anomaly_detector import BgpAnomalyDetector
from internal.bgp.anomaly_prioritizer import BgpAnomalyPrioritizer
from internal.bgp.models import BgpRouteRecord
from internal.bgp.remediation_planner import BgpRemediationPlanner
from internal.bgp.route_state_tracker import BgpRouteStateTracker


@dataclass(frozen=True)
class Scenario:
    name: str
    before_routes: list[BgpRouteRecord]
    after_routes: list[BgpRouteRecord]


def _common_fields() -> dict[str, str]:
    return {
        "device": "leaf-01",
        "network_instance": "default",
        "peer": "10.0.0.1",
        "afi_safi": "ipv4_unicast",
        "region": "us-west",
        "pop": "sjc",
        "fabric": "clos-a",
    }


def _route(
    *,
    ts: int,
    direction: str,
    prefix: str,
    next_hop: str,
    as_path: str,
    local_pref: int,
) -> BgpRouteRecord:
    return BgpRouteRecord(
        timestamp_ms=ts,
        direction=direction,
        prefix=prefix,
        next_hop=next_hop,
        as_path=as_path,
        local_pref=local_pref,
        **_common_fields(),
    )


def build_received_route_zero_scenario() -> Scenario:
    ts1 = 1711812000000
    ts2 = 1711812600000

    before_routes = [
        _route(
            ts=ts1,
            direction="received",
            prefix="10.10.0.0/24",
            next_hop="10.0.0.1",
            as_path="64512 64513",
            local_pref=100,
        ),
        _route(
            ts=ts1,
            direction="received",
            prefix="10.20.0.0/24",
            next_hop="10.0.0.1",
            as_path="64512 64513",
            local_pref=100,
        ),
        _route(
            ts=ts1,
            direction="advertised",
            prefix="192.0.2.0/24",
            next_hop="self",
            as_path="65000",
            local_pref=200,
        ),
    ]

    after_routes = [
        _route(
            ts=ts2,
            direction="advertised",
            prefix="192.0.2.0/24",
            next_hop="self",
            as_path="65000",
            local_pref=200,
        ),
    ]

    return Scenario(
        name="received_route_zero",
        before_routes=before_routes,
        after_routes=after_routes,
    )


def build_received_route_slash_scenario() -> Scenario:
    ts1 = 1711812000000
    ts2 = 1711812600000

    before_routes = [
        _route(
            ts=ts1,
            direction="received",
            prefix="10.10.0.0/24",
            next_hop="10.0.0.1",
            as_path="64512 64513",
            local_pref=100,
        ),
        _route(
            ts=ts1,
            direction="received",
            prefix="10.20.0.0/24",
            next_hop="10.0.0.1",
            as_path="64512 64513",
            local_pref=100,
        ),
        _route(
            ts=ts1,
            direction="received",
            prefix="10.30.0.0/24",
            next_hop="10.0.0.1",
            as_path="64512 64513",
            local_pref=100,
        ),
        _route(
            ts=ts1,
            direction="received",
            prefix="10.40.0.0/24",
            next_hop="10.0.0.1",
            as_path="64512 64513",
            local_pref=100,
        ),
        _route(
            ts=ts1,
            direction="advertised",
            prefix="192.0.2.0/24",
            next_hop="self",
            as_path="65000",
            local_pref=200,
        ),
    ]

    after_routes = [
        _route(
            ts=ts2,
            direction="received",
            prefix="10.10.0.0/24",
            next_hop="10.0.0.1",
            as_path="64512 64513",
            local_pref=100,
        ),
        _route(
            ts=ts2,
            direction="advertised",
            prefix="192.0.2.0/24",
            next_hop="self",
            as_path="65000",
            local_pref=200,
        ),
    ]

    return Scenario(
        name="received_route_slash",
        before_routes=before_routes,
        after_routes=after_routes,
    )


def build_advertised_route_zero_scenario() -> Scenario:
    ts1 = 1711812000000
    ts2 = 1711812600000

    before_routes = [
        _route(
            ts=ts1,
            direction="received",
            prefix="10.10.0.0/24",
            next_hop="10.0.0.1",
            as_path="64512 64513",
            local_pref=100,
        ),
        _route(
            ts=ts1,
            direction="advertised",
            prefix="192.0.2.0/24",
            next_hop="self",
            as_path="65000",
            local_pref=200,
        ),
        _route(
            ts=ts1,
            direction="advertised",
            prefix="198.51.100.0/24",
            next_hop="self",
            as_path="65000",
            local_pref=200,
        ),
    ]

    after_routes = [
        _route(
            ts=ts2,
            direction="received",
            prefix="10.10.0.0/24",
            next_hop="10.0.0.1",
            as_path="64512 64513",
            local_pref=100,
        ),
    ]

    return Scenario(
        name="advertised_route_zero",
        before_routes=before_routes,
        after_routes=after_routes,
    )


def build_route_churn_scenario() -> Scenario:
    ts1 = 1711812000000
    ts2 = 1711812600000

    before_routes = [
        _route(
            ts=ts1,
            direction="received",
            prefix="10.10.0.0/24",
            next_hop="10.0.0.1",
            as_path="64512 64513",
            local_pref=100,
        ),
        _route(
            ts=ts1,
            direction="received",
            prefix="10.20.0.0/24",
            next_hop="10.0.0.1",
            as_path="64512 64513",
            local_pref=100,
        ),
        _route(
            ts=ts1,
            direction="received",
            prefix="10.30.0.0/24",
            next_hop="10.0.0.1",
            as_path="64512 64513",
            local_pref=100,
        ),
        _route(
            ts=ts1,
            direction="advertised",
            prefix="192.0.2.0/24",
            next_hop="self",
            as_path="65000",
            local_pref=200,
        ),
    ]

    after_routes = [
        _route(
            ts=ts2,
            direction="received",
            prefix="10.10.0.0/24",
            next_hop="10.0.0.1",
            as_path="64512 64513",
            local_pref=100,
        ),
        _route(
            ts=ts2,
            direction="received",
            prefix="10.30.0.0/24",
            next_hop="10.0.0.1",
            as_path="64512 64513",
            local_pref=100,
        ),
        _route(
            ts=ts2,
            direction="received",
            prefix="10.40.0.0/24",
            next_hop="10.0.0.1",
            as_path="64512 64514",
            local_pref=100,
        ),
        _route(
            ts=ts2,
            direction="advertised",
            prefix="192.0.2.0/24",
            next_hop="self",
            as_path="65000",
            local_pref=150,
        ),
    ]

    return Scenario(
        name="route_churn_spike",
        before_routes=before_routes,
        after_routes=after_routes,
    )


def run_scenario(scenario: Scenario) -> dict:
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
    prioritized_groups = prioritizer.prioritize(anomalies)

    planner = BgpRemediationPlanner()
    recommendations = planner.plan(
        anomalies=[group.primary_anomaly for group in prioritized_groups],
        current_summaries=summaries,
        diff=diff,
    )

    recommendation_by_type = {
        item.anomaly_type: item.to_dict()
        for item in recommendations
    }

    return {
        "scenario": scenario.name,
        "raw_anomalies": [item.to_dict() for item in anomalies],
        "prioritized_anomalies": [group.to_dict() for group in prioritized_groups],
        "recommendations": list(recommendation_by_type.values()),
        "added_routes": [item.to_dict() for item in diff.added_routes],
        "removed_routes": [item.to_dict() for item in diff.removed_routes],
        "changed_routes": [item.to_dict() for item in diff.changed_routes],
    }


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )

    scenarios = [
        build_received_route_zero_scenario(),
        build_received_route_slash_scenario(),
        build_advertised_route_zero_scenario(),
        build_route_churn_scenario(),
    ]

    results = [run_scenario(scenario) for scenario in scenarios]
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
