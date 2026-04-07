from internal.bgp.history_query_service import (
    BgpHistoryQueryRequest,
    BgpHistoryQueryService,
)


def handle_bgp_route_history_query(payload: dict, history_store) -> dict:
    service = BgpHistoryQueryService(history_store=history_store)

    request = BgpHistoryQueryRequest(
        device=payload.get("device"),
        peer=payload.get("peer"),
        network_instance=payload.get("network_instance"),
        direction=payload.get("direction"),
        afi_safi=payload.get("afi_safi"),
        timestamp_ms=payload.get("timestamp_ms"),
        start_ts=payload.get("start_ts"),
        end_ts=payload.get("end_ts"),
        query_type=payload["query_type"],
    )

    response = service.handle(request)

    return {
        "status": "success",
        "query_type": payload["query_type"],
        "result_count": len(response.results),
        "results": response.results,
    }
