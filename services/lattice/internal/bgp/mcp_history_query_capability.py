from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from internal.bgp.history_query_service import (
    BgpHistoryQueryRequest,
    BgpHistoryQueryService,
)
from internal.bgp.history_store import BgpHistoryStore


@dataclass(frozen=True)
class BgpHistoryCapabilityInput:
    query_type: str
    device: str | None = None
    peer: str | None = None
    network_instance: str | None = None
    direction: str | None = None
    afi_safi: str | None = None
    timestamp_ms: int | None = None
    start_ts: int | None = None
    end_ts: int | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> BgpHistoryCapabilityInput:
        if "query_type" not in payload:
            raise ValueError("Missing required field: query_type")

        return cls(
            query_type=payload["query_type"],
            device=payload.get("device"),
            peer=payload.get("peer"),
            network_instance=payload.get("network_instance"),
            direction=payload.get("direction"),
            afi_safi=payload.get("afi_safi"),
            timestamp_ms=payload.get("timestamp_ms"),
            start_ts=payload.get("start_ts"),
            end_ts=payload.get("end_ts"),
        )


def handle_bgp_history_query_capability(
    *,
    payload: dict[str, Any],
    history_store: BgpHistoryStore,
) -> dict[str, Any]:
    capability_input = BgpHistoryCapabilityInput.from_payload(payload)

    service = BgpHistoryQueryService(history_store=history_store)
    response = service.handle(
        BgpHistoryQueryRequest(
            device=capability_input.device,
            peer=capability_input.peer,
            network_instance=capability_input.network_instance,
            direction=capability_input.direction,
            afi_safi=capability_input.afi_safi,
            timestamp_ms=capability_input.timestamp_ms,
            start_ts=capability_input.start_ts,
            end_ts=capability_input.end_ts,
            query_type=capability_input.query_type,
        )
    )

    return {
        "status": "success",
        "capability": "bgp_history_query",
        "input": asdict(capability_input),
        "result_count": len(response.results),
        "result": response.to_dict(),
    }
