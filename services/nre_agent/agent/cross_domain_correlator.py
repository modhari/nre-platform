"""
cross_domain_correlator.py — Cross-domain BGP + EVPN incident correlation.

Maintains a short in-memory window of recent BGP and EVPN incidents.
When a BGP incident and an EVPN incident share the same device and fabric
within the correlation window, they are grouped into a single cross-domain
incident and published to nre.cross_domain_incidents.

Correlation rules:
  - Same fabric AND same device
  - Both incidents within CORRELATION_WINDOW_SECONDS of each other
  - BGP root cause maps to a known EVPN symptom (see CORRELATION_MAP)

This runs inside the dual_diagnostics loop — after both BGP and EVPN
iterations complete, the correlator checks for overlapping incidents.
"""
from __future__ import annotations

import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any


# ── Config ────────────────────────────────────────────────────────────────────

CORRELATION_WINDOW_SECONDS = int(os.getenv("CORRELATION_WINDOW_SECONDS", "300"))

# BGP root cause → EVPN scenarios that commonly share the same root cause
CORRELATION_MAP: dict[str, list[str]] = {
    "peering_or_reachability_issue": [
        "esi_split_brain_analysis",
        "vtep_reachability_analysis",
        "vni_mismatch_analysis",
    ],
    "route-reflector": [
        "esi_split_brain_analysis",
        "vtep_reachability_analysis",
    ],
    "rr_failure": [
        "esi_split_brain_analysis",
        "vtep_reachability_analysis",
    ],
    "prefix_drain": [
        "vtep_reachability_analysis",
        "vni_mismatch_analysis",
    ],
    # BGP session flap on a device correlates with MAC mobility on same device
    "hold_timer_expired": [
        "mac_mobility_analysis",
        "vtep_reachability_analysis",
    ],
    "session_flap": [
        "mac_mobility_analysis",
        "vtep_reachability_analysis",
    ],
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ts() -> float:
    return time.time()


# ── In-memory incident window ─────────────────────────────────────────────────

class IncidentWindow:
    """
    Short-lived in-memory store of recent BGP and EVPN incidents.
    Keyed by (fabric, device) for fast cross-domain lookup.
    Entries expire after CORRELATION_WINDOW_SECONDS.
    """

    def __init__(self, window_s: int = CORRELATION_WINDOW_SECONDS) -> None:
        self._window_s = window_s
        # bgp[(fabric, device)] = list of {root_cause, incident_id, ts}
        self._bgp:  dict[tuple, list[dict[str, Any]]] = defaultdict(list)
        # evpn[(fabric, device)] = list of {scenario, incident_id, ts, anomaly_type}
        self._evpn: dict[tuple, list[dict[str, Any]]] = defaultdict(list)

    def _prune(self) -> None:
        cutoff = _now_ts() - self._window_s
        for key in list(self._bgp):
            self._bgp[key] = [e for e in self._bgp[key] if e["ts"] > cutoff]
            if not self._bgp[key]:
                del self._bgp[key]
        for key in list(self._evpn):
            self._evpn[key] = [e for e in self._evpn[key] if e["ts"] > cutoff]
            if not self._evpn[key]:
                del self._evpn[key]

    def add_bgp(
        self,
        fabric: str,
        device: str,
        root_cause: str,
        incident_id: str,
    ) -> None:
        self._bgp[(fabric, device)].append({
            "root_cause":  root_cause,
            "incident_id": incident_id,
            "ts":          _now_ts(),
        })

    def add_evpn(
        self,
        fabric: str,
        device: str,
        scenario: str,
        incident_id: str,
        anomaly_type: str,
    ) -> None:
        self._evpn[(fabric, device)].append({
            "scenario":    scenario,
            "incident_id": incident_id,
            "anomaly_type": anomaly_type,
            "ts":          _now_ts(),
        })

    def find_correlations(self) -> list[dict[str, Any]]:
        """
        Find BGP + EVPN incident pairs that share device/fabric and
        have a known causal relationship via CORRELATION_MAP.

        Returns list of correlation dicts ready to publish.
        """
        self._prune()
        correlations: list[dict[str, Any]] = []
        seen: set[tuple] = set()

        for key, bgp_entries in self._bgp.items():
            fabric, device = key
            evpn_entries = self._evpn.get(key, [])
            if not evpn_entries:
                continue

            for bgp in bgp_entries:
                root_cause = bgp["root_cause"]
                correlated_scenarios = CORRELATION_MAP.get(root_cause, [])
                if not correlated_scenarios:
                    continue

                for evpn in evpn_entries:
                    scenario = evpn["scenario"]
                    if scenario not in correlated_scenarios:
                        continue

                    pair_key = (bgp["incident_id"], evpn["incident_id"])
                    if pair_key in seen:
                        continue
                    seen.add(pair_key)

                    correlations.append({
                        "fabric":          fabric,
                        "device":          device,
                        "bgp_incident_id": bgp["incident_id"],
                        "bgp_root_cause":  root_cause,
                        "evpn_incident_id": evpn["incident_id"],
                        "evpn_scenario":   scenario,
                        "evpn_anomaly_type": evpn["anomaly_type"],
                        "correlation_confidence": "high"
                        if root_cause in CORRELATION_MAP else "medium",
                    })

        return correlations


# ── Public API ────────────────────────────────────────────────────────────────

_window = IncidentWindow()


def record_bgp_incident(
    fabric: str,
    device: str,
    root_cause: str,
    incident_id: str,
) -> None:
    _window.add_bgp(fabric=fabric, device=device,
                    root_cause=root_cause, incident_id=incident_id)


def record_evpn_incident(
    fabric: str,
    device: str,
    scenario: str,
    incident_id: str,
    anomaly_type: str,
) -> None:
    _window.add_evpn(fabric=fabric, device=device, scenario=scenario,
                     incident_id=incident_id, anomaly_type=anomaly_type)


def check_and_publish_correlations(publish_fn: Any) -> None:
    """
    Check for cross-domain correlations and publish any found.
    Call this after both BGP and EVPN iterations complete.
    """
    bgp_count  = sum(len(v) for v in _window._bgp.values())
    evpn_count = sum(len(v) for v in _window._evpn.values())
    print(
        f"[nre_agent] cross_domain_check"
        f" bgp_window={bgp_count} evpn_window={evpn_count}",
        flush=True,
    )
    correlations = _window.find_correlations()
    if not correlations:
        return

    print(
        f"[nre_agent] cross_domain_correlations found={len(correlations)}",
        flush=True,
    )

    for c in correlations:
        ts          = _utc_now_iso()
        incident_id = (
            f"cross:{c['fabric']}:{c['device']}"
            f":{c['bgp_root_cause']}:{c['evpn_anomaly_type']}"
        )

        print(
            f"[nre_agent] cross_domain_incident"
            f" incident_id={incident_id}"
            f" fabric={c['fabric']}"
            f" device={c['device']}"
            f" bgp_root_cause={c['bgp_root_cause']}"
            f" evpn_scenario={c['evpn_scenario']}"
            f" confidence={c['correlation_confidence']}",
            flush=True,
        )

        publish_fn(
            topic="nre.cross_domain_incidents",
            key=incident_id,
            payload={
                "event_type":              "cross_domain_incident",
                "event_version":           "v1",
                "ts":                      ts,
                "incident_id":             incident_id,
                "fabric":                  c["fabric"],
                "device":                  c["device"],
                "bgp_incident_id":         c["bgp_incident_id"],
                "bgp_root_cause":          c["bgp_root_cause"],
                "evpn_incident_id":        c["evpn_incident_id"],
                "evpn_scenario":           c["evpn_scenario"],
                "evpn_anomaly_type":       c["evpn_anomaly_type"],
                "correlation_confidence":  c["correlation_confidence"],
                "summary": (
                    f"BGP {c['bgp_root_cause']} and EVPN {c['evpn_scenario']} "
                    f"on {c['device']} share the same root cause"
                ),
            },
        )
