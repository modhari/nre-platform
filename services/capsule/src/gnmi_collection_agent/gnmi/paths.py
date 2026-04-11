"""
paths.py — Central registry of OpenConfig gNMI paths used across vendor packs.

BGP paths follow OpenConfig network-instance/protocols/bgp hierarchy.
EVPN/VXLAN paths follow OpenConfig network-instance/protocols/bgp/neighbors
and network-instance/vlans/vlan hierarchy for VNI and VTEP state.

All paths use origin="openconfig" unless vendor-native is required.
"""
from __future__ import annotations

from gnmi_collection_agent.gnmi.client import GnmiPath


class OpenConfigPaths:

    # ── System ────────────────────────────────────────────────────────────────

    system_cpu_total = GnmiPath(
        origin="openconfig",
        path="/system/cpus/cpu/state/total/avg",
    )

    # ── BGP session state ─────────────────────────────────────────────────────

    bgp_neighbor_session_state = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/protocols/protocol[identifier=BGP][name=BGP]"
            "/bgp/neighbors/neighbor[neighbor-address=*]"
            "/state/session-state"
        ),
    )

    bgp_neighbor_peer_as = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/protocols/protocol[identifier=BGP][name=BGP]"
            "/bgp/neighbors/neighbor[neighbor-address=*]"
            "/state/peer-as"
        ),
    )

    bgp_neighbor_local_as = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/protocols/protocol[identifier=BGP][name=BGP]"
            "/bgp/neighbors/neighbor[neighbor-address=*]"
            "/state/local-as"
        ),
    )

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

    bgp_neighbor_last_error = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/protocols/protocol[identifier=BGP][name=BGP]"
            "/bgp/neighbors/neighbor[neighbor-address=*]"
            "/state/last-error"
        ),
    )

    bgp_neighbor_established_transitions = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/protocols/protocol[identifier=BGP][name=BGP]"
            "/bgp/neighbors/neighbor[neighbor-address=*]"
            "/state/established-transitions"
        ),
    )

    bgp_global_as = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/protocols/protocol[identifier=BGP][name=BGP]"
            "/bgp/global/state/as"
        ),
    )

    bgp_neighbor_route_reflector_client = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/protocols/protocol[identifier=BGP][name=BGP]"
            "/bgp/neighbors/neighbor[neighbor-address=*]"
            "/route-reflector/state/route-reflector-client"
        ),
    )

    bgp_neighbor_hold_time = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/protocols/protocol[identifier=BGP][name=BGP]"
            "/bgp/neighbors/neighbor[neighbor-address=*]"
            "/timers/state/negotiated-hold-time"
        ),
    )

    # ── BGP EVPN AFI-SAFI state ───────────────────────────────────────────────
    # These paths capture EVPN-specific peer state under the L2VPN-EVPN
    # address family. Used to detect missing EVPN peering and route counts.

    bgp_evpn_peer_session_state = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/protocols/protocol[identifier=BGP][name=BGP]"
            "/bgp/neighbors/neighbor[neighbor-address=*]"
            "/afi-safis/afi-safi[afi-safi-name=L2VPN_EVPN]"
            "/state/active"
        ),
    )

    bgp_evpn_prefixes_received = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/protocols/protocol[identifier=BGP][name=BGP]"
            "/bgp/neighbors/neighbor[neighbor-address=*]"
            "/afi-safis/afi-safi[afi-safi-name=L2VPN_EVPN]"
            "/state/prefixes/received"
        ),
    )

    bgp_evpn_prefixes_sent = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/protocols/protocol[identifier=BGP][name=BGP]"
            "/bgp/neighbors/neighbor[neighbor-address=*]"
            "/afi-safis/afi-safi[afi-safi-name=L2VPN_EVPN]"
            "/state/prefixes/sent"
        ),
    )

    # ── VXLAN VNI operational state ───────────────────────────────────────────
    # OpenConfig models VNI state under network-instance with VXLAN extension.
    # These paths capture per-VNI operational status, VTEP membership,
    # and flooding list state.

    vxlan_vni_state = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/vlans/vlan[vlan-id=*]"
            "/vxlan/state/vni"
        ),
    )

    vxlan_vni_admin_state = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/vlans/vlan[vlan-id=*]"
            "/vxlan/state/admin-state"
        ),
    )

    vxlan_vni_oper_state = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/vlans/vlan[vlan-id=*]"
            "/vxlan/state/oper-state"
        ),
    )

    # ── VTEP reachability ─────────────────────────────────────────────────────
    # Remote VTEP peer table — used to detect unreachable VTEPs and
    # missing type-3 IMET routes.

    vxlan_vtep_peer_state = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/vlans/vlan[vlan-id=*]"
            "/vxlan/endpoints/endpoint[peer-ip=*]"
            "/state/peer-ip"
        ),
    )

    vxlan_vtep_peer_vni = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/vlans/vlan[vlan-id=*]"
            "/vxlan/endpoints/endpoint[peer-ip=*]"
            "/state/vni"
        ),
    )

    # ── MAC table and mobility ────────────────────────────────────────────────
    # Per-VNI MAC table state — used to detect MAC mobility storms,
    # duplicate MACs, and misconfigured bonds.

    evpn_mac_vni = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/fdb/mac-table/entries/entry[mac-address=*][vlan=*]"
            "/state/vni"
        ),
    )

    evpn_mac_entry_type = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/fdb/mac-table/entries/entry[mac-address=*][vlan=*]"
            "/state/entry-type"
        ),
    )

    evpn_mac_mobility_seq = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/fdb/mac-table/entries/entry[mac-address=*][vlan=*]"
            "/state/mobility-seq-no"
        ),
    )

    evpn_mac_peer_vtep = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/fdb/mac-table/entries/entry[mac-address=*][vlan=*]"
            "/state/peer-vtep"
        ),
    )

    # ── EVPN route type counts ────────────────────────────────────────────────
    # Per-VNI EVPN route type counts — used to detect missing type-3 IMET
    # routes (VTEP unreachable) and type-5 route leaking.

    evpn_routes_type2 = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/protocols/protocol[identifier=BGP][name=BGP]"
            "/bgp/rib/afi-safis/afi-safi[afi-safi-name=L2VPN_EVPN]"
            "/l2vpn-evpn/loc-rib/routes/route-distinguisher[route-distinguisher=*]"
            "/routes/route[prefix=*]/state/route-type"
        ),
    )

    evpn_routes_type3_imet = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/protocols/protocol[identifier=BGP][name=BGP]"
            "/bgp/rib/afi-safis/afi-safi[afi-safi-name=L2VPN_EVPN]"
            "/l2vpn-evpn/loc-rib/routes/route-distinguisher[route-distinguisher=*]"
            "/inclusive-multicast-ethernet-tag/routes/route[originating-router=*]"
            "/state/attr-index"
        ),
    )

    # ── ESI multihoming ───────────────────────────────────────────────────────
    # Ethernet Segment Identifier state — used to detect ESI split-brain
    # and designated forwarder election failures.

    evpn_esi_state = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/evpn/ethernet-segments/ethernet-segment[esi=*]"
            "/state/esi"
        ),
    )

    evpn_esi_df_state = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/evpn/ethernet-segments/ethernet-segment[esi=*]"
            "/state/designated-forwarder"
        ),
    )

    evpn_esi_active_links = GnmiPath(
        origin="openconfig",
        path=(
            "/network-instances/network-instance[name=*]"
            "/evpn/ethernet-segments/ethernet-segment[esi=*]"
            "/state/active-links"
        ),
    )
