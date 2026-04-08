"""
simulator.py — Synthetic gNMI BGP telemetry generator.

Generates realistic OpenConfig BGP state for four vendors across multiple
simulated devices and writes it in gnmic event-format JSON to a shared file.
The capsule bgp-snapshot-writer reads this file and translates it into
bgp_snapshot.json for nre-agent.

When real devices are available:
  1. Remove this pod from the Helm chart
  2. Deploy gnmic pointing at real devices with file output to the same path
  3. Nothing else in the pipeline changes

Simulated devices:
  leaf-01   arista  EOS     — RR client, connected to rr-01 and rr-02
  leaf-02   juniper Junos   — RR client, connected to rr-01 and rr-02
  leaf-03   cisco   NX-OS   — RR client, connected to rr-01 and rr-02
  leaf-04   nokia   SR Linux — RR client, connected to rr-01 and rr-02
  rr-01     arista  EOS     — Route reflector spine
  rr-02     juniper Junos   — Route reflector spine

Fault scenarios (cycle every SCENARIO_DURATION_SECONDS):
  1. healthy      — all sessions ESTABLISHED, normal prefix counts
  2. rr_failure   — rr-01 unreachable, all rr-01 clients show IDLE
  3. prefix_drain — leaf-01 peers established but prefixes drop to zero
  4. flap         — leaf-02 sessions flap between ESTABLISHED and IDLE
  5. recovery     — all sessions recovering, mixed states

Environment variables:
  GNMIC_OUTPUT_FILE          default: /data/gnmic_bgp.json
  SCENARIO_DURATION_SECONDS  default: 120  (seconds per scenario)
  POLL_INTERVAL_SECONDS      default: 30   (write interval)
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

def _output_file() -> Path:
    return Path(os.getenv("GNMIC_OUTPUT_FILE", "/data/gnmic_bgp.json"))

def _scenario_duration() -> int:
    return int(os.getenv("SCENARIO_DURATION_SECONDS", "120"))

def _poll_interval() -> int:
    return int(os.getenv("POLL_INTERVAL_SECONDS", "30"))

def _fabric() -> str:
    return os.getenv("FABRIC_NAME", "prod-dc-west")


# ── Device topology ───────────────────────────────────────────────────────────

@dataclass
class SimDevice:
    """One simulated device with its BGP peers."""
    name:       str
    vendor:     str
    nos_family: str
    gnmi_port:  int
    peers: list[dict[str, Any]] = field(default_factory=list)


# Full fabric topology — four leaf vendors + two RR spines
DEVICES: list[SimDevice] = [
    SimDevice(
        name="leaf-01",
        vendor="arista",
        nos_family="eos",
        gnmi_port=6030,
        peers=[
            {
                "address":          "10.0.0.10",
                "peer_as":          "65000",
                "network_instance": "default",
                "afi_safi":         "IPV4_UNICAST",
                "is_rr_client":     True,
                "rr":               "rr-01",
                "normal_prefixes":  128,
            },
            {
                "address":          "10.0.0.11",
                "peer_as":          "65000",
                "network_instance": "default",
                "afi_safi":         "IPV4_UNICAST",
                "is_rr_client":     True,
                "rr":               "rr-02",
                "normal_prefixes":  128,
            },
        ],
    ),
    SimDevice(
        name="leaf-02",
        vendor="juniper",
        nos_family="junos",
        gnmi_port=32767,
        peers=[
            {
                "address":          "10.0.0.12",
                "peer_as":          "65000",
                "network_instance": "default",
                "afi_safi":         "IPV4_UNICAST",
                "is_rr_client":     True,
                "rr":               "rr-01",
                "normal_prefixes":  96,
            },
            {
                "address":          "10.0.0.13",
                "peer_as":          "65000",
                "network_instance": "default",
                "afi_safi":         "IPV4_UNICAST",
                "is_rr_client":     True,
                "rr":               "rr-02",
                "normal_prefixes":  96,
            },
        ],
    ),
    SimDevice(
        name="leaf-03",
        vendor="cisco",
        nos_family="nx_os",
        gnmi_port=50051,
        peers=[
            {
                "address":          "10.0.0.14",
                "peer_as":          "65000",
                "network_instance": "default",
                "afi_safi":         "IPV4_UNICAST",
                "is_rr_client":     True,
                "rr":               "rr-01",
                "normal_prefixes":  112,
            },
            {
                "address":          "10.0.0.15",
                "peer_as":          "65000",
                "network_instance": "default",
                "afi_safi":         "IPV4_UNICAST",
                "is_rr_client":     True,
                "rr":               "rr-02",
                "normal_prefixes":  112,
            },
        ],
    ),
    SimDevice(
        name="leaf-04",
        vendor="nokia",
        nos_family="srlinux",
        gnmi_port=57400,
        peers=[
            {
                "address":          "10.0.0.16",
                "peer_as":          "65000",
                "network_instance": "default",
                "afi_safi":         "IPV4_UNICAST",
                "is_rr_client":     True,
                "rr":               "rr-01",
                "normal_prefixes":  80,
            },
            {
                "address":          "10.0.0.17",
                "peer_as":          "65000",
                "network_instance": "default",
                "afi_safi":         "IPV4_UNICAST",
                "is_rr_client":     True,
                "rr":               "rr-02",
                "normal_prefixes":  80,
            },
        ],
    ),
]


# ── Scenario engine ───────────────────────────────────────────────────────────

SCENARIOS = [
    "healthy",
    "rr_failure",
    "prefix_drain",
    "flap",
    "recovery",
]


class ScenarioClock:
    """
    Advances through fault scenarios at a fixed interval.

    Each scenario runs for SCENARIO_DURATION_SECONDS before moving
    to the next one in the cycle.
    """

    def __init__(self, duration_s: int) -> None:
        self._duration   = duration_s
        self._start_time = time.time()
        self._index      = 0

    def current(self) -> str:
        elapsed  = time.time() - self._start_time
        self._index = int(elapsed / self._duration) % len(SCENARIOS)
        return SCENARIOS[self._index]

    def seconds_remaining(self) -> int:
        elapsed = time.time() - self._start_time
        position_in_slot = elapsed % self._duration
        return int(self._duration - position_in_slot)


# ── Per-vendor event generation ───────────────────────────────────────────────

def _now_ns() -> int:
    """Current time as nanosecond Unix timestamp (gnmic format)."""
    return int(time.time() * 1_000_000_000)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _openconfig_event(
    device: SimDevice,
    peer: dict[str, Any],
    session_state: str,
    last_error: str | None,
    prefixes_received: int,
    prefixes_advertised: int,
) -> dict[str, Any]:
    """
    Build one gnmic event-format JSON object using OpenConfig paths.

    Used for arista, juniper, cisco, and nokia SR OS.
    gnmic event format documentation:
      https://gnmic.openconfig.net/user_guide/outputs/event_format/
    """
    ni   = peer["network_instance"]
    addr = peer["address"]
    afi  = peer["afi_safi"]
    port = device.gnmi_port

    return {
        "source":    f"{device.name}:{port}",
        "timestamp": _now_ns(),
        "time":      _now_iso(),
        "tags": {
            "network-instance_name":       ni,
            "neighbor_neighbor-address":   addr,
            "afi-safi_afi-safi-name":      afi,
            "subscription-name":           "bgp_session",
            "source":                      f"{device.name}:{port}",
        },
        "values": {
            # ── Session state ─────────────────────────────────────────────
            f"/network-instances/network-instance[name={ni}]"
            f"/protocols/protocol[identifier=BGP][name=BGP]"
            f"/bgp/neighbors/neighbor[neighbor-address={addr}]"
            f"/state/session-state":
                session_state.upper(),

            # ── Last error ────────────────────────────────────────────────
            f"/network-instances/network-instance[name={ni}]"
            f"/protocols/protocol[identifier=BGP][name=BGP]"
            f"/bgp/neighbors/neighbor[neighbor-address={addr}]"
            f"/state/last-error":
                last_error.upper().replace("_", "-") if last_error else None,

            # ── Prefix counts ─────────────────────────────────────────────
            f"/network-instances/network-instance[name={ni}]"
            f"/protocols/protocol[identifier=BGP][name=BGP]"
            f"/bgp/neighbors/neighbor[neighbor-address={addr}]"
            f"/afi-safis/afi-safi[afi-safi-name={afi}]"
            f"/state/prefixes/received":
                prefixes_received,

            f"/network-instances/network-instance[name={ni}]"
            f"/protocols/protocol[identifier=BGP][name=BGP]"
            f"/bgp/neighbors/neighbor[neighbor-address={addr}]"
            f"/afi-safis/afi-safi[afi-safi-name={afi}]"
            f"/state/prefixes/sent":
                prefixes_advertised,

            # ── Peer AS ───────────────────────────────────────────────────
            f"/network-instances/network-instance[name={ni}]"
            f"/protocols/protocol[identifier=BGP][name=BGP]"
            f"/bgp/neighbors/neighbor[neighbor-address={addr}]"
            f"/state/peer-as":
                peer["peer_as"],

            # ── RR client flag ────────────────────────────────────────────
            f"/network-instances/network-instance[name={ni}]"
            f"/protocols/protocol[identifier=BGP][name=BGP]"
            f"/bgp/neighbors/neighbor[neighbor-address={addr}]"
            f"/route-reflector/state/route-reflector-client":
                peer.get("is_rr_client", False),
        },
    }


def _srlinux_event(
    device: SimDevice,
    peer: dict[str, Any],
    session_state: str,
    last_error: str | None,
    prefixes_received: int,
    prefixes_advertised: int,
) -> dict[str, Any]:
    """
    Build one gnmic event-format JSON object using SR Linux native paths.

    SR Linux uses /network-instance[name=*] (singular, no wrapper) and
    exposes failure-reason instead of last-error which gives more precise
    disconnect causes.
    """
    ni   = peer["network_instance"]
    addr = peer["address"]
    afi  = peer["afi_safi"]
    port = device.gnmi_port

    # ── Map normalized error code to SR Linux failure-reason values ───────
    failure_reason_map = {
        "tcp_connect_failed":    "tcp-failure",
        "hold_timer_expired":    "hold-time-expired",
        "notification_received": "notification-received",
        "auth_failure":          "authentication-failure",
        "admin_shutdown":        "local-close",
    }
    failure_reason = failure_reason_map.get(last_error or "", "unknown")

    return {
        "source":    f"{device.name}:{port}",
        "timestamp": _now_ns(),
        "time":      _now_iso(),
        "tags": {
            "network-instance_name": ni,
            "peer-address":          addr,
            "afi_safi_name":         afi,
            "subscription-name":     "bgp_session",
            "source":                f"{device.name}:{port}",
        },
        "values": {
            # ── Session state (SR Linux uses lowercase) ───────────────────
            f"/network-instance[name={ni}]"
            f"/protocols/bgp/neighbor[peer-address={addr}]"
            f"/session-state":
                session_state.lower(),

            # ── Failure reason (richer than last-error) ───────────────────
            f"/network-instance[name={ni}]"
            f"/protocols/bgp/neighbor[peer-address={addr}]"
            f"/failure-reason":
                failure_reason if session_state != "established" else None,

            # ── Last event ────────────────────────────────────────────────
            f"/network-instance[name={ni}]"
            f"/protocols/bgp/neighbor[peer-address={addr}]"
            f"/last-event":
                "session-down" if session_state != "established" else "established",

            # ── Prefix counts ─────────────────────────────────────────────
            f"/network-instance[name={ni}]"
            f"/protocols/bgp/neighbor[peer-address={addr}]"
            f"/afi-safi[afi-safi-name={afi}]"
            f"/received-routes":
                prefixes_received,

            f"/network-instance[name={ni}]"
            f"/protocols/bgp/neighbor[peer-address={addr}]"
            f"/afi-safi[afi-safi-name={afi}]"
            f"/advertised-routes":
                prefixes_advertised,

            # ── Peer AS ───────────────────────────────────────────────────
            f"/network-instance[name={ni}]"
            f"/protocols/bgp/neighbor[peer-address={addr}]"
            f"/peer-as":
                peer["peer_as"],
        },
    }


def _build_event(
    device: SimDevice,
    peer: dict[str, Any],
    session_state: str,
    last_error: str | None,
    prefixes_received: int,
    prefixes_advertised: int,
) -> dict[str, Any]:
    """Dispatch to the correct event builder based on vendor/nos_family."""
    if device.nos_family == "srlinux":
        return _srlinux_event(
            device, peer,
            session_state, last_error,
            prefixes_received, prefixes_advertised,
        )
    return _openconfig_event(
        device, peer,
        session_state, last_error,
        prefixes_received, prefixes_advertised,
    )


# ── Scenario state computation ────────────────────────────────────────────────

def compute_peer_state(
    device: SimDevice,
    peer: dict[str, Any],
    scenario: str,
    scenario_seconds_remaining: int,
) -> tuple[str, str | None, int, int]:
    """
    Return (session_state, last_error, prefixes_received, prefixes_advertised)
    for a given peer under the current scenario.

    Scenarios:
      healthy      all sessions ESTABLISHED, full prefix counts
      rr_failure   rr-01 peers go IDLE with tcp_connect_failed
      prefix_drain leaf-01 peers ESTABLISHED but prefixes drain to 0
      flap         leaf-02 sessions alternate ESTABLISHED/IDLE
      recovery     sessions coming back up from rr_failure
    """
    normal_rx = peer["normal_prefixes"]
    normal_tx = normal_rx + 4   # advertise slightly more than received
    rr        = peer.get("rr", "rr-01")

    if scenario == "healthy":
        return "established", None, normal_rx, normal_tx

    elif scenario == "rr_failure":
        # Only rr-01 clients are affected — rr-02 sessions stay up
        if rr == "rr-01":
            return "idle", "tcp_connect_failed", 0, 0
        return "established", None, normal_rx, normal_tx

    elif scenario == "prefix_drain":
        # Only leaf-01 is affected — all vendors show this
        if device.name == "leaf-01":
            # Established session but zero prefixes received
            return "established", None, 0, normal_tx
        return "established", None, normal_rx, normal_tx

    elif scenario == "flap":
        # leaf-02 sessions alternate based on time remaining in slot
        if device.name == "leaf-02":
            # Flap every 30 seconds within the scenario window
            flap_phase = (scenario_seconds_remaining // 30) % 2
            if flap_phase == 0:
                return "idle", "hold_timer_expired", 0, 0
            return "established", None, normal_rx // 2, normal_tx
        return "established", None, normal_rx, normal_tx

    elif scenario == "recovery":
        # Sessions recovering — rr-01 clients come back one by one
        # based on device order (leaf-01 recovers first, leaf-04 last)
        device_order = ["leaf-01", "leaf-02", "leaf-03", "leaf-04"]
        device_index = device_order.index(device.name) \
            if device.name in device_order else 3
        recovery_threshold = _scenario_duration() * 0.25 * (3 - device_index)

        if rr == "rr-01" and scenario_seconds_remaining > recovery_threshold:
            return "active", "tcp_connect_failed", 0, 0
        return "established", None, normal_rx, normal_tx

    # Default to healthy
    return "established", None, normal_rx, normal_tx


# ── Main loop ─────────────────────────────────────────────────────────────────

def generate_events(scenario: str, seconds_remaining: int) -> list[dict[str, Any]]:
    """Generate one full set of gnmic events for all devices and peers."""
    events: list[dict[str, Any]] = []

    for device in DEVICES:
        for peer in device.peers:
            session_state, last_error, rx, tx = compute_peer_state(
                device, peer, scenario, seconds_remaining
            )
            event = _build_event(device, peer, session_state, last_error, rx, tx)
            events.append(event)

    return events


def write_events(events: list[dict[str, Any]], path: Path) -> None:
    """Write events as a JSON array to path atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(events, indent=2), encoding="utf-8")
    tmp.replace(path)


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    output_file = _output_file()
    poll        = _poll_interval()
    clock       = ScenarioClock(_scenario_duration())

    LOG.info(
        "gnmi-simulator starting — output=%s poll=%ds scenario_duration=%ds",
        output_file, poll, _scenario_duration(),
    )

    while True:
        try:
            scenario   = clock.current()
            remaining  = clock.seconds_remaining()
            events     = generate_events(scenario, remaining)

            write_events(events, output_file)

            LOG.info(
                "scenario=%-12s  remaining=%3ds  events=%d",
                scenario, remaining, len(events),
            )

        except Exception as exc:
            LOG.error("simulator error: %s", exc)

        time.sleep(poll)


if __name__ == "__main__":
    run()
