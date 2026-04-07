from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

from internal.bgp.models import (
    BgpPeerRouteSummary,
    BgpRouteEvent,
    BgpRouteRecord,
    SnapshotDiff,
)

LOG = logging.getLogger(__name__)


class BgpRouteStateTracker:
    """
    Track BGP route snapshots and compute diffs between times.

    This first version keeps data in memory and writes JSON artifacts for
    inspection. Later this can be backed by ClickHouse, BigQuery, or Kafka.
    """

    def __init__(self) -> None:
        self.snapshots: dict[int, dict[str, BgpRouteRecord]] = {}

    def ingest_snapshot(
        self,
        timestamp_ms: int,
        routes: list[BgpRouteRecord],
    ) -> None:
        """
        Store one complete snapshot keyed by route identity.
        """
        snapshot: dict[str, BgpRouteRecord] = {}

        for route in routes:
            if route.timestamp_ms != timestamp_ms:
                raise ValueError(
                    "All routes in a snapshot must share the snapshot timestamp"
                )
            snapshot[route.identity_key()] = route

        self.snapshots[timestamp_ms] = snapshot
        LOG.info(
            "Stored BGP route snapshot at %s with %s routes",
            timestamp_ms,
            len(snapshot),
        )

    def available_timestamps(self) -> list[int]:
        return sorted(self.snapshots.keys())

    def get_snapshot(self, timestamp_ms: int) -> list[BgpRouteRecord]:
        snapshot = self.snapshots.get(timestamp_ms, {})
        return list(snapshot.values())

    def nearest_snapshot_at_or_before(self, timestamp_ms: int) -> int | None:
        candidates = [ts for ts in self.snapshots if ts <= timestamp_ms]
        if not candidates:
            return None
        return max(candidates)

    def diff_snapshots(
        self,
        from_timestamp_ms: int,
        to_timestamp_ms: int,
    ) -> SnapshotDiff:
        before = self.snapshots.get(from_timestamp_ms)
        after = self.snapshots.get(to_timestamp_ms)

        if before is None:
            raise KeyError(f"Missing snapshot for from_timestamp_ms={from_timestamp_ms}")
        if after is None:
            raise KeyError(f"Missing snapshot for to_timestamp_ms={to_timestamp_ms}")

        before_keys = set(before.keys())
        after_keys = set(after.keys())

        added_keys = sorted(after_keys - before_keys)
        removed_keys = sorted(before_keys - after_keys)
        common_keys = sorted(before_keys & after_keys)

        added_routes = [after[key] for key in added_keys]
        removed_routes = [before[key] for key in removed_keys]
        changed_routes: list[BgpRouteEvent] = []

        for key in common_keys:
            old = before[key]
            new = after[key]
            details = self._attribute_changes(old, new)
            if details:
                changed_routes.append(
                    BgpRouteEvent(
                        timestamp_ms=to_timestamp_ms,
                        event_type="route_changed",
                        device=new.device,
                        network_instance=new.network_instance,
                        peer=new.peer,
                        direction=new.direction,
                        afi_safi=new.afi_safi,
                        prefix=new.prefix,
                        details=details,
                    )
                )

        summaries = self._build_peer_summaries(to_timestamp_ms, list(after.values()))

        return SnapshotDiff(
            from_timestamp_ms=from_timestamp_ms,
            to_timestamp_ms=to_timestamp_ms,
            added_routes=added_routes,
            removed_routes=removed_routes,
            changed_routes=changed_routes,
            peer_summaries=summaries,
        )

    def route_events_for_diff(
        self,
        from_timestamp_ms: int,
        to_timestamp_ms: int,
    ) -> list[BgpRouteEvent]:
        diff = self.diff_snapshots(from_timestamp_ms, to_timestamp_ms)
        events: list[BgpRouteEvent] = []

        for route in diff.added_routes:
            events.append(
                BgpRouteEvent(
                    timestamp_ms=to_timestamp_ms,
                    event_type="route_added",
                    device=route.device,
                    network_instance=route.network_instance,
                    peer=route.peer,
                    direction=route.direction,
                    afi_safi=route.afi_safi,
                    prefix=route.prefix,
                    details={},
                )
            )

        for route in diff.removed_routes:
            events.append(
                BgpRouteEvent(
                    timestamp_ms=to_timestamp_ms,
                    event_type="route_removed",
                    device=route.device,
                    network_instance=route.network_instance,
                    peer=route.peer,
                    direction=route.direction,
                    afi_safi=route.afi_safi,
                    prefix=route.prefix,
                    details={},
                )
            )

        events.extend(diff.changed_routes)
        return events

    def peer_summaries_at(self, timestamp_ms: int) -> list[BgpPeerRouteSummary]:
        snapshot = self.snapshots.get(timestamp_ms)
        if snapshot is None:
            raise KeyError(f"Missing snapshot for timestamp_ms={timestamp_ms}")
        return self._build_peer_summaries(timestamp_ms, list(snapshot.values()))

    def write_snapshot_json(self, timestamp_ms: int, output_path: Path) -> None:
        snapshot = self.get_snapshot(timestamp_ms)
        payload = {
            "timestamp_ms": timestamp_ms,
            "route_count": len(snapshot),
            "routes": [route.to_dict() for route in snapshot],
        }
        self._write_json(output_path, payload)

    def write_diff_json(
        self,
        from_timestamp_ms: int,
        to_timestamp_ms: int,
        output_path: Path,
    ) -> None:
        diff = self.diff_snapshots(from_timestamp_ms, to_timestamp_ms)
        self._write_json(output_path, diff.to_dict())

    def _build_peer_summaries(
        self,
        timestamp_ms: int,
        routes: list[BgpRouteRecord],
    ) -> list[BgpPeerRouteSummary]:
        grouped: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "device": "",
                "network_instance": "",
                "peer": "",
                "afi_safi": "",
                "received_prefix_count": 0,
                "advertised_prefix_count": 0,
                "region": None,
                "pop": None,
                "fabric": None,
            }
        )

        for route in routes:
            key = route.peer_key()
            item = grouped[key]
            item["device"] = route.device
            item["network_instance"] = route.network_instance
            item["peer"] = route.peer
            item["afi_safi"] = route.afi_safi
            item["region"] = route.region
            item["pop"] = route.pop
            item["fabric"] = route.fabric

            if route.direction == "received":
                item["received_prefix_count"] += 1
            elif route.direction == "advertised":
                item["advertised_prefix_count"] += 1

        summaries = [
            BgpPeerRouteSummary(
                timestamp_ms=timestamp_ms,
                device=item["device"],
                network_instance=item["network_instance"],
                peer=item["peer"],
                afi_safi=item["afi_safi"],
                received_prefix_count=item["received_prefix_count"],
                advertised_prefix_count=item["advertised_prefix_count"],
                region=item["region"],
                pop=item["pop"],
                fabric=item["fabric"],
            )
            for item in grouped.values()
        ]

        return sorted(
            summaries,
            key=lambda summary: (
                summary.device,
                summary.network_instance,
                summary.peer,
                summary.afi_safi,
            ),
        )

    def _attribute_changes(
        self,
        old: BgpRouteRecord,
        new: BgpRouteRecord,
    ) -> dict[str, Any]:
        old_dict = asdict(old)
        new_dict = asdict(new)

        ignored_keys = {"timestamp_ms", "labels"}
        changes: dict[str, Any] = {}

        for key in sorted(old_dict.keys()):
            if key in ignored_keys:
                continue
            if old_dict[key] != new_dict[key]:
                changes[key] = {
                    "old": old_dict[key],
                    "new": new_dict[key],
                }

        return changes

    def _write_json(self, output_path: Path, payload: dict[str, Any]) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(payload, indent=2),
            encoding="utf_8",
        )
        LOG.info("Wrote artifact to %s", output_path)


def build_demo_routes() -> tuple[list[BgpRouteRecord], list[BgpRouteRecord]]:
    """
    Two snapshots for quick testing.

    Snapshot 1 has three received routes and one advertised route.
    Snapshot 2 removes one received route, adds one received route,
    and changes local preference on one advertised route.
    """
    ts1 = 1711812000000
    ts2 = 1711812600000

    common = {
        "device": "leaf-01",
        "network_instance": "default",
        "peer": "10.0.0.1",
        "afi_safi": "ipv4_unicast",
        "region": "us-west",
        "pop": "sjc",
        "fabric": "clos-a",
    }

    snapshot_1 = [
        BgpRouteRecord(
            timestamp_ms=ts1,
            direction="received",
            prefix="10.10.0.0/24",
            next_hop="10.0.0.1",
            as_path="64512 64513",
            local_pref=100,
            **common,
        ),
        BgpRouteRecord(
            timestamp_ms=ts1,
            direction="received",
            prefix="10.20.0.0/24",
            next_hop="10.0.0.1",
            as_path="64512 64513",
            local_pref=100,
            **common,
        ),
        BgpRouteRecord(
            timestamp_ms=ts1,
            direction="received",
            prefix="10.30.0.0/24",
            next_hop="10.0.0.1",
            as_path="64512 64513",
            local_pref=100,
            **common,
        ),
        BgpRouteRecord(
            timestamp_ms=ts1,
            direction="advertised",
            prefix="192.0.2.0/24",
            next_hop="self",
            as_path="65000",
            local_pref=200,
            **common,
        ),
    ]

    snapshot_2 = [
        BgpRouteRecord(
            timestamp_ms=ts2,
            direction="received",
            prefix="10.10.0.0/24",
            next_hop="10.0.0.1",
            as_path="64512 64513",
            local_pref=100,
            **common,
        ),
        BgpRouteRecord(
            timestamp_ms=ts2,
            direction="received",
            prefix="10.30.0.0/24",
            next_hop="10.0.0.1",
            as_path="64512 64513",
            local_pref=100,
            **common,
        ),
        BgpRouteRecord(
            timestamp_ms=ts2,
            direction="received",
            prefix="10.40.0.0/24",
            next_hop="10.0.0.1",
            as_path="64512 64514",
            local_pref=100,
            **common,
        ),
        BgpRouteRecord(
            timestamp_ms=ts2,
            direction="advertised",
            prefix="192.0.2.0/24",
            next_hop="self",
            as_path="65000",
            local_pref=150,
            **common,
        ),
    ]

    return snapshot_1, snapshot_2


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

    diff = tracker.diff_snapshots(
        snapshot_1[0].timestamp_ms,
        snapshot_2[0].timestamp_ms,
    )
    events = tracker.route_events_for_diff(
        snapshot_1[0].timestamp_ms,
        snapshot_2[0].timestamp_ms,
    )

    print("AVAILABLE SNAPSHOTS")
    print(tracker.available_timestamps())
    print()

    print("PEER SUMMARIES AT LATEST SNAPSHOT")
    print(json.dumps([summary.to_dict() for summary in diff.peer_summaries], indent=2))
    print()

    print("DIFF")
    print(json.dumps(diff.to_dict(), indent=2))
    print()

    print("EVENTS")
    print(json.dumps([event.to_dict() for event in events], indent=2))


if __name__ == "__main__":
    main()
