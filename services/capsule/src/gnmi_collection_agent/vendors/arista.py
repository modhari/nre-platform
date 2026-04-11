"""
arista.py — Arista EOS vendor pack for Capsule.

Sensor groups:
  system        — CPU utilization
  bgp_session   — BGP neighbor state, last error, peer AS
  bgp_prefixes  — BGP prefix counts per AFI-SAFI
  bgp_topology  — Route reflector topology, hold timers
  evpn          — VNI state, VTEP reachability, MAC mobility, ESI
"""
from __future__ import annotations

from typing import List

from gnmi_collection_agent.core.types import DeviceIdentity
from gnmi_collection_agent.gnmi.paths import OpenConfigPaths
from gnmi_collection_agent.vendors.base import SensorGroup, VendorPack


class AristaPack(VendorPack):

    def match(self, ident: DeviceIdentity) -> bool:
        return ident.vendor.lower() == "arista"

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
            # ── EVPN sensor group ─────────────────────────────────────────────
            # Polled every 60s — VNI and VTEP state changes are the primary
            # signal for EVPN incident detection.
            #
            # Covers all five EVPN fault surfaces:
            #   vtep_unreachable    — vxlan_vtep_peer_state + evpn_routes_type3_imet
            #   mac_mobility_storm  — evpn_mac_mobility_seq + evpn_mac_peer_vtep
            #   vni_state_down      — vxlan_vni_oper_state
            #   type5_leaking       — bgp_evpn_prefixes_received (type-5 count spike)
            #   esi_split_brain     — evpn_esi_state + evpn_esi_active_links
            SensorGroup(
                name="evpn",
                sample_interval_s=60.0,
                paths=[
                    # EVPN BGP AFI-SAFI state
                    OpenConfigPaths.bgp_evpn_peer_session_state,
                    OpenConfigPaths.bgp_evpn_prefixes_received,
                    OpenConfigPaths.bgp_evpn_prefixes_sent,
                    # VNI operational state
                    OpenConfigPaths.vxlan_vni_state,
                    OpenConfigPaths.vxlan_vni_admin_state,
                    OpenConfigPaths.vxlan_vni_oper_state,
                    # VTEP peer reachability
                    OpenConfigPaths.vxlan_vtep_peer_state,
                    OpenConfigPaths.vxlan_vtep_peer_vni,
                    # MAC table and mobility
                    OpenConfigPaths.evpn_mac_vni,
                    OpenConfigPaths.evpn_mac_entry_type,
                    OpenConfigPaths.evpn_mac_mobility_seq,
                    OpenConfigPaths.evpn_mac_peer_vtep,
                    # EVPN route type counts
                    OpenConfigPaths.evpn_routes_type3_imet,
                    # ESI multihoming
                    OpenConfigPaths.evpn_esi_state,
                    OpenConfigPaths.evpn_esi_df_state,
                    OpenConfigPaths.evpn_esi_active_links,
                ],
            ),
        ]
