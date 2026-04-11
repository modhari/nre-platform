"""
simulator.py — Synthetic gNMI BGP + EVPN telemetry generator.

Writes two files:
  /data/gnmic_bgp.json   — BGP session state (existing)
  /data/gnmic_evpn.json  — EVPN VNI/VTEP/MAC/ESI state (new)

BGP and EVPN faults are correlated — the same scenario clock drives
both outputs so the agent sees consistent fabric-wide fault signals.

Simulated devices:
  leaf-01   arista  EOS       — RR client, VTEP 10.0.1.1, VNIs 10100 10200
  leaf-02   juniper Junos     — RR client, VTEP 10.0.1.2, VNIs 10100 10200
  leaf-03   cisco   NX-OS     — RR client, VTEP 10.0.1.3, VNIs 10100 10200
  leaf-04   nokia   SR Linux  — RR client, VTEP 10.0.1.4, VNIs 10100 10200
  rr-01     arista  EOS       — Route reflector spine
  rr-02     juniper Junos     — Route reflector spine

EVPN fault scenarios (same clock as BGP):
  healthy          all VNIs up, all VTEPs reachable, no MAC mobility
  rr_failure       EVPN BGP sessions to rr-01 drop, type-3 routes missing
  prefix_drain     leaf-01 VNI 10100 VTEP table empties (type-3 withdrawn)
  flap             leaf-02 MAC 00:50:56:aa:bb:01 starts flapping (mobility storm)
  recovery         VTEPs recovering, MAC mobility settling

Environment variables:
  GNMIC_OUTPUT_FILE          BGP output   default: /data/gnmic_bgp.json
  GNMIC_EVPN_OUTPUT_FILE     EVPN output  default: /data/gnmic_evpn.json
  SCENARIO_DURATION_SECONDS  default: 120
  POLL_INTERVAL_SECONDS      default: 30
  FABRIC_NAME                default: prod-dc-west
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)


# ── Config ────────────────────────────────────────────────────────────────────

def _bgp_output_file() -> Path:
    return Path(os.getenv("GNMIC_OUTPUT_FILE", "/data/gnmic_bgp.json"))

def _evpn_output_file() -> Path:
    return Path(os.getenv("GNMIC_EVPN_OUTPUT_FILE", "/data/gnmic_evpn.json"))

def _scenario_duration() -> int:
    return int(os.getenv("SCENARIO_DURATION_SECONDS", "120"))

def _poll_interval() -> int:
    return int(os.getenv("POLL_INTERVAL_SECONDS", "30"))

def _fabric() -> str:
    return os.getenv("FABRIC_NAME", "prod-dc-west")


# ── Device topology ───────────────────────────────────────────────────────────

@dataclass
class SimDevice:
    name:       str
    vendor:     str
    nos_family: str
    gnmi_port:  int
    local_vtep: str
    peers:      list[dict[str, Any]] = field(default_factory=list)
    vnis:       list[dict[str, Any]] = field(default_factory=list)
    macs:       list[dict[str, Any]] = field(default_factory=list)
    esis:       list[dict[str, Any]] = field(default_factory=list)


DEVICES: list[SimDevice] = [
    SimDevice(
        name="leaf-01", vendor="arista", nos_family="eos",
        gnmi_port=6030, local_vtep="10.0.1.1",
        peers=[
            {"address": "10.0.0.10", "peer_as": "65000", "network_instance": "default",
             "afi_safi": "IPV4_UNICAST", "is_rr_client": True, "rr": "rr-01", "normal_prefixes": 128},
            {"address": "10.0.0.11", "peer_as": "65000", "network_instance": "default",
             "afi_safi": "IPV4_UNICAST", "is_rr_client": True, "rr": "rr-02", "normal_prefixes": 128},
        ],
        vnis=[
            {"vni": 10100, "vlan": 100, "remote_vteps": ["10.0.1.2", "10.0.1.3", "10.0.1.4"]},
            {"vni": 10200, "vlan": 200, "remote_vteps": ["10.0.1.2", "10.0.1.3", "10.0.1.4"]},
        ],
        macs=[
            {"mac": "00:50:56:aa:01:01", "vni": 10100, "is_local": True},
            {"mac": "00:50:56:aa:01:02", "vni": 10200, "is_local": True},
        ],
        esis=[
            {"esi": "0000:0000:0000:0001:0001", "expected_links": 2},
        ],
    ),
    SimDevice(
        name="leaf-02", vendor="juniper", nos_family="junos",
        gnmi_port=32767, local_vtep="10.0.1.2",
        peers=[
            {"address": "10.0.0.12", "peer_as": "65000", "network_instance": "default",
             "afi_safi": "IPV4_UNICAST", "is_rr_client": True, "rr": "rr-01", "normal_prefixes": 96},
            {"address": "10.0.0.13", "peer_as": "65000", "network_instance": "default",
             "afi_safi": "IPV4_UNICAST", "is_rr_client": True, "rr": "rr-02", "normal_prefixes": 96},
        ],
        vnis=[
            {"vni": 10100, "vlan": 100, "remote_vteps": ["10.0.1.1", "10.0.1.3", "10.0.1.4"]},
            {"vni": 10200, "vlan": 200, "remote_vteps": ["10.0.1.1", "10.0.1.3", "10.0.1.4"]},
        ],
        macs=[
            {"mac": "00:50:56:aa:02:01", "vni": 10100, "is_local": True},
            # This MAC is the flapping one in the flap scenario
            {"mac": "00:50:56:aa:bb:01", "vni": 10200, "is_local": True},
        ],
        esis=[
            {"esi": "0000:0000:0000:0001:0002", "expected_links": 2},
        ],
    ),
    SimDevice(
        name="leaf-03", vendor="cisco", nos_family="nx_os",
        gnmi_port=50051, local_vtep="10.0.1.3",
        peers=[
            {"address": "10.0.0.14", "peer_as": "65000", "network_instance": "default",
             "afi_safi": "IPV4_UNICAST", "is_rr_client": True, "rr": "rr-01", "normal_prefixes": 112},
            {"address": "10.0.0.15", "peer_as": "65000", "network_instance": "default",
             "afi_safi": "IPV4_UNICAST", "is_rr_client": True, "rr": "rr-02", "normal_prefixes": 112},
        ],
        vnis=[
            {"vni": 10100, "vlan": 100, "remote_vteps": ["10.0.1.1", "10.0.1.2", "10.0.1.4"]},
            {"vni": 10200, "vlan": 200, "remote_vteps": ["10.0.1.1", "10.0.1.2", "10.0.1.4"]},
        ],
        macs=[
            {"mac": "00:50:56:aa:03:01", "vni": 10100, "is_local": True},
            {"mac": "00:50:56:aa:03:02", "vni": 10200, "is_local": True},
        ],
        esis=[],
    ),
    SimDevice(
        name="leaf-04", vendor="nokia", nos_family="srlinux",
        gnmi_port=57400, local_vtep="10.0.1.4",
        peers=[
            {"address": "10.0.0.16", "peer_as": "65000", "network_instance": "default",
             "afi_safi": "IPV4_UNICAST", "is_rr_client": True, "rr": "rr-01", "normal_prefixes": 80},
            {"address": "10.0.0.17", "peer_as": "65000", "network_instance": "default",
             "afi_safi": "IPV4_UNICAST", "is_rr_client": True, "rr": "rr-02", "normal_prefixes": 80},
        ],
        vnis=[
            {"vni": 10100, "vlan": 100, "remote_vteps": ["10.0.1.1", "10.0.1.2", "10.0.1.3"]},
            {"vni": 10200, "vlan": 200, "remote_vteps": ["10.0.1.1", "10.0.1.2", "10.0.1.3"]},
        ],
        macs=[
            {"mac": "00:50:56:aa:04:01", "vni": 10100, "is_local": True},
            {"mac": "00:50:56:aa:04:02", "vni": 10200, "is_local": True},
        ],
        esis=[
            {"esi": "0000:0000:0000:0001:0004", "expected_links": 2},
        ],
    ),
]


# ── Scenario engine ───────────────────────────────────────────────────────────

SCENARIOS = ["healthy", "rr_failure", "prefix_drain", "flap", "recovery"]


class ScenarioClock:
    def __init__(self, duration_s: int) -> None:
        self._duration   = duration_s
        self._start_time = time.time()

    def current(self) -> str:
        elapsed = time.time() - self._start_time
        index   = int(elapsed / self._duration) % len(SCENARIOS)
        return SCENARIOS[index]

    def seconds_remaining(self) -> int:
        elapsed = time.time() - self._start_time
        return int(self._duration - (elapsed % self._duration))


# ── Time helpers ──────────────────────────────────────────────────────────────

def _now_ns() -> int:
    return int(time.time() * 1_000_000_000)

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── BGP event generation (unchanged from original) ────────────────────────────

def _openconfig_bgp_event(
    device: SimDevice,
    peer: dict[str, Any],
    session_state: str,
    last_error: str | None,
    prefixes_received: int,
    prefixes_advertised: int,
) -> dict[str, Any]:
    ni   = peer["network_instance"]
    addr = peer["address"]
    afi  = peer["afi_safi"]
    port = device.gnmi_port
    return {
        "source": f"{device.name}:{port}", "timestamp": _now_ns(), "time": _now_iso(),
        "tags": {
            "network-instance_name": ni, "neighbor_neighbor-address": addr,
            "afi-safi_afi-safi-name": afi, "subscription-name": "bgp_session",
            "source": f"{device.name}:{port}",
        },
        "values": {
            f"/network-instances/network-instance[name={ni}]/protocols/protocol[identifier=BGP][name=BGP]/bgp/neighbors/neighbor[neighbor-address={addr}]/state/session-state": session_state.upper(),
            f"/network-instances/network-instance[name={ni}]/protocols/protocol[identifier=BGP][name=BGP]/bgp/neighbors/neighbor[neighbor-address={addr}]/state/last-error": last_error.upper().replace("_", "-") if last_error else None,
            f"/network-instances/network-instance[name={ni}]/protocols/protocol[identifier=BGP][name=BGP]/bgp/neighbors/neighbor[neighbor-address={addr}]/afi-safis/afi-safi[afi-safi-name={afi}]/state/prefixes/received": prefixes_received,
            f"/network-instances/network-instance[name={ni}]/protocols/protocol[identifier=BGP][name=BGP]/bgp/neighbors/neighbor[neighbor-address={addr}]/afi-safis/afi-safi[afi-safi-name={afi}]/state/prefixes/sent": prefixes_advertised,
            f"/network-instances/network-instance[name={ni}]/protocols/protocol[identifier=BGP][name=BGP]/bgp/neighbors/neighbor[neighbor-address={addr}]/state/peer-as": peer["peer_as"],
            f"/network-instances/network-instance[name={ni}]/protocols/protocol[identifier=BGP][name=BGP]/bgp/neighbors/neighbor[neighbor-address={addr}]/route-reflector/state/route-reflector-client": peer.get("is_rr_client", False),
        },
    }


def _srlinux_bgp_event(
    device: SimDevice,
    peer: dict[str, Any],
    session_state: str,
    last_error: str | None,
    prefixes_received: int,
    prefixes_advertised: int,
) -> dict[str, Any]:
    ni   = peer["network_instance"]
    addr = peer["address"]
    afi  = peer["afi_safi"]
    port = device.gnmi_port
    failure_reason_map = {
        "tcp_connect_failed": "tcp-failure", "hold_timer_expired": "hold-time-expired",
        "notification_received": "notification-received", "auth_failure": "authentication-failure",
        "admin_shutdown": "local-close",
    }
    failure_reason = failure_reason_map.get(last_error or "", "unknown")
    return {
        "source": f"{device.name}:{port}", "timestamp": _now_ns(), "time": _now_iso(),
        "tags": {
            "network-instance_name": ni, "peer-address": addr,
            "afi_safi_name": afi, "subscription-name": "bgp_session",
            "source": f"{device.name}:{port}",
        },
        "values": {
            f"/network-instance[name={ni}]/protocols/bgp/neighbor[peer-address={addr}]/session-state": session_state.lower(),
            f"/network-instance[name={ni}]/protocols/bgp/neighbor[peer-address={addr}]/failure-reason": failure_reason if session_state != "established" else None,
            f"/network-instance[name={ni}]/protocols/bgp/neighbor[peer-address={addr}]/last-event": "session-down" if session_state != "established" else "established",
            f"/network-instance[name={ni}]/protocols/bgp/neighbor[peer-address={addr}]/afi-safi[afi-safi-name={afi}]/received-routes": prefixes_received,
            f"/network-instance[name={ni}]/protocols/bgp/neighbor[peer-address={addr}]/afi-safi[afi-safi-name={afi}]/advertised-routes": prefixes_advertised,
            f"/network-instance[name={ni}]/protocols/bgp/neighbor[peer-address={addr}]/peer-as": peer["peer_as"],
        },
    }


def compute_bgp_peer_state(
    device: SimDevice,
    peer: dict[str, Any],
    scenario: str,
    seconds_remaining: int,
) -> tuple[str, str | None, int, int]:
    normal_rx = peer["normal_prefixes"]
    normal_tx = normal_rx + 4
    rr        = peer.get("rr", "rr-01")
    if scenario == "healthy":
        return "established", None, normal_rx, normal_tx
    elif scenario == "rr_failure":
        if rr == "rr-01":
            return "idle", "tcp_connect_failed", 0, 0
        return "established", None, normal_rx, normal_tx
    elif scenario == "prefix_drain":
        if device.name == "leaf-01":
            return "established", None, 0, normal_tx
        return "established", None, normal_rx, normal_tx
    elif scenario == "flap":
        if device.name == "leaf-02":
            flap_phase = (seconds_remaining // 30) % 2
            if flap_phase == 0:
                return "idle", "hold_timer_expired", 0, 0
            return "established", None, normal_rx // 2, normal_tx
        return "established", None, normal_rx, normal_tx
    elif scenario == "recovery":
        device_order = ["leaf-01", "leaf-02", "leaf-03", "leaf-04"]
        device_index = device_order.index(device.name) if device.name in device_order else 3
        recovery_threshold = _scenario_duration() * 0.25 * (3 - device_index)
        if rr == "rr-01" and seconds_remaining > recovery_threshold:
            return "active", "tcp_connect_failed", 0, 0
        return "established", None, normal_rx, normal_tx
    return "established", None, normal_rx, normal_tx


# ── EVPN event generation ─────────────────────────────────────────────────────

def _evpn_vni_event(
    device: SimDevice,
    vni_def: dict[str, Any],
    oper_state: str,
    remote_vteps: list[str],
) -> list[dict[str, Any]]:
    """Generate VNI state + VTEP peer events for one VNI."""
    events = []
    ni     = "default"
    vni    = vni_def["vni"]
    vlan   = vni_def["vlan"]
    port   = device.gnmi_port

    # VNI operational state event
    events.append({
        "source": f"{device.name}:{port}", "timestamp": _now_ns(), "time": _now_iso(),
        "tags": {
            "network-instance_name": ni,
            "vlan_vlan-id":          str(vlan),
            "subscription-name":     "evpn",
            "source":                f"{device.name}:{port}",
        },
        "values": {
            f"/network-instances/network-instance[name={ni}]/vlans/vlan[vlan-id={vlan}]/vxlan/state/vni":        vni,
            f"/network-instances/network-instance[name={ni}]/vlans/vlan[vlan-id={vlan}]/vxlan/state/oper-state": oper_state,
            f"/network-instances/network-instance[name={ni}]/vlans/vlan[vlan-id={vlan}]/vxlan/state/admin-state": "up",
        },
    })

    # VTEP peer events — one per remote VTEP
    for vtep_ip in remote_vteps:
        events.append({
            "source": f"{device.name}:{port}", "timestamp": _now_ns(), "time": _now_iso(),
            "tags": {
                "network-instance_name":   ni,
                "vlan_vlan-id":            str(vlan),
                "endpoint_peer-ip":        vtep_ip,
                "subscription-name":       "evpn",
                "source":                  f"{device.name}:{port}",
            },
            "values": {
                f"/network-instances/network-instance[name={ni}]/vlans/vlan[vlan-id={vlan}]/vxlan/endpoints/endpoint[peer-ip={vtep_ip}]/state/peer-ip": vtep_ip,
                f"/network-instances/network-instance[name={ni}]/vlans/vlan[vlan-id={vlan}]/vxlan/endpoints/endpoint[peer-ip={vtep_ip}]/state/vni":     vni,
            },
        })

    return events


def _evpn_mac_event(
    device: SimDevice,
    mac_def: dict[str, Any],
    mobility_count: int,
    peer_vtep: str | None,
) -> dict[str, Any]:
    """Generate MAC table event with mobility counter."""
    ni   = "default"
    mac  = mac_def["mac"]
    vni  = mac_def["vni"]
    vlan = vni // 100  # simple vlan derivation for simulation
    port = device.gnmi_port
    return {
        "source": f"{device.name}:{port}", "timestamp": _now_ns(), "time": _now_iso(),
        "tags": {
            "network-instance_name":   ni,
            "entry_mac-address":       mac,
            "vni":                     str(vni),
            "subscription-name":       "evpn",
            "source":                  f"{device.name}:{port}",
        },
        "values": {
            f"/network-instances/network-instance[name={ni}]/fdb/mac-table/entries/entry[mac-address={mac}][vlan={vlan}]/state/vni":            vni,
            f"/network-instances/network-instance[name={ni}]/fdb/mac-table/entries/entry[mac-address={mac}][vlan={vlan}]/state/entry-type":     "dynamic",
            f"/network-instances/network-instance[name={ni}]/fdb/mac-table/entries/entry[mac-address={mac}][vlan={vlan}]/state/mobility-seq-no": mobility_count,
            f"/network-instances/network-instance[name={ni}]/fdb/mac-table/entries/entry[mac-address={mac}][vlan={vlan}]/state/peer-vtep":      peer_vtep,
        },
    }


def _evpn_esi_event(
    device: SimDevice,
    esi_def: dict[str, Any],
    active_links: int,
) -> dict[str, Any]:
    """Generate ESI state event."""
    ni   = "default"
    esi  = esi_def["esi"]
    port = device.gnmi_port
    df   = device.local_vtep if active_links >= 2 else None
    return {
        "source": f"{device.name}:{port}", "timestamp": _now_ns(), "time": _now_iso(),
        "tags": {
            "network-instance_name":         ni,
            "ethernet-segment_esi":          esi,
            "subscription-name":             "evpn",
            "source":                        f"{device.name}:{port}",
        },
        "values": {
            f"/network-instances/network-instance[name={ni}]/evpn/ethernet-segments/ethernet-segment[esi={esi}]/state/esi":                  esi,
            f"/network-instances/network-instance[name={ni}]/evpn/ethernet-segments/ethernet-segment[esi={esi}]/state/designated-forwarder": df,
            f"/network-instances/network-instance[name={ni}]/evpn/ethernet-segments/ethernet-segment[esi={esi}]/state/active-links":         active_links,
        },
    }


def _evpn_type3_route_event(
    device: SimDevice,
    vni: int,
    vtep_count: int,
) -> dict[str, Any]:
    """Generate EVPN type-3 IMET route count event."""
    ni   = "default"
    port = device.gnmi_port
    rd   = f"{device.local_vtep}:{vni}"
    return {
        "source": f"{device.name}:{port}", "timestamp": _now_ns(), "time": _now_iso(),
        "tags": {
            "network-instance_name": ni, "vni": str(vni),
            "subscription-name": "evpn", "source": f"{device.name}:{port}",
        },
        "values": {
            f"/network-instances/network-instance[name={ni}]/protocols/protocol[identifier=BGP][name=BGP]/bgp/rib/afi-safis/afi-safi[afi-safi-name=L2VPN_EVPN]/l2vpn-evpn/loc-rib/routes/route-distinguisher[route-distinguisher={rd}]/inclusive-multicast-ethernet-tag/routes/route[originating-router={device.local_vtep}]/state/attr-index": vtep_count,
        },
    }


def compute_evpn_device_state(
    device: SimDevice,
    scenario: str,
    seconds_remaining: int,
) -> dict[str, Any]:
    """
    Compute EVPN state for one device under the current scenario.

    Returns:
      vni_states    — per-VNI (vni, oper_state, remote_vteps)
      mac_states    — per-MAC (mac, mobility_count, peer_vtep)
      esi_states    — per-ESI (esi, active_links)
      type3_counts  — per-VNI type-3 route count
    """
    vni_states:   list[dict[str, Any]] = []
    mac_states:   list[dict[str, Any]] = []
    esi_states:   list[dict[str, Any]] = []
    type3_counts: dict[int, int]       = {}

    for vni_def in device.vnis:
        vni          = vni_def["vni"]
        all_vteps    = list(vni_def["remote_vteps"])
        oper_state   = "up"
        remote_vteps = list(all_vteps)
        type3_count  = len(all_vteps) + 1  # +1 for self

        if scenario == "healthy":
            pass  # defaults above

        elif scenario == "rr_failure":
            # EVPN BGP sessions to rr-01 drop — type-3 routes withdrawn
            # from devices that had rr-01 as their EVPN route reflector
            # This manifests as reduced VTEP peer table
            if device.name in ("leaf-01", "leaf-03"):
                # Remove leaf-02 and leaf-04 from VTEP table (lost via rr-01)
                remote_vteps = [v for v in all_vteps
                                if v not in ("10.0.1.2", "10.0.1.4")]
                type3_count  = len(remote_vteps) + 1

        elif scenario == "prefix_drain":
            # leaf-01 VNI 10100 loses all remote VTEPs (type-3 withdrawn)
            if device.name == "leaf-01" and vni == 10100:
                remote_vteps = []
                type3_count  = 1  # only self
                oper_state   = "up"  # session still up, routes gone

        elif scenario == "flap":
            # leaf-02 VNI 10200 VTEP table flaps
            if device.name == "leaf-02" and vni == 10200:
                flap_phase = (seconds_remaining // 30) % 2
                if flap_phase == 0:
                    remote_vteps = all_vteps[:1]  # only first VTEP visible
                    type3_count  = 2

        elif scenario == "recovery":
            # Gradual recovery — VTEPs come back one by one
            device_order = ["leaf-01", "leaf-02", "leaf-03", "leaf-04"]
            idx = device_order.index(device.name) if device.name in device_order else 3
            recovered_count = max(1, len(all_vteps) - idx)
            remote_vteps = all_vteps[:recovered_count]
            type3_count  = recovered_count + 1

        vni_states.append({
            "vni":          vni,
            "oper_state":   oper_state,
            "remote_vteps": remote_vteps,
        })
        type3_counts[vni] = type3_count

    # ── MAC states ─────────────────────────────────────────────────────────
    for mac_def in device.macs:
        mobility_count = 0
        peer_vtep      = None

        if scenario == "flap" and device.name == "leaf-02" \
                and mac_def["mac"] == "00:50:56:aa:bb:01":
            # This MAC is the storm MAC — high mobility count
            mobility_count = 12 + (seconds_remaining % 8)
            peer_vtep      = "10.0.1.1"

        elif scenario == "recovery" and device.name == "leaf-02" \
                and mac_def["mac"] == "00:50:56:aa:bb:01":
            # Settling — mobility count dropping
            mobility_count = max(0, 8 - (120 - seconds_remaining) // 15)
            peer_vtep      = "10.0.1.1" if mobility_count > 0 else None

        mac_states.append({
            "mac":            mac_def["mac"],
            "vni":            mac_def["vni"],
            "mobility_count": mobility_count,
            "peer_vtep":      peer_vtep,
            "is_local":       mac_def.get("is_local", True),
        })

    # ── ESI states ─────────────────────────────────────────────────────────
    for esi_def in device.esis:
        active_links = esi_def["expected_links"]

        # In rr_failure, one ESI link goes down on affected devices
        if scenario == "rr_failure" and device.name == "leaf-01":
            active_links = 1

        # In recovery, ESI links recover
        elif scenario == "recovery" and device.name == "leaf-01":
            active_links = 2 if seconds_remaining < 60 else 1

        esi_states.append({
            "esi":          esi_def["esi"],
            "active_links": active_links,
        })

    return {
        "vni_states":   vni_states,
        "mac_states":   mac_states,
        "esi_states":   esi_states,
        "type3_counts": type3_counts,
    }


def generate_evpn_events(
    scenario: str,
    seconds_remaining: int,
) -> list[dict[str, Any]]:
    """Generate full EVPN telemetry for all devices under current scenario."""
    events: list[dict[str, Any]] = []

    for device in DEVICES:
        state = compute_evpn_device_state(device, scenario, seconds_remaining)

        # VNI and VTEP events
        for vni_state in state["vni_states"]:
            events.extend(_evpn_vni_event(
                device,
                next(v for v in device.vnis if v["vni"] == vni_state["vni"]),
                vni_state["oper_state"],
                vni_state["remote_vteps"],
            ))
            # Type-3 route count event
            events.append(_evpn_type3_route_event(
                device,
                vni_state["vni"],
                state["type3_counts"].get(vni_state["vni"], 0),
            ))

        # MAC events
        for mac_state in state["mac_states"]:
            mac_def = next(
                (m for m in device.macs if m["mac"] == mac_state["mac"]), None
            )
            if mac_def:
                events.append(_evpn_mac_event(
                    device, mac_def,
                    mac_state["mobility_count"],
                    mac_state["peer_vtep"],
                ))

        # ESI events
        for esi_state in state["esi_states"]:
            esi_def = next(
                (e for e in device.esis if e["esi"] == esi_state["esi"]), None
            )
            if esi_def:
                events.append(_evpn_esi_event(
                    device, esi_def, esi_state["active_links"]
                ))

    return events


# ── BGP event generation ──────────────────────────────────────────────────────

def generate_bgp_events(
    scenario: str,
    seconds_remaining: int,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for device in DEVICES:
        for peer in device.peers:
            session_state, last_error, rx, tx = compute_bgp_peer_state(
                device, peer, scenario, seconds_remaining
            )
            if device.nos_family == "srlinux":
                events.append(_srlinux_bgp_event(
                    device, peer, session_state, last_error, rx, tx
                ))
            else:
                events.append(_openconfig_bgp_event(
                    device, peer, session_state, last_error, rx, tx
                ))
    return events


# ── File I/O ──────────────────────────────────────────────────────────────────

def write_events(events: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(events, indent=2), encoding="utf-8")
    tmp.replace(path)


# ── Main loop ─────────────────────────────────────────────────────────────────

def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    bgp_file   = _bgp_output_file()
    evpn_file  = _evpn_output_file()
    poll       = _poll_interval()
    clock      = ScenarioClock(_scenario_duration())

    LOG.info(
        "gnmi-simulator starting — bgp=%s evpn=%s poll=%ds",
        bgp_file, evpn_file, poll,
    )

    while True:
        try:
            scenario  = clock.current()
            remaining = clock.seconds_remaining()

            bgp_events  = generate_bgp_events(scenario, remaining)
            evpn_events = generate_evpn_events(scenario, remaining)

            write_events(bgp_events,  bgp_file)
            write_events(evpn_events, evpn_file)

            LOG.info(
                "scenario=%-12s  remaining=%3ds  bgp_events=%d  evpn_events=%d",
                scenario, remaining, len(bgp_events), len(evpn_events),
            )

        except Exception as exc:
            LOG.error("simulator error: %s", exc)

        time.sleep(poll)


if __name__ == "__main__":
    run()
