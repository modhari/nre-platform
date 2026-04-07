from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from internal.bgp.history_store import BgpHistoryStore


@dataclass(frozen=True)
class BgpHistoryQueryRequest:
    device: str | None = None
    peer: str | None = None
    network_instance: str | None = None
    direction: str | None = None
    afi_safi: str | None = None
    timestamp_ms: int | None = None
    start_ts: int | None = None
    end_ts: int | None = None
    query_type: str = "routes_at_time"


@dataclass
class BgpHistoryQueryResponse:
    request: dict[str, Any]
    results: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BgpHistoryQueryService:
    """
    Service layer for historical BGP state queries.
    """

    def __init__(self, history_store: BgpHistoryStore) -> None:
        self.history_store = history_store

    def handle(
        self,
        request: BgpHistoryQueryRequest,
    ) -> BgpHistoryQueryResponse:
        query_type = request.query_type

        if query_type == "routes_at_time":
            if request.timestamp_ms is None:
                raise ValueError("timestamp_ms is required for routes_at_time")

            rows = self.history_store.routes_at_or_before(
                timestamp_ms=request.timestamp_ms,
                peer=request.peer,
                direction=request.direction,
                afi_safi=request.afi_safi,
            )
            rows = self._filter_rows(
                rows=rows,
                device=request.device,
                network_instance=request.network_instance,
            )
            return BgpHistoryQueryResponse(
                request=asdict(request),
                results=[row.to_dict() for row in rows],
            )

        if query_type == "route_events_between":
            if request.start_ts is None or request.end_ts is None:
                raise ValueError(
                    "start_ts and end_ts are required for route_events_between"
                )

            rows = self.history_store.route_events_between(
                start_ts=request.start_ts,
                end_ts=request.end_ts,
                peer=request.peer,
                direction=request.direction,
                afi_safi=request.afi_safi,
            )
            rows = self._filter_rows(
                rows=rows,
                device=request.device,
                network_instance=request.network_instance,
            )
            return BgpHistoryQueryResponse(
                request=asdict(request),
                results=[row.to_dict() for row in rows],
            )

        if query_type == "added_routes_between":
            if request.start_ts is None or request.end_ts is None:
                raise ValueError(
                    "start_ts and end_ts are required for added_routes_between"
                )

            rows = self.history_store.route_events_between(
                start_ts=request.start_ts,
                end_ts=request.end_ts,
                peer=request.peer,
                direction=request.direction,
                afi_safi=request.afi_safi,
                event_type="route_added",
            )
            rows = self._filter_rows(
                rows=rows,
                device=request.device,
                network_instance=request.network_instance,
            )
            return BgpHistoryQueryResponse(
                request=asdict(request),
                results=[row.to_dict() for row in rows],
            )

        if query_type == "removed_routes_between":
            if request.start_ts is None or request.end_ts is None:
                raise ValueError(
                    "start_ts and end_ts are required for removed_routes_between"
                )

            rows = self.history_store.route_events_between(
                start_ts=request.start_ts,
                end_ts=request.end_ts,
                peer=request.peer,
                direction=request.direction,
                afi_safi=request.afi_safi,
                event_type="route_removed",
            )
            rows = self._filter_rows(
                rows=rows,
                device=request.device,
                network_instance=request.network_instance,
            )
            return BgpHistoryQueryResponse(
                request=asdict(request),
                results=[row.to_dict() for row in rows],
            )

        if query_type == "changed_routes_between":
            if request.start_ts is None or request.end_ts is None:
                raise ValueError(
                    "start_ts and end_ts are required for changed_routes_between"
                )

            rows = self.history_store.route_events_between(
                start_ts=request.start_ts,
                end_ts=request.end_ts,
                peer=request.peer,
                direction=request.direction,
                afi_safi=request.afi_safi,
                event_type="route_changed",
            )
            rows = self._filter_rows(
                rows=rows,
                device=request.device,
                network_instance=request.network_instance,
            )
            return BgpHistoryQueryResponse(
                request=asdict(request),
                results=[row.to_dict() for row in rows],
            )

        if query_type == "peer_summaries_at_time":
            if request.timestamp_ms is None:
                raise ValueError("timestamp_ms is required for peer_summaries_at_time")

            rows = self.history_store.peer_summaries_at_or_before(
                timestamp_ms=request.timestamp_ms,
                peer=request.peer,
                afi_safi=request.afi_safi,
            )
            rows = self._filter_rows(
                rows=rows,
                device=request.device,
                network_instance=request.network_instance,
            )
            return BgpHistoryQueryResponse(
                request=asdict(request),
                results=[row.to_dict() for row in rows],
            )

        if query_type == "anomalies_between":
            if request.start_ts is None or request.end_ts is None:
                raise ValueError(
                    "start_ts and end_ts are required for anomalies_between"
                )

            rows = self.history_store.anomalies_between(
                start_ts=request.start_ts,
                end_ts=request.end_ts,
                peer=request.peer,
            )
            rows = self._filter_rows(
                rows=rows,
                device=request.device,
                network_instance=request.network_instance,
            )
            return BgpHistoryQueryResponse(
                request=asdict(request),
                results=[row.to_dict() for row in rows],
            )

        raise ValueError(f"Unsupported query_type: {query_type}")

    def _filter_rows(
        self,
        rows: list[Any],
        device: str | None,
        network_instance: str | None,
    ) -> list[Any]:
        filtered = rows

        if device is not None:
            filtered = [row for row in filtered if getattr(row, "device", None) == device]

        if network_instance is not None:
            filtered = [
                row
                for row in filtered
                if getattr(row, "network_instance", None) == network_instance
            ]

        return filtered
