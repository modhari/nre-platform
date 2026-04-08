"""
juniper.py — Juniper Junos vendor pack for Capsule.

Sensor groups:
  system   — CPU utilization
  bgp      — BGP neighbor state, prefix counts, last error, RR config

Juniper Junos supports OpenConfig BGP under the standard
network-instances hierarchy with origin="openconfig".

gNMI port on Junos: 32767 (default)
Enable with:
  set system services extension-service request-response grpc clear-text port 32767
  set system services extension-service request-response grpc skip-authentication

Notes:
  Junos requires the path to omit the top-level /configuration container.
  All paths here start at /network-instances/... which is correct for gNMI.
  For vendor-native Junos paths the origin would be "junos-openconfig" or
  "native" — those are added here only when OpenConfig coverage is absent.
"""
from __future__ import annotations

from typing import List

from gnmi_collection_agent.core.types import DeviceIdentity
from gnmi_collection_agent.gnmi.paths import OpenConfigPaths
from gnmi_collection_agent.vendors.base import SensorGroup, VendorPack


class JuniperPack(VendorPack):
    """
    Vendor pack for Juniper Junos devices.

    Matches any device whose vendor field is 'juniper' (case-insensitive).
    """

    def match(self, ident: DeviceIdentity) -> bool:
        return ident.vendor.lower() == "juniper"

    def sensor_groups(self, supports_openconfig: bool) -> List[SensorGroup]:
        """
        Return sensor groups for Juniper Junos.

        Junos has supported OpenConfig BGP since 17.3. Modern Junos releases
        (18.1+) have full OpenConfig coverage for BGP neighbor state and
        prefix counts. Fall back to empty if OpenConfig is not available
        rather than guessing at native paths.
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
            # On Junos, session-state values are uppercase:
            # IDLE, CONNECT, ACTIVE, OPENSENT, OPENCONFIRM, ESTABLISHED
            # The snapshot writer normalizes these to lowercase before
            # writing bgp_snapshot.json.
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
            # On Junos, received counts reflect routes after import policy.
            # Use 'show route receive-protocol bgp <peer>' to see pre-policy
            # counts — that requires soft-reconfiguration which is not
            # available via OpenConfig telemetry. The OpenConfig path returns
            # post-policy counts, which is what nre-agent uses.
            SensorGroup(
                name="bgp_prefixes",
                sample_interval_s=60.0,
                paths=[
                    OpenConfigPaths.bgp_neighbor_prefixes_received,
                    OpenConfigPaths.bgp_neighbor_prefixes_advertised,
                ],
            ),

            # ── BGP route reflector topology ──────────────────────────────────
            SensorGroup(
                name="bgp_topology",
                sample_interval_s=300.0,
                paths=[
                    OpenConfigPaths.bgp_neighbor_route_reflector_client,
                    OpenConfigPaths.bgp_neighbor_hold_time,
                ],
            ),
        ]
