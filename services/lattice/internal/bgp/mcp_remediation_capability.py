from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Any

from internal.bgp.history_store import BgpHistoryStore
from internal.bgp.remediation_service import (
    BgpRemediationService,
    BgpRemediationServiceRequest,
)
from internal.bgp.route_state_tracker import BgpRouteStateTracker, build_demo_routes

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class BgpRemediationCapabilityInput:
    device: str
    peer: str | None = None
    network_instance: str = "default"
    afi_safi: str = "ipv4_unicast"
    from_timestamp_ms: int | None = None
    to_timestamp_ms: int | None = None
    plan_only: bool = True
    execute: bool = False

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> BgpRemediationCapabilityInput:
        if "device" not in payload:
            raise ValueError("Missing required field: device")

        return cls(
            device=payload["device"],
            peer=payload.get("peer"),
            network_instance=payload.get("network_instance", "default"),
            afi_safi=payload.get("afi_safi", "ipv4_unicast"),
            from_timestamp_ms=payload.get("from_timestamp_ms"),
            to_timestamp_ms=payload.get("to_timestamp_ms"),
            plan_only=payload.get("plan_only", True),
            execute=payload.get("execute", False),
        )


def handle_bgp_remediation_capability(
    *,
    payload: dict[str, Any],
    tracker: BgpRouteStateTracker,
    history_store: BgpHistoryStore,
) -> dict[str, Any]:
    """
    Thin MCP friendly wrapper around the BGP remediation service.

    MCP should own:
    auth
    signing
    replay protection
    idempotency
    audit
    approval workflow

    This handler only:
    validates payload
    builds service request
    calls service
    returns structured response
    """
    capability_input = BgpRemediationCapabilityInput.from_payload(payload)

    if capability_input.execute and capability_input.plan_only:
        raise ValueError("execute=true requires plan_only=false")

    service = BgpRemediationService(
        tracker=tracker,
        history_store=history_store,
    )

    response = service.handle(
        BgpRemediationServiceRequest(
            device=capability_input.device,
            peer=capability_input.peer,
            network_instance=capability_input.network_instance,
            afi_safi=capability_input.afi_safi,
            from_timestamp_ms=capability_input.from_timestamp_ms,
            to_timestamp_ms=capability_input.to_timestamp_ms,
            plan_only=capability_input.plan_only,
            execute=capability_input.execute,
        )
    )

    return {
        "status": "success",
        "capability": "bgp_remediation_plan"
        if capability_input.plan_only
        else "bgp_remediation_execute",
        "input": asdict(capability_input),
        "result": response.to_dict(),
    }


def _build_demo_state() -> tuple[BgpRouteStateTracker, BgpHistoryStore]:
    tracker = BgpRouteStateTracker()
    snapshot_1, snapshot_2 = build_demo_routes()

    tracker.ingest_snapshot(snapshot_1[0].timestamp_ms, snapshot_1)
    tracker.ingest_snapshot(snapshot_2[0].timestamp_ms, snapshot_2)

    from_ts = snapshot_1[0].timestamp_ms
    to_ts = snapshot_2[0].timestamp_ms

    summaries = tracker.peer_summaries_at(to_ts)
    events = tracker.route_events_for_diff(from_ts, to_ts)

    from internal.bgp.anomaly_detector import BgpAnomalyDetector

    anomalies = BgpAnomalyDetector(
        received_major_drop_pct=20.0,
        received_critical_drop_pct=50.0,
        advertised_major_drop_pct=20.0,
        advertised_critical_drop_pct=50.0,
        churn_event_threshold=3,
    ).detect_from_tracker(
        tracker=tracker,
        from_timestamp_ms=from_ts,
        to_timestamp_ms=to_ts,
    )

    history_store = BgpHistoryStore()
    history_store.store_route_snapshot_rows(snapshot_1)
    history_store.store_route_snapshot_rows(snapshot_2)
    history_store.store_peer_summary_rows(summaries)
    history_store.store_route_event_rows(events)
    history_store.store_anomaly_rows(anomalies)

    return tracker, history_store


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )

    tracker, history_store = _build_demo_state()

    plan_payload = {
        "device": "leaf-01",
        "peer": "10.0.0.1",
        "network_instance": "default",
        "afi_safi": "ipv4_unicast",
        "plan_only": True,
        "execute": False,
    }

    execute_payload = {
        "device": "leaf-01",
        "peer": "10.0.0.1",
        "network_instance": "default",
        "afi_safi": "ipv4_unicast",
        "plan_only": False,
        "execute": True,
    }

    plan_response = handle_bgp_remediation_capability(
        payload=plan_payload,
        tracker=tracker,
        history_store=history_store,
    )

    execute_response = handle_bgp_remediation_capability(
        payload=execute_payload,
        tracker=tracker,
        history_store=history_store,
    )

    print(
        json.dumps(
            {
                "plan_response": plan_response,
                "execute_response": execute_response,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
