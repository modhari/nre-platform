"""
juniper.py — Juniper Junos vendor pack for Capsule.

Sensor groups:
  system        — CPU utilization
  bgp_session   — BGP neighbor state
  bgp_prefixes  — BGP prefix counts
  bgp_topology  — Route reflector topology
  evpn          — VNI state, VTEP reachability, MAC mobility, ESI

Notes:
  Junos supports OpenConfig EVPN paths via origin="openconfig".
  For MAC table state, Junos native paths are more reliable but
  OpenConfig coverage is sufficient for anomaly detection.
"""
from __future__ import annotations

from typing import List

from gnmi_collection_agent.core.types import DeviceIdentity
from gnmi_collection_agent.gnmi.paths import OpenConfigPaths
from gnmi_collection_agent.vendors.base import SensorGroup, VendorPack


class JuniperPack(VendorPack):

    def match(self, ident: DeviceIdentity) -> bool:
        return ident.vendor.lower() == "juniper"

    def sensor_groups(self, supports_openconfig: bool) -> List[SensorGroup]:
        if not supports_openconfig:
            return []

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
