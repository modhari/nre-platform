from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from internal.bgp.models import BgpPeerRouteSummary, SnapshotDiff
from internal.bgp.route_state_tracker import BgpRouteStateTracker, build_demo_routes

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class BgpAnomaly:
    """
    A classified BGP routing anomaly for one peer and address family.
    """

    timestamp_ms: int
    anomaly_type: str
    severity: str
    blast_radius: str
    device: str
    network_instance: str
    peer: str
    afi_safi: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BgpAnomalyDetector:
    """
    Detect route slash and churn anomalies from peer summaries and diffs.

    This first version is intentionally simple and deterministic.
    Later it can incorporate peer type, policy changes, sibling device
    comparisons, and topology wide baselines.
    """

    def __init__(
        self,
        received_major_drop_pct: float = 30.0,
        received_critical_drop_pct: float = 70.0,
        advertised_major_drop_pct: float = 30.0,
        advertised_critical_drop_pct: float = 70.0,
        churn_event_threshold: int = 20,
    ) -> None:
        self.received_major_drop_pct = received_major_drop_pct
        self.received_critical_drop_pct = received_critical_drop_pct
        self.advertised_major_drop_pct = advertised_major_drop_pct
        self.advertised_critical_drop_pct = advertised_critical_drop_pct
        self.churn_event_threshold = churn_event_threshold

    def detect_from_tracker(
        self,
        tracker: BgpRouteStateTracker,
        from_timestamp_ms: int,
        to_timestamp_ms: int,
    ) -> list[BgpAnomaly]:
        diff = tracker.diff_snapshots(from_timestamp_ms, to_timestamp_ms)
        previous_summaries = tracker.peer_summaries_at(from_timestamp_ms)
        current_summaries = tracker.peer_summaries_at(to_timestamp_ms)
        return self.detect(
            diff=diff,
            previous_summaries=previous_summaries,
            current_summaries=current_summaries,
        )

    def detect(
        self,
        diff: SnapshotDiff,
        previous_summaries: list[BgpPeerRouteSummary],
        current_summaries: list[BgpPeerRouteSummary],
    ) -> list[BgpAnomaly]:
        anomalies: list[BgpAnomaly] = []

        previous_by_key = {summary.peer_key(): summary for summary in previous_summaries}
        current_by_key = {summary.peer_key(): summary for summary in current_summaries}

        all_keys = sorted(set(previous_by_key) | set(current_by_key))

        for peer_key in all_keys:
            previous = previous_by_key.get(peer_key)
            current = current_by_key.get(peer_key)

            if current is None and previous is not None:
                current = BgpPeerRouteSummary(
                    timestamp_ms=diff.to_timestamp_ms,
                    device=previous.device,
                    network_instance=previous.network_instance,
                    peer=previous.peer,
                    afi_safi=previous.afi_safi,
                    received_prefix_count=0,
                    advertised_prefix_count=0,
                    region=previous.region,
                    pop=previous.pop,
                    fabric=previous.fabric,
                )

            if previous is None and current is not None:
                previous = BgpPeerRouteSummary(
                    timestamp_ms=diff.from_timestamp_ms,
                    device=current.device,
                    network_instance=current.network_instance,
                    peer=current.peer,
                    afi_safi=current.afi_safi,
                    received_prefix_count=0,
                    advertised_prefix_count=0,
                    region=current.region,
                    pop=current.pop,
                    fabric=current.fabric,
                )

            if previous is None or current is None:
                continue

            anomalies.extend(
                self._detect_received_anomalies(
                    previous=previous,
                    current=current,
                    timestamp_ms=diff.to_timestamp_ms,
                )
            )
            anomalies.extend(
                self._detect_advertised_anomalies(
                    previous=previous,
                    current=current,
                    timestamp_ms=diff.to_timestamp_ms,
                )
            )

        anomalies.extend(self._detect_churn(diff))
        return anomalies

    def _detect_received_anomalies(
        self,
        previous: BgpPeerRouteSummary,
        current: BgpPeerRouteSummary,
        timestamp_ms: int,
    ) -> list[BgpAnomaly]:
        anomalies: list[BgpAnomaly] = []

        old_count = previous.received_prefix_count
        new_count = current.received_prefix_count
        drop_pct = self._drop_pct(old_count, new_count)

        if old_count > 0 and new_count == 0:
            anomalies.append(
                self._build_anomaly(
                    timestamp_ms=timestamp_ms,
                    anomaly_type="received_route_zero",
                    severity="critical",
                    peer=current,
                    details={
                        "old_received_prefix_count": old_count,
                        "new_received_prefix_count": new_count,
                        "drop_pct": drop_pct,
                    },
                )
            )
            return anomalies

        if drop_pct >= self.received_critical_drop_pct:
            anomalies.append(
                self._build_anomaly(
                    timestamp_ms=timestamp_ms,
                    anomaly_type="received_route_slash",
                    severity="critical",
                    peer=current,
                    details={
                        "old_received_prefix_count": old_count,
                        "new_received_prefix_count": new_count,
                        "drop_pct": drop_pct,
                    },
                )
            )
        elif drop_pct >= self.received_major_drop_pct:
            anomalies.append(
                self._build_anomaly(
                    timestamp_ms=timestamp_ms,
                    anomaly_type="received_route_slash",
                    severity="major",
                    peer=current,
                    details={
                        "old_received_prefix_count": old_count,
                        "new_received_prefix_count": new_count,
                        "drop_pct": drop_pct,
                    },
                )
            )

        return anomalies

    def _detect_advertised_anomalies(
        self,
        previous: BgpPeerRouteSummary,
        current: BgpPeerRouteSummary,
        timestamp_ms: int,
    ) -> list[BgpAnomaly]:
        anomalies: list[BgpAnomaly] = []

        old_count = previous.advertised_prefix_count
        new_count = current.advertised_prefix_count
        drop_pct = self._drop_pct(old_count, new_count)

        if old_count > 0 and new_count == 0:
            anomalies.append(
                self._build_anomaly(
                    timestamp_ms=timestamp_ms,
                    anomaly_type="advertised_route_zero",
                    severity="critical",
                    peer=current,
                    details={
                        "old_advertised_prefix_count": old_count,
                        "new_advertised_prefix_count": new_count,
                        "drop_pct": drop_pct,
                    },
                )
            )
            return anomalies

        if drop_pct >= self.advertised_critical_drop_pct:
            anomalies.append(
                self._build_anomaly(
                    timestamp_ms=timestamp_ms,
                    anomaly_type="advertised_route_slash",
                    severity="critical",
                    peer=current,
                    details={
                        "old_advertised_prefix_count": old_count,
                        "new_advertised_prefix_count": new_count,
                        "drop_pct": drop_pct,
                    },
                )
            )
        elif drop_pct >= self.advertised_major_drop_pct:
            anomalies.append(
                self._build_anomaly(
                    timestamp_ms=timestamp_ms,
                    anomaly_type="advertised_route_slash",
                    severity="major",
                    peer=current,
                    details={
                        "old_advertised_prefix_count": old_count,
                        "new_advertised_prefix_count": new_count,
                        "drop_pct": drop_pct,
                    },
                )
            )

        return anomalies

    def _detect_churn(self, diff: SnapshotDiff) -> list[BgpAnomaly]:
        event_count = (
            len(diff.added_routes)
            + len(diff.removed_routes)
            + len(diff.changed_routes)
        )

        if event_count < self.churn_event_threshold:
            return []

        summaries = diff.peer_summaries
        if not summaries:
            return []

        peer = summaries[0]
        return [
            self._build_anomaly(
                timestamp_ms=diff.to_timestamp_ms,
                anomaly_type="route_churn_spike",
                severity="major",
                peer=peer,
                details={
                    "event_count": event_count,
                    "added_routes": len(diff.added_routes),
                    "removed_routes": len(diff.removed_routes),
                    "changed_routes": len(diff.changed_routes),
                },
            )
        ]

    def _build_anomaly(
        self,
        timestamp_ms: int,
        anomaly_type: str,
        severity: str,
        peer: BgpPeerRouteSummary,
        details: dict[str, Any],
    ) -> BgpAnomaly:
        return BgpAnomaly(
            timestamp_ms=timestamp_ms,
            anomaly_type=anomaly_type,
            severity=severity,
            blast_radius="peer_only",
            device=peer.device,
            network_instance=peer.network_instance,
            peer=peer.peer,
            afi_safi=peer.afi_safi,
            details=details,
        )

    def _drop_pct(self, old_count: int, new_count: int) -> float:
        if old_count <= 0:
            return 0.0
        if new_count >= old_count:
            return 0.0
        return ((old_count - new_count) / old_count) * 100.0


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

    print("ANOMALIES")
    print(json.dumps([anomaly.to_dict() for anomaly in anomalies], indent=2))


if __name__ == "__main__":
    main()
