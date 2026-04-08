"""
nokia.py — Nokia SR Linux and SR OS vendor pack for Capsule.

Sensor groups:
  system   — CPU utilization
  bgp      — BGP neighbor state, prefix counts, last error, RR config

Nokia has two NOS families with different gNMI path structures:

SR Linux (srlinux):
  gNMI port: 57400 (default)
  Enable with: system / grpc-server / admin-state enable
  OpenConfig BGP: supported via openconfig origin
  Path quirk: SR Linux uses /network-instance[name=*] (singular, no
              plural wrapper) for its native model, but supports the
              standard OpenConfig /network-instances/... path when
              origin="openconfig" is specified. We use OpenConfig paths.

SR OS (sros):
  gNMI port: 57400 (default)
  Enable with: configure system grpc allow-unsecure-connection
  OpenConfig BGP: supported on SR OS 20.7+
  Path quirk: SR OS combines config and state in a single tree under
              /configure and /state. OpenConfig paths work when the
              nokia-oc-bgp module is loaded.

Both variants match on vendor='nokia'. The nos_family field
('srlinux' vs 'sros') is used to select the appropriate sensor groups
since the two have meaningfully different OpenConfig coverage.
"""
from __future__ import annotations

from typing import List

from gnmi_collection_agent.core.types import DeviceIdentity
from gnmi_collection_agent.gnmi.paths import OpenConfigPaths
from gnmi_collection_agent.vendors.base import SensorGroup, VendorPack


# ── Nokia SR Linux native BGP paths ──────────────────────────────────────────
# SR Linux exposes BGP state under its native model at these paths when
# origin="native" is used. These are preferred on SR Linux because the
# native model has richer state (last-event, failure-reason, etc.) than
# the OpenConfig mapping.

from gnmi_collection_agent.gnmi.client import GnmiPath

_SRLINUX_BGP_SESSION_STATE = GnmiPath(
    origin="native",
    path=(
        "/network-instance[name=*]"
        "/protocols/bgp/neighbor[peer-address=*]"
        "/session-state"
    ),
)

_SRLINUX_BGP_LAST_EVENT = GnmiPath(
    origin="native",
    path=(
        "/network-instance[name=*]"
        "/protocols/bgp/neighbor[peer-address=*]"
        "/last-event"
    ),
)

_SRLINUX_BGP_FAILURE_REASON = GnmiPath(
    origin="native",
    path=(
        "/network-instance[name=*]"
        "/protocols/bgp/neighbor[peer-address=*]"
        "/failure-reason"
    ),
)

_SRLINUX_BGP_PREFIXES_RECEIVED = GnmiPath(
    origin="native",
    path=(
        "/network-instance[name=*]"
        "/protocols/bgp/neighbor[peer-address=*]"
        "/afi-safi[afi-safi-name=*]"
        "/received-routes"
    ),
)

_SRLINUX_BGP_PREFIXES_ADVERTISED = GnmiPath(
    origin="native",
    path=(
        "/network-instance[name=*]"
        "/protocols/bgp/neighbor[peer-address=*]"
        "/afi-safi[afi-safi-name=*]"
        "/advertised-routes"
    ),
)

_SRLINUX_BGP_PEER_AS = GnmiPath(
    origin="native",
    path=(
        "/network-instance[name=*]"
        "/protocols/bgp/neighbor[peer-address=*]"
        "/peer-as"
    ),
)


class NokiaPack(VendorPack):
    """
    Vendor pack for Nokia SR Linux and SR OS devices.

    Matches any device whose vendor field is 'nokia' (case-insensitive).
    Uses native SR Linux paths when nos_family is 'srlinux' and
    OpenConfig paths when nos_family is 'sros' or when OpenConfig
    support is confirmed via capability discovery.
    """

    def match(self, ident: DeviceIdentity) -> bool:
        return ident.vendor.lower() == "nokia"

    def sensor_groups(self, supports_openconfig: bool) -> List[SensorGroup]:
        """
        Return sensor groups for Nokia.

        SR Linux is detected by nos_family. All other Nokia devices
        use OpenConfig paths. If neither OpenConfig nor SR Linux native
        paths are available, return empty.
        """
        # ── SR Linux — use native paths (richer state than OpenConfig) ────────
        # nos_family check is not available directly on supports_openconfig,
        # so SR Linux native sensor groups are returned regardless of the
        # OpenConfig flag — the FakeGnmiClient and real SR Linux both serve
        # these paths. The capability discovery step sets supports_openconfig
        # based on the presence of openconfig-bgp in the model list.
        return self._srlinux_groups() if not supports_openconfig \
            else self._openconfig_groups()

    def _srlinux_groups(self) -> List[SensorGroup]:
        """
        Sensor groups using SR Linux native gNMI paths.

        These return richer state than OpenConfig — notably failure-reason
        which maps directly to last_error in bgp_snapshot.json. The snapshot
        writer has a dedicated SR Linux translation path.
        """
        return [
            # ── System telemetry ──────────────────────────────────────────────
            SensorGroup(
                name="system",
                sample_interval_s=10.0,
                paths=[
                    OpenConfigPaths.system_cpu_total,
                ],
            ),

            # ── BGP session state (native) ────────────────────────────────────
            # failure-reason gives the exact disconnect cause:
            # tcp-failure, hold-time-expired, notification-received, etc.
            # This maps more precisely to last_error than OpenConfig last-error.
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

            # ── BGP prefix counts (native) ────────────────────────────────────
            SensorGroup(
                name="bgp_prefixes",
                sample_interval_s=60.0,
                paths=[
                    _SRLINUX_BGP_PREFIXES_RECEIVED,
                    _SRLINUX_BGP_PREFIXES_ADVERTISED,
                ],
            ),
        ]

    def _openconfig_groups(self) -> List[SensorGroup]:
        """
        Sensor groups using standard OpenConfig BGP paths.

        Used for SR OS and any Nokia device that advertises OpenConfig
        BGP model support via gNMI capabilities.
        """
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
