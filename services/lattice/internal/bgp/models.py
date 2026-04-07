from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class BgpRouteRecord:
    """
    Canonical BGP route record for one prefix at one collection time.

    The identity of a route observation is intentionally narrow:
    device, network instance, peer, direction, address family, and prefix.

    Everything else is route metadata that may change over time.
    """

    timestamp_ms: int
    device: str
    network_instance: str
    peer: str
    direction: str
    afi_safi: str
    prefix: str
    next_hop: str | None = None
    as_path: str | None = None
    local_pref: int | None = None
    med: int | None = None
    communities: list[str] = field(default_factory=list)
    origin: str | None = None
    best_path: bool | None = None
    validation_state: str | None = None
    region: str | None = None
    pop: str | None = None
    fabric: str | None = None
    labels: dict[str, str] = field(default_factory=dict)

    def identity_key(self) -> str:
        return "|".join(
            [
                self.device,
                self.network_instance,
                self.peer,
                self.direction,
                self.afi_safi,
                self.prefix,
            ]
        )

    def peer_key(self) -> str:
        return "|".join(
            [
                self.device,
                self.network_instance,
                self.peer,
                self.afi_safi,
            ]
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BgpRouteEvent:
    """
    Change event between two snapshots.

    event_type is expected to be one of:
    route_added
    route_removed
    route_changed
    """

    timestamp_ms: int
    event_type: str
    device: str
    network_instance: str
    peer: str
    direction: str
    afi_safi: str
    prefix: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BgpPeerRouteSummary:
    """
    Aggregate route counts for one peer and address family at one snapshot.
    """

    timestamp_ms: int
    device: str
    network_instance: str
    peer: str
    afi_safi: str
    received_prefix_count: int
    advertised_prefix_count: int
    region: str | None = None
    pop: str | None = None
    fabric: str | None = None

    def peer_key(self) -> str:
        return "|".join(
            [
                self.device,
                self.network_instance,
                self.peer,
                self.afi_safi,
            ]
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SnapshotDiff:
    """
    Diff between two route snapshots.
    """

    from_timestamp_ms: int
    to_timestamp_ms: int
    added_routes: list[BgpRouteRecord]
    removed_routes: list[BgpRouteRecord]
    changed_routes: list[BgpRouteEvent]
    peer_summaries: list[BgpPeerRouteSummary]

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_timestamp_ms": self.from_timestamp_ms,
            "to_timestamp_ms": self.to_timestamp_ms,
            "added_routes": [route.to_dict() for route in self.added_routes],
            "removed_routes": [route.to_dict() for route in self.removed_routes],
            "changed_routes": [event.to_dict() for event in self.changed_routes],
            "peer_summaries": [summary.to_dict() for summary in self.peer_summaries],
        }
