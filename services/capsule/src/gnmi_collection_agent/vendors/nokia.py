"""
nokia.py — Nokia SR Linux and SR OS vendor pack for Capsule.

Sensor groups:
  system        — CPU utilization
  bgp_session   — BGP neighbor state (native on SR Linux, OC on SR OS)
  bgp_prefixes  — BGP prefix counts
  bgp_topology  — Route reflector topology (SR OS only)
  evpn          — VNI state, VTEP reachability, MAC mobility, ESI

Notes:
  SR Linux uses native paths for EVPN MAC table — the native model
  exposes mac-duplication-detected and mobility-count directly, which
  maps more precisely to mac_mobility_storm than the OpenConfig path.
  SR OS uses OpenConfig EVPN paths when available.
"""
from __future__ import annotations

from typing import List

from gnmi_collection_agent.core.types import DeviceIdentity
from gnmi_collection_agent.gnmi.client import GnmiPath
from gnmi_collection_agent.gnmi.paths import OpenConfigPaths
from gnmi_collection_agent.vendors.base import SensorGroup, VendorPack


# ── SR Linux native BGP paths ─────────────────────────────────────────────────

_SRLINUX_BGP_SESSION_STATE = GnmiPath(
    origin="native",
    path="/network-instance[name=*]/protocols/bgp/neighbor[peer-address=*]/session-state",
)
_SRLINUX_BGP_LAST_EVENT = GnmiPath(
    origin="native",
    path="/network-instance[name=*]/protocols/bgp/neighbor[peer-address=*]/last-event",
)
_SRLINUX_BGP_FAILURE_REASON = GnmiPath(
    origin="native",
    path="/network-instance[name=*]/protocols/bgp/neighbor[peer-address=*]/failure-reason",
)
_SRLINUX_BGP_PREFIXES_RECEIVED = GnmiPath(
    origin="native",
    path="/network-instance[name=*]/protocols/bgp/neighbor[peer-address=*]/afi-safi[afi-safi-name=*]/received-routes",
)
_SRLINUX_BGP_PREFIXES_ADVERTISED = GnmiPath(
    origin="native",
    path="/network-instance[name=*]/protocols/bgp/neighbor[peer-address=*]/afi-safi[afi-safi-name=*]/advertised-routes",
)
_SRLINUX_BGP_PEER_AS = GnmiPath(
    origin="native",
    path="/network-instance[name=*]/protocols/bgp/neighbor[peer-address=*]/peer-as",
)

# ── SR Linux native EVPN paths ────────────────────────────────────────────────
# SR Linux exposes richer EVPN state than OpenConfig — especially for
# MAC duplication detection and mobility counters.

_SRLINUX_EVPN_VNI_OPER = GnmiPath(
    origin="native",
    path="/network-instance[name=*]/vxlan-interface[name=*]/bridge-table/statistics/active-entries",
)
_SRLINUX_EVPN_VTEP_PEER = GnmiPath(
    origin="native",
    path="/network-instance[name=*]/vxlan-interface[name=*]/bridge-table/unicast-destinations/destination[vtep=*][vni=*]/statistics/active-entries",
)
_SRLINUX_MAC_MOBILITY_COUNT = GnmiPath(
    origin="native",
    path="/network-instance[name=*]/bridge-table/mac-table/mac[address=*]/last-update",
)
_SRLINUX_MAC_DUP_DETECTED = GnmiPath(
    origin="native",
    path="/network-instance[name=*]/bridge-table/mac-duplication/mac[address=*]/detected-time",
)
_SRLINUX_ESI_STATE = GnmiPath(
    origin="native",
    path="/system/network-instance/protocols/evpn/ethernet-segments/bgp-instance[id=*]/ethernet-segment[name=*]/esi",
)
_SRLINUX_ESI_DF = GnmiPath(
    origin="native",
    path="/system/network-instance/protocols/evpn/ethernet-segments/bgp-instance[id=*]/ethernet-segment[name=*]/df-election/oper-designated-forwarder",
)


class NokiaPack(VendorPack):

    def match(self, ident: DeviceIdentity) -> bool:
        return ident.vendor.lower() == "nokia"

    def sensor_groups(self, supports_openconfig: bool) -> List[SensorGroup]:
        return self._srlinux_groups() if not supports_openconfig \
            else self._openconfig_groups()

    def _srlinux_groups(self) -> List[SensorGroup]:
        return [
            SensorGroup(
                name="system",
                sample_interval_s=10.0,
                paths=[OpenConfigPaths.system_cpu_total],
            ),
            SensorGroup(
                name="bgp_session",
                sample_interval_s=30.0,
                paths=[
                    _SRLINUX_BGP_SESSION_STATE,
                    _SRLINUX_BGP_LAST_EVENT,
                    _SRLINUX_BGP_FAILURE_REASON,
                    _SRLINUX_BGP_PEER_AS,
                ],
            ),
            SensorGroup(
                name="bgp_prefixes",
                sample_interval_s=60.0,
                paths=[
                    _SRLINUX_BGP_PREFIXES_RECEIVED,
                    _SRLINUX_BGP_PREFIXES_ADVERTISED,
                ],
            ),
            # ── SR Linux EVPN — native paths ──────────────────────────────────
            # SR Linux native model has better EVPN coverage than OpenConfig
            # for MAC duplication detection and VTEP bridge table state.
            SensorGroup(
                name="evpn",
                sample_interval_s=60.0,
                paths=[
                    _SRLINUX_EVPN_VNI_OPER,
                    _SRLINUX_EVPN_VTEP_PEER,
                    _SRLINUX_MAC_MOBILITY_COUNT,
                    _SRLINUX_MAC_DUP_DETECTED,
                    _SRLINUX_ESI_STATE,
                    _SRLINUX_ESI_DF,
                ],
            ),
        ]

    def _openconfig_groups(self) -> List[SensorGroup]:
        return [
            SensorGroup(
                name="system",
                sample_interval_s=10.0,
                paths=[OpenConfigPaths.system_cpu_total],
            ),
            SensorGroup(
                name="bgp_session",
                sample_interval_s=30.0,
                paths=[
                    OpenConfigPaths.bgp_neighbor_session_state,
                    OpenConfigPaths.bgp_neighbor_last_error,
                    OpenConfigPaths.bgp_neighbor_established_transitions,
                    OpenConfigPaths.bgp_neighbor_peer_as,
                    OpenConfigPaths.bgp_neighbor_local_as,
                    OpenConfigPaths.bgp_global_as,
                ],
            ),
            SensorGroup(
                name="bgp_prefixes",
                sample_interval_s=60.0,
                paths=[
                    OpenConfigPaths.bgp_neighbor_prefixes_received,
                    OpenConfigPaths.bgp_neighbor_prefixes_advertised,
                ],
            ),
            SensorGroup(
                name="bgp_topology",
                sample_interval_s=300.0,
                paths=[
                    OpenConfigPaths.bgp_neighbor_route_reflector_client,
                    OpenConfigPaths.bgp_neighbor_hold_time,
                ],
            ),
            SensorGroup(
                name="evpn",
                sample_interval_s=60.0,
                paths=[
                    OpenConfigPaths.bgp_evpn_peer_session_state,
                    OpenConfigPaths.bgp_evpn_prefixes_received,
                    OpenConfigPaths.bgp_evpn_prefixes_sent,
                    OpenConfigPaths.vxlan_vni_state,
                    OpenConfigPaths.vxlan_vni_admin_state,
                    OpenConfigPaths.vxlan_vni_oper_state,
                    OpenConfigPaths.vxlan_vtep_peer_state,
                    OpenConfigPaths.vxlan_vtep_peer_vni,
                    OpenConfigPaths.evpn_mac_vni,
                    OpenConfigPaths.evpn_mac_entry_type,
                    OpenConfigPaths.evpn_mac_mobility_seq,
                    OpenConfigPaths.evpn_mac_peer_vtep,
                    OpenConfigPaths.evpn_routes_type3_imet,
                    OpenConfigPaths.evpn_esi_state,
                    OpenConfigPaths.evpn_esi_df_state,
                    OpenConfigPaths.evpn_esi_active_links,
                ],
            ),
        ]
