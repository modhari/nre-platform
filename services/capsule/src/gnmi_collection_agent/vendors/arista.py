"""
arista.py — Arista EOS vendor pack for Capsule.

Sensor groups:
  system   — CPU utilization (original)
  bgp      — BGP neighbor state, prefix counts, last error, RR config

Arista EOS supports OpenConfig BGP fully under the standard
network-instances hierarchy. All BGP paths use origin="openconfig".

gNMI port on Arista EOS: 6030 (default)
Enable with: management api gnmi / transport grpc default / no shutdown
"""
from __future__ import annotations

from typing import List

from gnmi_collection_agent.core.types import DeviceIdentity
from gnmi_collection_agent.gnmi.paths import OpenConfigPaths
from gnmi_collection_agent.vendors.base import SensorGroup, VendorPack


class AristaPack(VendorPack):
    """
    Vendor pack for Arista EOS devices.

    Matches any device whose vendor field is 'arista' (case-insensitive).
    Returns sensor groups based on whether the device supports OpenConfig.
    """

    def match(self, ident: DeviceIdentity) -> bool:
        return ident.vendor.lower() == "arista"

    def sensor_groups(self, supports_openconfig: bool) -> List[SensorGroup]:
        """
        Return sensor groups for Arista EOS.

        When OpenConfig is supported (which it is on all modern EOS versions),
        return both system and BGP groups. Fall back to empty if OpenConfig
        is not available — we never guess at vendor-native paths here.
        """
        if not supports_openconfig:
            return []

        return [
            # ── System telemetry ──────────────────────────────────────────────
            SensorGroup(
                name="system",
                sample_interval_s=10.0,
                paths=[
                    OpenConfigPaths.system_cpu_total,
                ],
            ),

            # ── BGP session state ─────────────────────────────────────────────
            # Polled every 30s. Session state changes are the primary signal
            # for BGP incident detection in nre-agent.
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

            # ── BGP prefix counts ─────────────────────────────────────────────
            # Polled every 60s. A received count of zero on an ESTABLISHED
            # session triggers the peer_not_advertising anomaly type.
            SensorGroup(
                name="bgp_prefixes",
                sample_interval_s=60.0,
                paths=[
                    OpenConfigPaths.bgp_neighbor_prefixes_received,
                    OpenConfigPaths.bgp_neighbor_prefixes_advertised,
                ],
            ),

            # ── BGP route reflector topology ──────────────────────────────────
            # Polled every 300s — topology changes infrequently.
            # Used by the cross-device correlator to identify RR clients
            # and map correlated session failures to their common RR.
            SensorGroup(
                name="bgp_topology",
                sample_interval_s=300.0,
                paths=[
                    OpenConfigPaths.bgp_neighbor_route_reflector_client,
                    OpenConfigPaths.bgp_neighbor_hold_time,
                ],
            ),
        ]
