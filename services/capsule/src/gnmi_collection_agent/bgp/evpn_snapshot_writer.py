"""
evpn_snapshot_writer.py — Translate gnmic EVPN telemetry into evpn_snapshot.json.

This is the EVPN equivalent of bgp/snapshot_writer.py.

Input:  /data/gnmic_evpn.json  — gnmic event-format JSON written by the
                                  gnmi-simulator (or real gnmic in production)
Output: /data/evpn_snapshot.json — structured EVPN state consumed by nre-agent

Translation contract:
  gnmic path / leaf                     → evpn_snapshot field
  ─────────────────────────────────────────────────────────────────
  vxlan_vni_oper_state                  → vni_table[].state
  vxlan_vtep_peer_state                 → vtep_table[].reachable
  evpn_mac_mobility_seq                 → mac_table[].mobility_count
  evpn_mac_peer_vtep                    → mac_table[].vtep
  evpn_routes_type3_imet                → evpn_routes.type3_count
  bgp_evpn_prefixes_received            → evpn_routes.type5_count (spike detection)
  evpn_esi_active_links                 → esi_table[].active_links
  evpn_esi_df_state                     → esi_table[].designated_forwarder

Anomaly detection:
  vtep_unreachable      — VTEP in peer table but zero type-3 routes
  mac_mobility_storm    — MAC mobility_count > MAC_MOBILITY_THRESHOLD
  vni_state_down        — VNI oper_state != up
  type5_leaking         — type-5 route count spike above baseline
  esi_split_brain       — active_links < expected_links

Environment variables:
  GNMIC_EVPN_OUTPUT_FILE       default: /data/gnmic_evpn.json
  EVPN_SNAPSHOT_OUTPUT_FILE    default: /data/evpn_snapshot.json
  POLL_INTERVAL_SECONDS        default: 30
  FABRIC_NAME                  default: prod-dc-west
  MAC_MOBILITY_THRESHOLD       default: 5
  TYPE5_SPIKE_THRESHOLD        default: 50
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


# ── Config ────────────────────────────────────────────────────────────────────

def _evpn_input_file() -> Path:
    return Path(os.getenv("GNMIC_EVPN_OUTPUT_FILE", "/data/gnmic_evpn.json"))

def _snapshot_output_file() -> Path:
    return Path(os.getenv("EVPN_SNAPSHOT_OUTPUT_FILE", "/data/evpn_snapshot.json"))

def _poll_interval() -> int:
    return int(os.getenv("POLL_INTERVAL_SECONDS", "30"))

def _fabric_name() -> str:
    return os.getenv("FABRIC_NAME", "prod-dc-west")

def _mac_mobility_threshold() -> int:
    return int(os.getenv("MAC_MOBILITY_THRESHOLD", "5"))

def _type5_spike_threshold() -> int:
    return int(os.getenv("TYPE5_SPIKE_THRESHOLD", "50"))


# ── Path parsing ──────────────────────────────────────────────────────────────

_KEY_RE = re.compile(r'\[([^=\]]+)=([^\]]+)\]')


def _extract_keys(path: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for m in _KEY_RE.finditer(path)}


def _path_leaf(path: str) -> str:
    segment = path.rstrip("/").split("/")[-1]
    return _KEY_RE.sub("", segment).strip("-")


def _strip_port(source: str) -> str:
    return source.rsplit(":", 1)[0] if ":" in source else source


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── gnmic event parsing ───────────────────────────────────────────────────────

def parse_evpn_events(
    raw: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Parse gnmic EVPN event-format JSON into structured per-device state.

    Returns a dict keyed by device name containing:
      vni_table     — per-VNI operational state
      vtep_table    — per-VTEP reachability state
      mac_table     — per-MAC mobility and VTEP binding
      evpn_routes   — route type counts
      esi_table     — per-ESI multihoming state
    """
    # State containers keyed by device
    vni_table:    dict[str, dict[str, Any]] = defaultdict(dict)
    vtep_table:   dict[str, dict[str, Any]] = defaultdict(dict)
    mac_table:    dict[str, dict[str, Any]] = defaultdict(dict)
    evpn_routes:  dict[str, dict[str, Any]] = defaultdict(
        lambda: {"type2_count": 0, "type3_count": 0, "type5_count": 0,
                 "missing_type3_vteps": [], "type5_leaking": False}
    )
    esi_table:    dict[str, dict[str, Any]] = defaultdict(dict)
    timestamps:   dict[str, str] = {}

    for event in raw:
        if not isinstance(event, dict):
            continue

        source    = event.get("source", "unknown")
        device    = _strip_port(source)
        timestamp = event.get("time") or _now_iso()
        tags      = event.get("tags", {}) or {}
        values    = event.get("values", {}) or {}

        if device not in timestamps:
            timestamps[device] = timestamp

        ni = (tags.get("network-instance_name")
              or tags.get("network_instance_name")
              or "default")

        # ── Extract identifiers from tags ──────────────────────────────────
        vlan_id  = (tags.get("vlan_vlan-id")
                    or tags.get("vlan-id"))
        peer_ip  = (tags.get("endpoint_peer-ip")
                    or tags.get("peer-ip")
                    or tags.get("vtep"))
        mac_addr = (tags.get("entry_mac-address")
                    or tags.get("mac-address")
                    or tags.get("mac"))
        esi_id   = (tags.get("ethernet-segment_esi")
                    or tags.get("esi"))

        # ── Process each value in the event ───────────────────────────────
        for path_key, value in values.items():
            leaf = _path_leaf(path_key)
            keys = _extract_keys(path_key)

            # ── VNI state ──────────────────────────────────────────────────
            if leaf in ("vni", "oper-state", "admin-state") and "endpoint" not in path_key:
                vni_key = vlan_id or keys.get("vlan-id", "unknown")
                if vni_key not in vni_table[device]:
                    vni_table[device][vni_key] = {
                        "vni":         None,
                        "vlan":        vni_key,
                        "state":       "unknown",
                        "admin_state": "unknown",
                        "vteps":       [],
                        "network_instance": ni,
                    }
                if leaf == "vni":
                    vni_table[device][vni_key]["vni"] = int(value) if value else None
                elif leaf == "oper-state":
                    vni_table[device][vni_key]["state"] = str(value).lower() if value else "unknown"
                elif leaf == "admin-state":
                    vni_table[device][vni_key]["admin_state"] = str(value).lower() if value else "unknown"

            # ── VTEP peer reachability ─────────────────────────────────────
            elif leaf in ("peer-ip",):
                vtep_key = peer_ip or keys.get("peer-ip") or str(value)
                if vtep_key and vtep_key not in vtep_table[device]:
                    vtep_table[device][vtep_key] = {
                        "vtep_ip":    vtep_key,
                        "reachable":  True,
                        "vnis":       [],
                        "last_seen":  timestamp,
                        "network_instance": ni,
                    }
                # Add VNI to VTEP entry
                vni_val = keys.get("vni") or tags.get("vni")
                if vni_val and vtep_key in vtep_table[device]:
                    vnis = vtep_table[device][vtep_key]["vnis"]
                    try:
                        vni_int = int(vni_val)
                        if vni_int not in vnis:
                            vnis.append(vni_int)
                    except (ValueError, TypeError):
                        pass

            # ── VTEP VNI association ──────────────────────────────────────
            # Separate event: .../endpoint[peer-ip=X]/state/vni = VNI_ID
            # Associates a VNI with its VTEP entry.
            elif leaf == "vni" and "endpoint" in path_key:
                vtep_key = (peer_ip
                            or tags.get("endpoint_peer-ip")
                            or keys.get("peer-ip"))
                if vtep_key:
                    if vtep_key not in vtep_table[device]:
                        vtep_table[device][vtep_key] = {
                            "vtep_ip":          vtep_key,
                            "reachable":        True,
                            "vnis":             [],
                            "last_seen":        timestamp,
                            "network_instance": ni,
                        }
                    try:
                        vni_int = int(value) if value is not None else None
                        if vni_int is not None:
                            vnis = vtep_table[device][vtep_key]["vnis"]
                            if vni_int not in vnis:
                                vnis.append(vni_int)
                    except (ValueError, TypeError):
                        pass

            # ── MAC table and mobility ─────────────────────────────────────
            elif leaf in ("mobility-seq-no", "mobility_seq_no",
                          "mobility-count", "peer-vtep",
                          "mac-duplication-detected", "detected-time"):
                mac_key = mac_addr or keys.get("mac-address", "unknown")
                vni_val = (tags.get("vni")
                           or keys.get("vlan")
                           or keys.get("vlan-id"))

                if mac_key not in mac_table[device]:
                    mac_table[device][mac_key] = {
                        "mac":             mac_key,
                        "vni":             None,
                        "vtep":            None,
                        "mobility_count":  0,
                        "is_local":        False,
                        "seq_number":      0,
                        "dup_detected":    False,
                        "network_instance": ni,
                    }

                entry = mac_table[device][mac_key]

                if vni_val:
                    try:
                        entry["vni"] = int(vni_val)
                    except (ValueError, TypeError):
                        pass

                if leaf in ("mobility-seq-no", "mobility_seq_no"):
                    try:
                        seq = int(value) if value is not None else 0
                        entry["mobility_count"] = seq
                        entry["seq_number"]     = seq
                    except (ValueError, TypeError):
                        pass

                elif leaf == "peer-vtep":
                    entry["vtep"] = str(value) if value else None
                    entry["is_local"] = False

                elif leaf in ("mac-duplication-detected", "detected-time"):
                    entry["dup_detected"] = bool(value)

            # ── EVPN route counts ──────────────────────────────────────────
            elif leaf in ("attr-index", "route-type"):
                # type-3 IMET route presence detected by attr-index path
                if "inclusive-multicast" in path_key or "type3" in path_key.lower():
                    evpn_routes[device]["type3_count"] += 1
                elif "route-type" in leaf:
                    route_type = str(value).lower() if value else ""
                    if "2" in route_type or "mac" in route_type:
                        evpn_routes[device]["type2_count"] += 1
                    elif "5" in route_type or "prefix" in route_type:
                        evpn_routes[device]["type5_count"] += 1

            # ── ESI multihoming ────────────────────────────────────────────
            elif leaf in ("esi",):
                esi_key = esi_id or keys.get("esi") or str(value)
                if esi_key not in esi_table[device]:
                    esi_table[device][esi_key] = {
                        "esi":                  esi_key,
                        "active_links":         0,
                        "expected_links":       2,
                        "designated_forwarder": None,
                        "split_brain":          False,
                        "network_instance":     ni,
                    }

            elif leaf in ("oper-designated-forwarder", "designated-forwarder"):
                esi_key = esi_id or keys.get("esi", "unknown")
                if esi_key in esi_table[device]:
                    esi_table[device][esi_key]["designated_forwarder"] = (
                        str(value) if value else None
                    )

            elif leaf in ("active-links", "active_links"):
                esi_key = esi_id or keys.get("esi", "unknown")
                if esi_key in esi_table[device]:
                    try:
                        links = int(value) if value is not None else 0
                        esi_table[device][esi_key]["active_links"]  = links
                        esi_table[device][esi_key]["split_brain"]   = links < 2
                    except (ValueError, TypeError):
                        pass

            # ── SR Linux native EVPN paths ─────────────────────────────────
            elif leaf in ("active-entries",):
                # SR Linux bridge table active entries — maps to VNI state
                vni_iface = (tags.get("vxlan-interface_name")
                             or keys.get("name", "unknown"))
                if vni_iface not in vni_table[device]:
                    vni_table[device][vni_iface] = {
                        "vni":         None,
                        "vlan":        vni_iface,
                        "state":       "up" if int(value or 0) >= 0 else "unknown",
                        "admin_state": "unknown",
                        "vteps":       [],
                        "network_instance": ni,
                    }

    return {
        "vni_table":   vni_table,
        "vtep_table":  vtep_table,
        "mac_table":   mac_table,
        "evpn_routes": evpn_routes,
        "esi_table":   esi_table,
        "timestamps":  timestamps,
    }


# ── Anomaly detection ─────────────────────────────────────────────────────────

def detect_anomalies(
    device: str,
    parsed: dict[str, Any],
    mac_mobility_threshold: int,
    type5_spike_threshold: int,
) -> list[dict[str, Any]]:
    """
    Detect EVPN anomalies from parsed device state.

    Returns a list of anomaly dicts — each one maps to a scenario in
    the EVPN scenario registry and becomes an evpn.analyze call in
    the nre-agent loop.

    Anomaly types:
      vtep_unreachable      vtep_ip, vni
      mac_mobility_storm    mac, vni, mobility_count
      vni_state_down        vni, vlan
      type5_leaking         device (no additional fields)
      esi_split_brain       esi, active_links, expected_links
    """
    anomalies: list[dict[str, Any]] = []

    vni_table   = parsed["vni_table"].get(device, {})
    vtep_table  = parsed["vtep_table"].get(device, {})
    mac_table   = parsed["mac_table"].get(device, {})
    evpn_routes = parsed["evpn_routes"].get(device, {})
    esi_table   = parsed["esi_table"].get(device, {})

    # ── vtep_unreachable ─────────────────────────────────────────────────────
    # A VTEP is unreachable when:
    #   (a) it appears in the peer table but has reachable=False, OR
    #   (b) the type-3 IMET route count is less than the number of known
    #       VTEPs — meaning some VTEPs have withdrawn their IMET route.
    type3_count  = evpn_routes.get("type3_count", 0)
    vtep_count   = len(vtep_table)

    for vtep_ip, vtep_state in vtep_table.items():
        if not vtep_state.get("reachable", True):
            for vni in vtep_state.get("vnis", [None]):
                anomalies.append({
                    "type":    "vtep_unreachable",
                    "vtep_ip": vtep_ip,
                    "vni":     vni,
                    "detail":  "vtep marked unreachable in peer table",
                })

    # Check per-VNI VTEP coverage using VNI table.
    # Only flag vtep_unreachable when:
    #   - the VNI is operationally up (session healthy, routes gone)
    #   - AND the device has at least one other VNI with remote VTEPs
    #     (confirming the VTEP table is being populated normally)
    #   - AND this specific VNI has zero remote VTEPs
    # This avoids false positives when ALL VNIs have no VTEPs (healthy
    # scenario or first poll before VTEP table is populated).
    vnis_with_vteps = set()
    for vtep_ip, vtep_state in vtep_table.items():
        for vni_id in vtep_state.get("vnis", []):
            vnis_with_vteps.add(vni_id)

    for vlan_key, vni_state in vni_table.items():
        vni_id = vni_state.get("vni")
        if not vni_id:
            continue
        vteps_for_vni = [
            vtep_ip for vtep_ip, vtep_state in vtep_table.items()
            if vni_id in vtep_state.get("vnis", [])
        ]
        other_vnis_have_vteps = bool(vnis_with_vteps - {vni_id})
        if (len(vteps_for_vni) == 0
                and vni_state.get("state", "unknown") == "up"
                and other_vnis_have_vteps):
            anomalies.append({
                "type":    "vtep_unreachable",
                "vtep_ip": "all",
                "vni":     vni_id,
                "detail":  "no remote VTEPs advertising type-3 IMET route for this VNI",
            })

    # ── mac_mobility_storm ───────────────────────────────────────────────────
    # MAC mobility counter above threshold indicates flapping MAC.
    for mac_addr, mac_state in mac_table.items():
        if mac_state.get("mobility_count", 0) >= mac_mobility_threshold:
            anomalies.append({
                "type":           "mac_mobility_storm",
                "mac":            mac_addr,
                "vni":            mac_state.get("vni"),
                "mobility_count": mac_state.get("mobility_count", 0),
                "vtep":           mac_state.get("vtep"),
                "dup_detected":   mac_state.get("dup_detected", False),
            })

    # ── vni_state_down ───────────────────────────────────────────────────────
    # VNI operational state is not up — possible VLAN-VNI mismatch or
    # missing NVE configuration.
    for vlan_key, vni_state in vni_table.items():
        state = vni_state.get("state", "unknown")
        if state not in ("up", "active", "unknown"):
            anomalies.append({
                "type":  "vni_state_down",
                "vni":   vni_state.get("vni"),
                "vlan":  vlan_key,
                "state": state,
            })

    # ── type5_leaking ────────────────────────────────────────────────────────
    # Type-5 route count spike above threshold indicates prefix leaking
    # from a VRF into the EVPN fabric.
    type5_count = evpn_routes.get("type5_count", 0)
    if type5_count >= type5_spike_threshold:
        anomalies.append({
            "type":        "type5_leaking",
            "type5_count": type5_count,
            "detail":      f"type-5 route count {type5_count} exceeds threshold {type5_spike_threshold}",
        })

    # ── esi_split_brain ──────────────────────────────────────────────────────
    # ESI active links below expected — designated forwarder election
    # may be broken or a physical link is down.
    for esi_id, esi_state in esi_table.items():
        if esi_state.get("split_brain", False):
            anomalies.append({
                "type":                 "esi_split_brain",
                "esi":                  esi_id,
                "active_links":         esi_state.get("active_links", 0),
                "expected_links":       esi_state.get("expected_links", 2),
                "designated_forwarder": esi_state.get("designated_forwarder"),
            })

    return anomalies


# ── Snapshot assembly ─────────────────────────────────────────────────────────

def build_evpn_snapshot(
    parsed:  dict[str, Any],
    fabric:  str,
    mac_mobility_threshold: int,
    type5_spike_threshold:  int,
) -> dict[str, Any]:
    """
    Assemble the evpn_snapshot.json structure from parsed EVPN state.

    Output format (what nre-agent reads):
    {
      "fabric":    "prod-dc-west",
      "timestamp": "2026-04-09T...",
      "devices": [
        {
          "device":      "leaf-01",
          "vendor":      "arista",
          "timestamp":   "...",
          "vtep_table":  [...],
          "vni_table":   [...],
          "mac_table":   [...],
          "evpn_routes": {...},
          "esi_table":   [...],
          "anomalies":   [...]
        }
      ]
    }
    """
    vni_table   = parsed["vni_table"]
    vtep_table  = parsed["vtep_table"]
    mac_table   = parsed["mac_table"]
    evpn_routes = parsed["evpn_routes"]
    esi_table   = parsed["esi_table"]
    timestamps  = parsed["timestamps"]

    all_devices = set(vni_table) | set(vtep_table) | set(mac_table) | set(esi_table)
    devices: list[dict[str, Any]] = []

    for device in sorted(all_devices):
        anomalies = detect_anomalies(
            device=device,
            parsed=parsed,
            mac_mobility_threshold=mac_mobility_threshold,
            type5_spike_threshold=type5_spike_threshold,
        )

        devices.append({
            "device":    device,
            "timestamp": timestamps.get(device, _now_iso()),

            "vtep_table": list(vtep_table.get(device, {}).values()),

            "vni_table": list(vni_table.get(device, {}).values()),

            "mac_table": list(mac_table.get(device, {}).values()),

            "evpn_routes": evpn_routes.get(device, {
                "type2_count": 0,
                "type3_count": 0,
                "type5_count": 0,
                "missing_type3_vteps": [],
                "type5_leaking": False,
            }),

            "esi_table": list(esi_table.get(device, {}).values()),

            "anomalies": anomalies,
        })

    return {
        "fabric":    fabric,
        "timestamp": _now_iso(),
        "devices":   devices,
    }


# ── File I/O ──────────────────────────────────────────────────────────────────

def read_gnmic_evpn_output(path: Path) -> list[dict[str, Any]]:
    """Read gnmic EVPN event-format JSON — handles both array and JSONL."""
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return []
        if text.startswith("["):
            return json.loads(text)
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
        LOG.error("Failed to read gnmic EVPN output from %s: %s", path, exc)
        return []


def write_evpn_snapshot(snapshot: dict[str, Any], path: Path) -> None:
    """Write evpn_snapshot.json atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    tmp.replace(path)

    device_count   = len(snapshot.get("devices", []))
    anomaly_count  = sum(
        len(d.get("anomalies", []))
        for d in snapshot.get("devices", [])
    )
    LOG.info(
        "Wrote evpn_snapshot.json — %d devices, %d anomalies",
        device_count, anomaly_count,
    )


# ── Main loop ─────────────────────────────────────────────────────────────────

def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    evpn_file    = _evpn_input_file()
    snapshot_file = _snapshot_output_file()
    fabric        = _fabric_name()
    interval      = _poll_interval()
    mac_threshold = _mac_mobility_threshold()
    type5_threshold = _type5_spike_threshold()

    LOG.info(
        "capsule evpn-snapshot-writer starting — "
        "input=%s output=%s interval=%ds fabric=%s",
        evpn_file, snapshot_file, interval, fabric,
    )

    last_mtime: float = 0.0

    while True:
        try:
            current_mtime = evpn_file.stat().st_mtime \
                if evpn_file.exists() else 0.0

            if current_mtime != last_mtime:
                last_mtime = current_mtime

                raw     = read_gnmic_evpn_output(evpn_file)
                parsed  = parse_evpn_events(raw)
                snap    = build_evpn_snapshot(
                    parsed=parsed,
                    fabric=fabric,
                    mac_mobility_threshold=mac_threshold,
                    type5_spike_threshold=type5_threshold,
                )
                write_evpn_snapshot(snap, snapshot_file)
            else:
                LOG.debug("gnmic EVPN output unchanged — skipping")

        except Exception as exc:
            LOG.error("evpn_snapshot_writer error: %s", exc)

        time.sleep(interval)


if __name__ == "__main__":
    run()
