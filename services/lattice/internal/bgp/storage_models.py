from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class BgpRouteSnapshotRow:
    """
    One stored route observation at one time.
    """

    ts: int
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BgpPeerRouteSummaryRow:
    """
    Aggregate received and advertised route counts per peer.
    """

    ts: int
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
class BgpRouteEventRow:
    """
    Change event between two snapshots.
    """

    ts: int
    device: str
    network_instance: str
    peer: str
    direction: str
    afi_safi: str
    prefix: str
    event_type: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BgpAnomalyRow:
    """
    Stored anomaly record for later analysis and remediation.
    """

    ts: int
    device: str
    network_instance: str
    peer: str
    afi_safi: str
    anomaly_type: str
    severity: str
    blast_radius: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
