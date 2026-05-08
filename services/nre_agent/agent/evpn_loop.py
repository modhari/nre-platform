"""
evpn_loop.py — EVPN diagnostics iteration for nre-agent.

Reads /data/evpn_snapshot.json (written by capsule evpn-snapshot-writer),
loads the EVPN scenario registry, and calls evpn.analyze via mcp-server
for each active anomaly detected across all devices.

The scenario registry lives at:
  services/lattice/internal/knowledge/domains/evpn_vxlan/registry/scenarios.yaml

Adding a new EVPN scenario requires:
  1. Add an entry to scenarios.yaml
  2. Add the corresponding anomaly detection logic to evpn_snapshot_writer.py
  3. Add simulation in gnmi_simulator/simulator.py
  No changes to this file needed.

Environment variables:
  NRE_AGENT_EVPN_SNAPSHOT_FILE   default: /data/evpn_snapshot.json
  NRE_AGENT_EVPN_SCENARIO_REGISTRY  default: (bundled registry path)
  NRE_AGENT_EVPN_FABRIC          default: prod-dc-west
  NRE_AGENT_EVPN_VENDOR          default: arista
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

LOG = logging.getLogger(__name__)


# ── Config ────────────────────────────────────────────────────────────────────

def _evpn_snapshot_file() -> Path:
    return Path(os.getenv(
        "NRE_AGENT_EVPN_SNAPSHOT_FILE", "/data/evpn_snapshot.json"
    ))


def _evpn_registry_path() -> Path:
    # Default: relative to this file's location so it works in dev and in container
    default = Path(__file__).parent / "evpn_scenarios.yaml"
    return Path(os.getenv("NRE_AGENT_EVPN_SCENARIO_REGISTRY", str(default)))


def _fabric() -> str:
    return os.getenv("NRE_AGENT_EVPN_FABRIC", "prod-dc-west")


def _default_vendor() -> str:
    return os.getenv("NRE_AGENT_EVPN_VENDOR", "arista")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Scenario registry ─────────────────────────────────────────────────────────

def load_scenario_registry(path: Path) -> list[dict[str, Any]]:
    """
    Load EVPN scenario registry from YAML.

    Returns list of scenario dicts keyed by trigger type for fast lookup.
    Falls back to empty list if file is missing — agent proceeds without
    EVPN diagnostics rather than crashing.
    """
    if not path.exists():
        LOG.warning(
            "EVPN scenario registry not found at %s — "
            "EVPN diagnostics disabled",
            path,
        )
        return []

    try:
        with path.open("r", encoding="utf-8") as fh:
            registry = yaml.safe_load(fh) or []
        LOG.info(
            "loaded EVPN scenario registry — %d scenarios from %s",
            len(registry), path,
        )
        return registry
    except Exception as exc:
        LOG.error("failed to load EVPN scenario registry: %s", exc)
        return []


def registry_by_trigger(
    registry: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Index registry by trigger type for O(1) lookup."""
    return {entry["trigger"]: entry for entry in registry if "trigger" in entry}


# ── Snapshot loading ──────────────────────────────────────────────────────────

def load_evpn_snapshot(path: Path) -> dict[str, Any]:
    """
    Load evpn_snapshot.json from disk.

    Returns empty snapshot gracefully when file is missing — the EVPN
    loop started before capsule wrote its first snapshot.
    """
    if not path.exists():
        LOG.debug("evpn_snapshot.json not yet available at %s", path)
        return {"devices": []}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("evpn snapshot must be a JSON object")
        return data
    except Exception as exc:
        LOG.error("failed to load evpn snapshot from %s: %s", path, exc)
        return {"devices": []}


# ── Question template rendering ───────────────────────────────────────────────

def render_question(
    template: str,
    anomaly:  dict[str, Any],
    device:   str,
    fabric:   str,
) -> str:
    """
    Render the question template from the registry using anomaly fields.

    All {field} placeholders are replaced with values from the anomaly dict,
    device, and fabric. Missing fields are replaced with 'unknown'.
    """
    context = {
        "device": device,
        "fabric": fabric,
        **{k: str(v) if v is not None else "unknown" for k, v in anomaly.items()},
    }
    try:
        return template.format_map(
            {k: context.get(k, "unknown") for k in _extract_placeholders(template)}
        )
    except (KeyError, ValueError):
        # Fallback — return template with best-effort substitution
        result = template
        for key, value in context.items():
            result = result.replace(f"{{{key}}}", str(value))
        return result


def _extract_placeholders(template: str) -> list[str]:
    """Extract {field} placeholder names from a template string."""
    import re
    return re.findall(r'\{(\w+)\}', template)


# ── Main iteration ────────────────────────────────────────────────────────────


# ── Multi-device EVPN correlation ─────────────────────────────────────────────

def correlate_evpn_anomalies(
    devices: list[dict[str, Any]],
    registry: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Group anomalies sharing the same type across 2+ devices into
    fabric-wide correlated incidents.

    Returns:
      correlated: list of fabric-wide incident dicts
      standalone: list of single-device anomaly dicts
    """
    from collections import defaultdict

    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for device_state in devices:
        device = device_state.get("device", "unknown")
        for anomaly in device_state.get("anomalies", []):
            anomaly_type = anomaly.get("type")
            if not anomaly_type:
                continue
            by_type[anomaly_type].append({
                "device":  device,
                "anomaly": anomaly,
            })

    correlated: list[dict[str, Any]] = []
    standalone: list[dict[str, Any]] = []

    for anomaly_type, entries in by_type.items():
        if len(entries) >= 2:
            affected_devices = [e["device"] for e in entries]
            rep_anomaly      = entries[0]["anomaly"]
            correlated.append({
                "anomaly_type":     anomaly_type,
                "affected_devices": affected_devices,
                "device_count":     len(affected_devices),
                "rep_anomaly":      rep_anomaly,
                "all_entries":      entries,
            })
        else:
            standalone.append({
                "device":  entries[0]["device"],
                "anomaly": entries[0]["anomaly"],
            })

    return correlated, standalone

def run_evpn_diagnostics_iteration(
    registry:   list[dict[str, Any]],
    publish_fn: Any,
) -> None:
    """
    Execute one EVPN diagnostics cycle with multi-device correlation.

    For anomalies appearing on 2+ devices simultaneously, a single
    fabric-wide incident is created. Single-device anomalies are handled
    independently as before.
    """
    from agent.client import call_mcp_evpn_analyze

    snapshot_file  = _evpn_snapshot_file()
    fabric         = _fabric()
    default_vendor = _default_vendor()

    snapshot = load_evpn_snapshot(snapshot_file)
    devices  = snapshot.get("devices", [])

    if not devices:
        LOG.debug("evpn snapshot has no devices — skipping iteration")
        return

    trigger_map     = registry_by_trigger(registry)
    total_anomalies = sum(len(d.get("anomalies", [])) for d in devices)

    LOG.info(
        "[evpn_loop] snapshot loaded — %d devices, %d total anomalies",
        len(devices), total_anomalies,
    )

    if not total_anomalies:
        return

    # ── Correlate anomalies across devices ────────────────────────────────────
    correlated, standalone = correlate_evpn_anomalies(devices, registry)

    if correlated:
        LOG.info(
            "[evpn_loop] correlation — %d fabric-wide incidents, %d standalone",
            len(correlated), len(standalone),
        )

    # ── Handle correlated (fabric-wide) incidents ─────────────────────────────
    for group in correlated:
        anomaly_type     = group["anomaly_type"]
        affected_devices = group["affected_devices"]
        rep_anomaly      = group["rep_anomaly"]
        device_count     = group["device_count"]

        scenario_def = trigger_map.get(anomaly_type)
        if not scenario_def:
            LOG.warning(
                "[evpn_loop] no scenario for correlated anomaly_type=%s",
                anomaly_type,
            )
            continue

        required = scenario_def.get("required", [])
        missing  = [f for f in required if not rep_anomaly.get(f)]
        if missing:
            LOG.warning(
                "[evpn_loop] correlated anomaly_type=%s missing fields %s",
                anomaly_type, missing,
            )
            continue

        scenario   = scenario_def["scenario"]
        capability = scenario_def.get("capability", "bgp_evpn_peer_state")
        risk_class = scenario_def.get("risk_class", "medium")
        ts         = _utc_now_iso()

        # Fabric-wide incident_id covers all affected devices
        incident_id = (
            f"evpn:{fabric}:fabric_wide:{anomaly_type}"
            f":{rep_anomaly.get('vni') or rep_anomaly.get('esi') or 'unknown'}"
        )

        # Build a question that names all affected devices
        device_list = ", ".join(affected_devices)
        question = render_question(
            template=scenario_def.get("question", "EVPN fault detected"),
            anomaly=rep_anomaly,
            device=f"{device_list} ({device_count} devices)",
            fabric=fabric,
        )

        LOG.info(
            "[evpn_loop] fabric_wide incident anomaly_type=%s "
            "devices=%s scenario=%s risk=%s incident_id=%s",
            anomaly_type, affected_devices, scenario, risk_class, incident_id,
        )

        print(
            f"[nre_agent] evpn_correlated_incident"
            f" incident_id={incident_id}"
            f" scenario={scenario}"
            f" affected_devices={affected_devices}"
            f" device_count={device_count}"
            f" risk={risk_class}",
            flush=True,
        )

        try:
            evpn_result = call_mcp_evpn_analyze(
                question=question,
                vendor=default_vendor,
                nos_family="eos",
                scenario=scenario,
                capability=capability,
                device=affected_devices[0],  # primary device for capability lookup
                fabric=fabric,
                vni=rep_anomaly.get("vni"),
                mac=rep_anomaly.get("mac"),
                incident_id=incident_id,
                timestamp_utc=ts,
            )
        except Exception as exc:
            LOG.error(
                "[evpn_loop] evpn.analyze failed for correlated %s: %s",
                incident_id, exc,
            )
            continue

        reasoning     = evpn_result.get("reasoning", {})
        governed_plan = evpn_result.get("governed_plan", {})
        mcp_plan      = evpn_result.get("mcp_plan", {})

        safe_actions  = len(governed_plan.get("allowed_tools", []))
        gated_actions = len(governed_plan.get("downgraded_tools", [])) + \
                        len(governed_plan.get("blocked_tools", []))
        approval_req  = governed_plan.get("requires_approval", False)
        confidence    = mcp_plan.get("confidence", "unknown")

        print(
            f"[nre_agent] evpn_correlated_incident"
            f" incident_id={incident_id}"
            f" scenario={scenario}"
            f" risk={risk_class}"
            f" confidence={confidence}"
            f" safe_actions={safe_actions}"
            f" gated_actions={gated_actions}"
            f" approval_required={approval_req}"
            f" devices={affected_devices}",
            flush=True,
        )

        # Publish fabric-wide incident
        incident_payload = {
            "event_type":          "evpn_correlated_incident_snapshot",
            "event_version":       "v1",
            "ts":                  ts,
            "incident_id":         incident_id,
            "fabric":              fabric,
            "affected_devices":    affected_devices,
            "device_count":        device_count,
            "scenario":            scenario,
            "anomaly_type":        anomaly_type,
            "vendor":              default_vendor,
            "risk_class":          risk_class,
            "confidence":          confidence,
            "approval_required":   approval_req,
            "safe_action_count":   safe_actions,
            "gated_action_count":  gated_actions,
            "findings":            reasoning.get("findings", []),
            "likely_causes":       reasoning.get("likely_causes", []),
            "payload":             evpn_result,
        }

        publish_fn(
            topic="nre.evpn_incidents",
            key=incident_id,
            payload=incident_payload,
        )
        publish_fn(
            topic="nre.evpn_plans",
            key=incident_id,
            payload={
                "event_type":        "evpn_correlated_plan_snapshot",
                "event_version":     "v1",
                "ts":                ts,
                "incident_id":       incident_id,
                "fabric":            fabric,
                "affected_devices":  affected_devices,
                "device_count":      device_count,
                "scenario":          scenario,
                "risk_class":        risk_class,
                "approval_required": approval_req,
                "safe_step_count":   safe_actions,
                "gated_step_count":  gated_actions,
                "payload":           evpn_result,
            },
        )

        print(
            f"[nre_agent] ts={ts} evpn_correlated_incident_id={incident_id}"
            f" published to kafka",
            flush=True,
        )

    # ── Handle standalone (single-device) incidents ───────────────────────────
    for item in standalone:
        device  = item["device"]
        anomaly = item["anomaly"]

        anomaly_type = anomaly.get("type")
        scenario_def = trigger_map.get(anomaly_type)
        if not scenario_def:
            continue

        required = scenario_def.get("required", [])
        missing  = [f for f in required if not anomaly.get(f)]
        if missing:
            continue

        scenario   = scenario_def["scenario"]
        capability = scenario_def.get("capability", "bgp_evpn_peer_state")
        risk_class = scenario_def.get("risk_class", "medium")
        ts         = _utc_now_iso()
        incident_id = (
            f"evpn:{fabric}:{device}:{anomaly_type}"
            f":{anomaly.get('vni') or anomaly.get('esi') or anomaly.get('mac', 'unknown')}"
        )

        question = render_question(
            template=scenario_def.get("question", "EVPN fault detected"),
            anomaly=anomaly,
            device=device,
            fabric=fabric,
        )

        LOG.info(
            "[evpn_loop] standalone incident device=%s scenario=%s "
            "risk=%s incident_id=%s",
            device, scenario, risk_class, incident_id,
        )

        try:
            evpn_result = call_mcp_evpn_analyze(
                question=question,
                vendor=default_vendor,
                nos_family="eos",
                scenario=scenario,
                capability=capability,
                device=device,
                fabric=fabric,
                vni=anomaly.get("vni"),
                mac=anomaly.get("mac"),
                incident_id=incident_id,
                timestamp_utc=ts,
            )
        except Exception as exc:
            LOG.error(
                "[evpn_loop] evpn.analyze failed for %s: %s",
                incident_id, exc,
            )
            continue

        reasoning     = evpn_result.get("reasoning", {})
        governed_plan = evpn_result.get("governed_plan", {})
        mcp_plan      = evpn_result.get("mcp_plan", {})

        safe_actions  = len(governed_plan.get("allowed_tools", []))
        gated_actions = len(governed_plan.get("downgraded_tools", [])) + \
                        len(governed_plan.get("blocked_tools", []))
        approval_req  = governed_plan.get("requires_approval", False)
        confidence    = mcp_plan.get("confidence", "unknown")

        print(
            f"[nre_agent] evpn_incident"
            f" incident_id={incident_id}"
            f" scenario={scenario}"
            f" risk={risk_class}"
            f" confidence={confidence}"
            f" safe_actions={safe_actions}"
            f" gated_actions={gated_actions}"
            f" approval_required={approval_req}",
            flush=True,
        )
        print(
            f"[nre_agent] ts={ts}"
            f" evpn_incident_id={incident_id}"
            f" published to kafka",
            flush=True,
        )

        incident_payload = {
            "event_type":          "evpn_incident_snapshot",
            "event_version":       "v1",
            "ts":                  ts,
            "incident_id":         incident_id,
            "fabric":              fabric,
            "device":              device,
            "scenario":            scenario,
            "anomaly_type":        anomaly_type,
            "vendor":              default_vendor,
            "risk_class":          risk_class,
            "confidence":          confidence,
            "approval_required":   approval_req,
            "safe_action_count":   safe_actions,
            "gated_action_count":  gated_actions,
            "findings":            reasoning.get("findings", []),
            "likely_causes":       reasoning.get("likely_causes", []),
            "payload":             evpn_result,
        }

        publish_fn(
            topic="nre.evpn_incidents",
            key=incident_id,
            payload=incident_payload,
        )
        publish_fn(
            topic="nre.evpn_plans",
            key=incident_id,
            payload={
                "event_type":        "evpn_plan_snapshot",
                "event_version":     "v1",
                "ts":                ts,
                "incident_id":       incident_id,
                "plan_id":           f"evpn_plan:{incident_id}",
                "fabric":            fabric,
                "device":            device,
                "scenario":          scenario,
                "risk_class":        risk_class,
                "approval_required": approval_req,
                "safe_step_count":   safe_actions,
                "gated_step_count":  gated_actions,
                "payload":           evpn_result,
            },
        )
