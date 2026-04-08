"""
paths.py — Central registry of OpenConfig gNMI paths used across vendor packs.

Why this exists:
  Keeping paths in one module prevents duplication across vendor packs and
  makes it easy to evolve paths over time without touching vendor files.

BGP paths follow OpenConfig network-instance/protocols/bgp hierarchy:
  /network-instances/network-instance[name=<vrf>]/protocols/protocol[identifier=BGP][name=BGP]/bgp/...

All paths use origin="openconfig" — vendor-native paths are added in
vendor packs using GnmiPath(origin="<vendor>", path="...").
"""
from __future__ import annotations

from gnmi_collection_agent.gnmi.client import GnmiPath


class OpenConfigPaths:
    """
    Central place for OpenConfig gNMI paths used across vendor packs.

    Paths are grouped by functional area. Add new paths here first,
    then reference them from the relevant vendor pack sensor groups.
    """

    # ── System ────────────────────────────────────────────────────────────────

    system_cpu_total = GnmiPath(
        origin="openconfig",
        path="/system/cpus/cpu/state/total/avg",
    )

    # ── BGP session state ─────────────────────────────────────────────────────
    # These paths return the FSM state of each BGP neighbor session.
    # Values: IDLE, CONNECT, ACTIVE, OPENSENT, OPENCONFIRM, ESTABLISHED

    bgp_neighbor_session_state = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/protocols/protocol[identifier=BGP][name=BGP]"
            "/bgp/neighbors/neighbor[neighbor-address=*]"
            "/state/session-state"
        ),
    )

    # ── BGP neighbor configuration ────────────────────────────────────────────
    # Peer AS number — used to verify remote-as matches expectations.

    bgp_neighbor_peer_as = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/protocols/protocol[identifier=BGP][name=BGP]"
            "/bgp/neighbors/neighbor[neighbor-address=*]"
            "/state/peer-as"
        ),
    )

    # Local AS number configured on this device.
    bgp_neighbor_local_as = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/protocols/protocol[identifier=BGP][name=BGP]"
            "/bgp/neighbors/neighbor[neighbor-address=*]"
            "/state/local-as"
        ),
    )

    # ── BGP prefix counts ─────────────────────────────────────────────────────
    # Received prefix count per neighbor per AFI-SAFI.
    # A zero count on an ESTABLISHED session is the key signal for
    # the peer_not_advertising anomaly type.

    bgp_neighbor_prefixes_received = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/protocols/protocol[identifier=BGP][name=BGP]"
            "/bgp/neighbors/neighbor[neighbor-address=*]"
            "/afi-safis/afi-safi[afi-safi-name=*]"
            "/state/prefixes/received"
        ),
    )

    # Advertised prefix count per neighbor per AFI-SAFI.
    bgp_neighbor_prefixes_advertised = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/protocols/protocol[identifier=BGP][name=BGP]"
            "/bgp/neighbors/neighbor[neighbor-address=*]"
            "/afi-safis/afi-safi[afi-safi-name=*]"
            "/state/prefixes/sent"
        ),
    )

    # ── BGP error and notification state ──────────────────────────────────────
    # Last error received from the peer — maps to last_error in bgp_snapshot.
    # Values include: HOLD_TIMER_EXPIRED, NOTIFICATION_RECEIVED,
    # TCP_CONNECT_FAILED, OPEN_MSG_ERR, etc.

    bgp_neighbor_last_error = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/protocols/protocol[identifier=BGP][name=BGP]"
            "/bgp/neighbors/neighbor[neighbor-address=*]"
            "/state/last-error"
        ),
    )

    # Number of times the session has been established — used to detect flaps.
    bgp_neighbor_established_transitions = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/protocols/protocol[identifier=BGP][name=BGP]"
            "/bgp/neighbors/neighbor[neighbor-address=*]"
            "/state/established-transitions"
        ),
    )

    # ── BGP global AS ─────────────────────────────────────────────────────────
    # The device's own AS number.

    bgp_global_as = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/protocols/protocol[identifier=BGP][name=BGP]"
            "/bgp/global/state/as"
        ),
    )

    # ── BGP route reflector ───────────────────────────────────────────────────
    # Whether this neighbor is a route reflector client.
    # Used to identify RR topology and correlate RR failures.

    bgp_neighbor_route_reflector_client = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/protocols/protocol[identifier=BGP][name=BGP]"
            "/bgp/neighbors/neighbor[neighbor-address=*]"
            "/route-reflector/state/route-reflector-client"
        ),
    )

    # ── BGP timers ────────────────────────────────────────────────────────────
    # Negotiated hold time — a very low value can cause hold timer expiry.

    bgp_neighbor_hold_time = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/protocols/protocol[identifier=BGP][name=BGP]"
            "/bgp/neighbors/neighbor[neighbor-address=*]"
            "/timers/state/negotiated-hold-time"
        ),
    )
