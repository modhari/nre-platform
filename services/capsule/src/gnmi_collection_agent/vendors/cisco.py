"""
cisco.py — Cisco NX-OS and IOS-XR vendor pack for Capsule.

Sensor groups:
  system   — CPU utilization
  bgp      — BGP neighbor state, prefix counts, last error, RR config

Cisco NX-OS and IOS-XR both support OpenConfig BGP but with differences:

NX-OS:
  gNMI port: 50051 (default)
  Enable with: feature grpc / grpc port 50051
  OpenConfig BGP support: NX-OS 9.3+ with openconfig feature enabled
  Quirk: address-family must be explicitly activated per neighbor —
         a session can be ESTABLISHED with zero prefixes if the AFI-SAFI
         is not activated. The snapshot writer treats zero prefixes on
         an established session as peer_not_advertising.

IOS-XR:
  gNMI port: 57400 (default)
  Enable with: grpc / port 57400 / no-tls
  OpenConfig BGP support: IOS-XR 6.3+ with openconfig BGP models

Both variants match on vendor='cisco'. The nos_family field on
DeviceIdentity ('nx_os' vs 'ios_xr') can be used to add vendor-native
paths in future when OpenConfig coverage is incomplete.
"""
from __future__ import annotations

from typing import List

from gnmi_collection_agent.core.types import DeviceIdentity
from gnmi_collection_agent.gnmi.paths import OpenConfigPaths
from gnmi_collection_agent.vendors.base import SensorGroup, VendorPack


class CiscoPack(VendorPack):
    """
    Vendor pack for Cisco NX-OS and IOS-XR devices.

    Matches any device whose vendor field is 'cisco' (case-insensitive).
    """

    def match(self, ident: DeviceIdentity) -> bool:
        return ident.vendor.lower() == "cisco"

    def sensor_groups(self, supports_openconfig: bool) -> List[SensorGroup]:
        """
        Return sensor groups for Cisco NX-OS / IOS-XR.

        Both NX-OS and IOS-XR use the same OpenConfig BGP paths. The
        main difference between them is the gNMI port and the encoding
        (json_ietf is preferred on both). Those are gnmic configuration
        concerns, not sensor group concerns.

        Falls back to empty if OpenConfig is not available — NX-OS
        versions before 9.3 do not support OpenConfig BGP via gNMI.
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
            # On NX-OS, 'show bgp process' must show running state before
            # gNMI BGP paths are available. If the BGP process is not
            # running, the paths return empty rather than an error.
            # The snapshot writer treats missing session state as IDLE.
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
            # On NX-OS, prefix counts are per AFI-SAFI per neighbor.
            # If the neighbor is not activated under address-family ipv4
            # unicast, the count will be zero even on an ESTABLISHED session.
            # The snapshot writer maps this to the peer_not_advertising
            # anomaly type with root_cause_hint set to
            # 'address_family_not_activated_or_upstream_issue'.
            SensorGroup(
                name="bgp_prefixes",
                sample_interval_s=60.0,
                paths=[
                    OpenConfigPaths.bgp_neighbor_prefixes_received,
                    OpenConfigPaths.bgp_neighbor_prefixes_advertised,
                ],
            ),

            # ── BGP route reflector topology ──────────────────────────────────
            # NX-OS uses 'show bgp neighbors <ip> | inc cluster' to inspect
            # RR config. The OpenConfig path maps to the same data.
            SensorGroup(
                name="bgp_topology",
                sample_interval_s=300.0,
                paths=[
                    OpenConfigPaths.bgp_neighbor_route_reflector_client,
                    OpenConfigPaths.bgp_neighbor_hold_time,
                ],
            ),
        ]
