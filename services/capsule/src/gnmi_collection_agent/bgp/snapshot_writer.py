"""
snapshot_writer.py — Translate gnmic BGP telemetry into bgp_snapshot.json.

This is the bridge between the gNMI collection layer and nre-agent.

Input:  /data/gnmic_bgp.json  — gnmic event-format JSON written by the
                                 gnmi-simulator (or real gnmic in production)
Output: /data/bgp_snapshot.json — the format nre-agent already reads

Translation contract:
  gnmic event format  →  bgp_snapshot.json field
  ─────────────────────────────────────────────────────────────────
  neighbor-address key  →  peer
  session-state value   →  session_state  (lowercased)
  last-error value      →  last_error     (normalized, see _normalize_error)
  failure-reason value  →  last_error     (SR Linux native, see above)
  prefixes/received     →  prefixes_received
  afi-safi-name key     →  address_family (normalized, see _normalize_afi)
  source field          →  device         (hostname stripped of port)
  network-instance key  →  network_instance
  timestamp field       →  timestamp      (ISO 8601)

Shared dependency detection:
  When multiple peers on the same device share the same last_error
  and are all non-ESTABLISHED, the writer sets shared_dependency to
  the most common peer AS or the route reflector peer IP if one is
  identified. This is a heuristic — nre-agent's lattice analysis does
  the authoritative correlation.

Usage:
  Run as a long-lived process. Watches for changes to gnmic_bgp.json
  and rewrites bgp_snapshot.json whenever the input changes.

  GNMIC_OUTPUT_FILE=/data/gnmic_bgp.json
  SNAPSHOT_OUTPUT_FILE=/data/bgp_snapshot.json
  POLL_INTERVAL_SECONDS=30
  python -m gnmi_collection_agent.bgp.snapshot_writer
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)

# ── Environment config ────────────────────────────────────────────────────────

def _gnmic_output_file() -> Path:
    return Path(os.getenv("GNMIC_OUTPUT_FILE", "/data/gnmic_bgp.json"))

def _snapshot_output_file() -> Path:
    return Path(os.getenv("SNAPSHOT_OUTPUT_FILE", "/data/bgp_snapshot.json"))

def _poll_interval() -> int:
    return int(os.getenv("POLL_INTERVAL_SECONDS", "30"))

def _fabric_name() -> str:
    return os.getenv("FABRIC_NAME", "default")


# ── Path parsing ──────────────────────────────────────────────────────────────

# Regex to extract key=value pairs from gNMI path elements like
# /network-instances/network-instance[name=default]/...
_KEY_RE = re.compile(r'\[([^=\]]+)=([^\]]+)\]')


def _extract_keys(path: str) -> dict[str, str]:
    """
    Extract all [key=value] pairs from a gNMI path string.

    Example:
      input:  ".../neighbor[neighbor-address=10.0.0.12]/afi-safis/afi-safi[afi-safi-name=IPV4_UNICAST]/..."
      output: {"neighbor-address": "10.0.0.12", "afi-safi-name": "IPV4_UNICAST"}
    """
    return {m.group(1): m.group(2) for m in _KEY_RE.finditer(path)}


def _path_leaf(path: str) -> str:
    """Return the last path element, stripping any key predicates."""
    segment = path.rstrip("/").split("/")[-1]
    return _KEY_RE.sub("", segment).strip("-")


# ── Value normalization ───────────────────────────────────────────────────────

def _normalize_session_state(raw: Any) -> str:
    """
    Normalize BGP session state to the lowercase values nre-agent expects.

    OpenConfig returns uppercase (IDLE, ESTABLISHED, etc.).
    SR Linux native returns mixed case (idle, Established, etc.).
    We always return lowercase.
    """
    if raw is None:
        return "idle"
    return str(raw).lower()


def _normalize_error(raw: Any) -> str | None:
    """
    Normalize last-error and failure-reason values to nre-agent error codes.

    OpenConfig last-error values vary by vendor:
      Arista:  "TCP_CONNECT_FAILED", "HOLD_TIMER_EXPIRED", etc.
      Junos:   "tcp-connect-failed", "hold-timer-expired", etc.
      NX-OS:   "TcpConnectFailed", "HoldTimerExpired", etc.
      SR Linux failure-reason: "tcp-failure", "hold-time-expired", etc.

    nre-agent expects: "tcp_connect_failed", "hold_timer_expired", etc.
    """
    if raw is None:
        return None

    s = str(raw).lower()

    # ── Map known patterns to normalized codes ─────────────────────────────
    if any(x in s for x in ("tcp", "connect", "transport")):
        return "tcp_connect_failed"
    if any(x in s for x in ("hold", "timer")):
        return "hold_timer_expired"
    if any(x in s for x in ("notification", "notif")):
        return "notification_received"
    if any(x in s for x in ("open", "msg", "message")):
        return "open_message_error"
    if any(x in s for x in ("auth", "password")):
        return "auth_failure"
    if any(x in s for x in ("prefix", "limit")):
        return "prefix_limit_exceeded"
    if any(x in s for x in ("cease", "admin", "shutdown")):
        return "admin_shutdown"

    # ── Unknown error — normalize separators and return as-is ─────────────
    return re.sub(r"[-\s]+", "_", s).strip("_") or None


def _normalize_afi(raw: Any) -> str:
    """
    Normalize AFI-SAFI name to the lowercase underscore format nre-agent uses.

    OpenConfig values:  "IPV4_UNICAST", "openconfig-bgp-types:IPV4_UNICAST"
    nre-agent expects:  "ipv4_unicast"
    """
    if raw is None:
        return "ipv4_unicast"

    s = str(raw).lower()

    # Strip OpenConfig type prefix if present (openconfig-bgp-types:IPV4_UNICAST)
    if ":" in s:
        s = s.split(":")[-1]

    return s.replace("-", "_")


def _strip_port(source: str) -> str:
    """
    Strip the port number from a gnmic source field.

    gnmic source format: "leaf-01:6030" or "192.168.1.1:57400"
    We want:             "leaf-01"      or "192.168.1.1"
    """
    return source.rsplit(":", 1)[0] if ":" in source else source


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── gnmic event parsing ───────────────────────────────────────────────────────

def parse_gnmic_events(raw: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """
    Parse a list of gnmic event-format JSON objects into a structured dict
    keyed by (device, network_instance, peer_address).

    gnmic event format (one object per update):
    {
      "source":    "leaf-01:6030",
      "timestamp": 1711812006000000000,
      "time":      "2024-03-30T...",
      "tags": {
        "network-instance_name":   "default",
        "neighbor_neighbor-address": "10.0.0.12",
        "afi-safi_afi-safi-name":  "IPV4_UNICAST"
      },
      "values": {
        "/network-instances/.../session-state": "IDLE",
        "/network-instances/.../last-error":    "TCP_CONNECT_FAILED"
      }
    }

    Returns a dict keyed by (device, network_instance, peer) containing
    the merged state for each peer across all received events.
    """
    # peers[device][ni][peer] = merged state dict
    peers: dict[str, dict[str, dict[str, Any]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(dict))
    )

    for event in raw:
        if not isinstance(event, dict):
            continue

        source    = event.get("source", "unknown")
        device    = _strip_port(source)
        timestamp = event.get("time") or _now_iso()
        tags      = event.get("tags", {}) or {}
        values    = event.get("values", {}) or {}

        # ── Extract network instance and peer from tags ────────────────────
        # gnmic flattens path keys into tags with mangled names
        ni   = (tags.get("network-instance_name")
                or tags.get("network_instance_name")
                or "default")
        peer = (tags.get("neighbor_neighbor-address")
                or tags.get("peer-address")
                or tags.get("neighbor_peer-address"))

        if not peer:
            # Fall back to extracting peer from the path key in values
            for path_key in values:
                keys = _extract_keys(path_key)
                peer = (keys.get("neighbor-address")
                        or keys.get("peer-address"))
                if peer:
                    break

        if not peer:
            continue

        afi_raw = (tags.get("afi-safi_afi-safi-name")
                   or tags.get("afi_safi_name"))

        if peer not in peers[device][ni]:
            peers[device][ni][peer] = {}
        state = peers[device][ni][peer]

        # ── Set timestamp if not already set ──────────────────────────────
        if "timestamp" not in state:
            state["timestamp"] = timestamp

        # ── Extract values from the values dict ───────────────────────────
        for path_key, value in values.items():
            leaf = _path_leaf(path_key)

            if leaf in ("session-state", "session_state"):
                state["session_state"] = _normalize_session_state(value)

            elif leaf in ("last-error", "last_error"):
                state["last_error"] = _normalize_error(value)

            elif leaf in ("failure-reason", "failure_reason"):
                # SR Linux native path — maps to last_error
                state["last_error"] = _normalize_error(value)

            elif leaf in ("last-event", "last_event"):
                # SR Linux native path — store for context
                state["last_event"] = str(value).lower() if value else None

            elif leaf in ("received", "received-routes"):
                state["prefixes_received"] = int(value) if value is not None else 0
                if afi_raw:
                    state["address_family"] = _normalize_afi(afi_raw)

            elif leaf in ("sent", "advertised-routes"):
                state["prefixes_advertised"] = int(value) if value is not None else 0

            elif leaf in ("peer-as",):
                state["peer_as"] = str(value) if value else None

            elif leaf in ("route-reflector-client",):
                state["is_rr_client"] = bool(value)

    return peers


# ── Shared dependency detection ───────────────────────────────────────────────

def _detect_shared_dependency(
    peer_states: dict[str, Any],
) -> dict[str, str | None]:
    """
    Detect a shared dependency across non-ESTABLISHED peers on one device.

    Strategy:
    1. If multiple peers share the same last_error, that error is the
       shared signal.
    2. If any peer is flagged as is_rr_client=True and all failing peers
       are RR clients, the shared dependency is likely the route reflector.
    3. Return a dict mapping peer_address → shared_dependency hint.

    This is a heuristic — lattice does the authoritative correlation.
    The hint is passed as root_cause_hint in bgp_snapshot.json.
    """
    result: dict[str, str | None] = {}

    # Collect non-established peers and their errors
    failing = {
        peer: state for peer, state in peer_states.items()
        if state.get("session_state", "idle") != "established"
    }

    if len(failing) < 2:
        # Single failing peer — no shared dependency to detect
        for peer in peer_states:
            result[peer] = None
        return result

    # ── Count shared errors ───────────────────────────────────────────────
    error_counts: dict[str, int] = defaultdict(int)
    for state in failing.values():
        err = state.get("last_error")
        if err:
            error_counts[err] += 1

    dominant_error = max(error_counts, key=error_counts.get) \
        if error_counts else None
    dominant_count = error_counts.get(dominant_error, 0) if dominant_error else 0

    # ── Check if all failing peers are RR clients ─────────────────────────
    all_rr_clients = all(
        state.get("is_rr_client", False) for state in failing.values()
    )

    for peer, state in peer_states.items():
        if peer not in failing:
            result[peer] = None
            continue

        if all_rr_clients and dominant_count >= 2:
            # All failing peers are RR clients with a common error —
            # the shared dependency is the route reflector
            result[peer] = "route-reflector"
        elif dominant_count >= 2:
            # Multiple peers share the same error — common upstream issue
            result[peer] = dominant_error
        else:
            result[peer] = None

    return result


# ── Snapshot assembly ─────────────────────────────────────────────────────────

def build_snapshot(
    peers: dict[str, dict[str, dict[str, Any]]],
    fabric: str,
) -> dict[str, Any]:
    """
    Assemble the bgp_snapshot.json structure from parsed peer state.

    Output format (what nre-agent reads):
    {
      "events": [
        {
          "peer":             "10.0.0.12",
          "session_state":    "idle",
          "last_error":       "tcp_connect_failed",
          "shared_dependency": "route-reflector",
          "address_family":   "ipv4_unicast",
          "root_cause_hint":  "route-reflector",
          "prefixes_received": 0,
          "network_instance": "default",
          "device":           "leaf-01",
          "fabric":           "prod-dc-west",
          "timestamp":        "2026-04-07T14:30:00+00:00",
          "logs":             []
        },
        ...
      ]
    }
    """
    events: list[dict[str, Any]] = []

    for device, ni_map in peers.items():
        for ni, peer_map in ni_map.items():

            # ── Detect shared dependencies within this device/NI ──────────
            shared = _detect_shared_dependency(peer_map)

            for peer, state in peer_map.items():
                session_state    = state.get("session_state", "idle")
                last_error       = state.get("last_error")
                shared_dep       = shared.get(peer)
                prefixes_received = state.get("prefixes_received", 0)
                address_family   = state.get("address_family", "ipv4_unicast")
                timestamp        = state.get("timestamp", _now_iso())

                # ── Derive root_cause_hint ────────────────────────────────
                # This is a heuristic hint for lattice. The authoritative
                # root cause is determined by lattice's BGP analysis engine.
                if shared_dep == "route-reflector":
                    root_cause_hint = "rr-01"  # generic placeholder
                elif session_state == "established" and prefixes_received == 0:
                    root_cause_hint = "peer_not_advertising_or_upstream_issue"
                elif last_error == "tcp_connect_failed":
                    root_cause_hint = shared_dep or "underlay_or_config_issue"
                else:
                    root_cause_hint = shared_dep or last_error or None

                events.append({
                    "peer":              peer,
                    "session_state":     session_state,
                    "last_error":        last_error,
                    "shared_dependency": shared_dep,
                    "address_family":    address_family,
                    "root_cause_hint":   root_cause_hint,
                    "prefixes_received": prefixes_received,
                    "network_instance":  ni,
                    "device":            device,
                    "fabric":            fabric,
                    "timestamp":         timestamp,
                    "logs":              [],
                })

    return {"events": events}


# ── File I/O ──────────────────────────────────────────────────────────────────

def read_gnmic_output(path: Path) -> list[dict[str, Any]]:
    """
    Read gnmic event-format JSON from path.

    gnmic writes one JSON object per line (JSONL) when using event format,
    or a JSON array when using json format. Handle both.
    """
    if not path.exists():
        return []

    try:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return []

        # ── Try JSON array first ──────────────────────────────────────────
        if text.startswith("["):
            return json.loads(text)

        # ── Fall back to JSONL (one object per line) ──────────────────────
        events = []
        for line in text.splitlines():
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return events

    except Exception as exc:
        LOG.error("Failed to read gnmic output from %s: %s", path, exc)
        return []


def write_snapshot(snapshot: dict[str, Any], path: Path) -> None:
    """
    Write bgp_snapshot.json atomically using a temp file and rename.

    Atomic write prevents nre-agent from reading a partial file if the
    writer and reader overlap.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    tmp.replace(path)
    LOG.info(
        "Wrote bgp_snapshot.json — %d events from %d devices",
        len(snapshot.get("events", [])),
        len({e["device"] for e in snapshot.get("events", [])}),
    )


# ── Main loop ─────────────────────────────────────────────────────────────────

def run() -> None:
    """
    Main loop. Polls gnmic_bgp.json and rewrites bgp_snapshot.json
    whenever the input changes or the poll interval elapses.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    gnmic_file    = _gnmic_output_file()
    snapshot_file = _snapshot_output_file()
    fabric        = _fabric_name()
    interval      = _poll_interval()

    LOG.info(
        "capsule bgp-snapshot-writer starting — "
        "input=%s output=%s interval=%ds fabric=%s",
        gnmic_file, snapshot_file, interval, fabric,
    )

    last_mtime: float = 0.0

    while True:
        try:
            # ── Only reprocess if the input file changed ───────────────────
            current_mtime = gnmic_file.stat().st_mtime \
                if gnmic_file.exists() else 0.0

            if current_mtime != last_mtime:
                last_mtime = current_mtime

                raw    = read_gnmic_output(gnmic_file)
                peers  = parse_gnmic_events(raw)
                snap   = build_snapshot(peers, fabric)

                write_snapshot(snap, snapshot_file)

            else:
                LOG.debug("gnmic output unchanged — skipping")

        except Exception as exc:
            LOG.error("snapshot_writer error: %s", exc)

        time.sleep(interval)


if __name__ == "__main__":
    run()
