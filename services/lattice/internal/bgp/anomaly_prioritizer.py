from __future__ import annotations

from dataclasses import dataclass, field

from internal.bgp.anomaly_detector import BgpAnomaly

ANOMALY_PRIORITY = {
    "received_route_zero": 100,
    "advertised_route_zero": 90,
    "received_route_slash": 80,
    "advertised_route_slash": 70,
    "route_churn_spike": 10,
}


@dataclass(frozen=True)
class PrioritizedAnomalyGroup:
    """
    One grouped anomaly decision for a peer and time window.

    primary_anomaly drives remediation.
    supporting_anomalies provide context without creating duplicate actions.
    """

    primary_anomaly: BgpAnomaly
    supporting_anomalies: list[BgpAnomaly] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "primary_anomaly": self.primary_anomaly.to_dict(),
            "supporting_anomalies": [
                anomaly.to_dict() for anomaly in self.supporting_anomalies
            ],
        }


class BgpAnomalyPrioritizer:
    """
    Suppress weaker anomalies when a stronger anomaly already explains the issue.

    Example:
    received_route_slash should dominate route_churn_spike for the same peer
    and time window.
    """

    def prioritize(
        self,
        anomalies: list[BgpAnomaly],
    ) -> list[PrioritizedAnomalyGroup]:
        grouped: dict[str, list[BgpAnomaly]] = {}

        for anomaly in anomalies:
            key = self._group_key(anomaly)
            grouped.setdefault(key, []).append(anomaly)

        results: list[PrioritizedAnomalyGroup] = []

        for group in grouped.values():
            ranked = sorted(group, key=self._sort_key, reverse=True)
            results.append(
                PrioritizedAnomalyGroup(
                    primary_anomaly=ranked[0],
                    supporting_anomalies=ranked[1:],
                )
            )

        return sorted(
            results,
            key=lambda item: (
                item.primary_anomaly.timestamp_ms,
                item.primary_anomaly.device,
                item.primary_anomaly.peer,
                item.primary_anomaly.afi_safi,
            ),
        )

    def _group_key(self, anomaly: BgpAnomaly) -> str:
        return "|".join(
            [
                str(anomaly.timestamp_ms),
                anomaly.device,
                anomaly.network_instance,
                anomaly.peer,
                anomaly.afi_safi,
            ]
        )

    def _sort_key(self, anomaly: BgpAnomaly) -> tuple[int, int]:
        priority = ANOMALY_PRIORITY.get(anomaly.anomaly_type, 0)
        severity = self._severity_rank(anomaly.severity)
        return (priority, severity)

    def _severity_rank(self, severity: str) -> int:
        mapping = {
            "critical": 3,
            "major": 2,
            "minor": 1,
        }
        return mapping.get(severity, 0)
