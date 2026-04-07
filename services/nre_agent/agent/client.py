"""
client.py — HTTP client for all nre-agent outbound calls.

All external calls go through this module. No other module in the agent
should import urllib or requests directly.

Call chain:
  nre_agent → mcp_server (/mcp POST)
    → lattice      (bgp.analyze, evpn.*)
    → lattice-mcp  (bgp.history_query, bgp.remediation_plan)
    → ecmp-trace   (ecmp.trace)
    → qdrant       (bgp.rag_context — proxied through mcp_server)

Environment variables:
  NRE_AGENT_MCP_URL         mcp_server base URL
                             default: http://mcp-server:8080
  NRE_AGENT_MCP_AUTH_TOKEN  bearer token for MCP auth
                             default: test
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any


# ── Connection config ─────────────────────────────────────────────────────────

def _mcp_url() -> str:
    return os.getenv("NRE_AGENT_MCP_URL", "http://mcp-server:8080").rstrip("/")

def _mcp_auth_token() -> str:
    return os.getenv("NRE_AGENT_MCP_AUTH_TOKEN", "test")


# ── Core HTTP helper ──────────────────────────────────────────────────────────

def _post_mcp(method: str, params: dict[str, Any]) -> dict[str, Any]:
    """
    Send one MCP request to mcp_server and return the parsed response body.

    Raises on HTTP errors and connection failures — callers must catch.
    """
    payload = {
        "api_version": "v1",
        "request_id":  f"{method.replace('.', '_')}_agent",
        "method":      method,
        "params":      params,
    }

    req = urllib.request.Request(
        url=f"{_mcp_url()}/mcp",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {_mcp_auth_token()}",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=15) as response:
        body = response.read().decode("utf-8")

    return json.loads(body)


def _unwrap_mcp_result(response: dict[str, Any]) -> dict[str, Any]:
    """
    When mcp_server returns ok=true, unwrap the nested result dict.
    Otherwise return the full envelope so callers can inspect the error.
    """
    if response.get("ok") and isinstance(response.get("result"), dict):
        return response["result"]
    return response


# ── BGP analysis ──────────────────────────────────────────────────────────────

def call_lattice_bgp_diagnostics(
    *,
    fabric: str,
    device: str,
    snapshot: dict[str, Any],
    base_url: str = "http://lattice:8080",
) -> dict[str, Any]:
    """
    Run BGP snapshot diagnosis via mcp_server → lattice.

    This is the primary entry point for the bgp_diagnostics agent mode.
    The snapshot is raw BGP event data from the bgp_snapshot.json
    ConfigMap (or, in future, live gNMI collection via Capsule).
    """
    return call_mcp_bgp_analyze(
        fabric=fabric,
        device=device,
        snapshot=snapshot,
    )


def call_mcp_bgp_analyze(
    *,
    fabric: str,
    device: str,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """
    POST bgp.analyze to mcp_server.

    mcp_server routes this to the BGP analyzer which classifies peer
    events, detects anomalies, and proposes remediation actions.
    """
    response = _post_mcp(
        "bgp.analyze",
        {
            "fabric":   fabric,
            "device":   device,
            "snapshot": snapshot,
        },
    )
    return _unwrap_mcp_result(response)


# ── BGP history queries ───────────────────────────────────────────────────────

def call_mcp_bgp_history_query(
    *,
    query_type: str,
    device: str,
    peer: str | None = None,
    network_instance: str | None = None,
    direction: str | None = None,
    afi_safi: str | None = None,
    timestamp_ms: int | None = None,
    start_ts: int | None = None,
    end_ts: int | None = None,
    incident_id: str | None = None,
) -> dict[str, Any]:
    """
    Query BGP route history from lattice-mcp via mcp_server.

    query_type values:
      routes_at_time          point-in-time route snapshot
      route_events_between    all events in a time window
      removed_routes_between  route_removed events only
      added_routes_between    route_added events only
      peer_summaries_at_time  received/advertised counts per peer
      anomalies_between       classified anomalies in a window
    """
    params: dict[str, Any] = {
        "query_type": query_type,
        "device":     device,
    }

    # Optional filters — only included when provided
    if peer              is not None: params["peer"]              = peer
    if network_instance  is not None: params["network_instance"]  = network_instance
    if direction         is not None: params["direction"]         = direction
    if afi_safi          is not None: params["afi_safi"]          = afi_safi
    if timestamp_ms      is not None: params["timestamp_ms"]      = timestamp_ms
    if start_ts          is not None: params["start_ts"]          = start_ts
    if end_ts            is not None: params["end_ts"]            = end_ts
    if incident_id       is not None: params["incident_id"]       = incident_id

    response = _post_mcp("bgp.history_query", params)
    return _unwrap_mcp_result(response)


# ── BGP remediation planning ──────────────────────────────────────────────────

def call_mcp_bgp_remediation_plan(
    *,
    device: str,
    peer: str | None = None,
    network_instance: str = "default",
    afi_safi: str = "ipv4_unicast",
    from_timestamp_ms: int | None = None,
    to_timestamp_ms: int | None = None,
    incident_id: str | None = None,
) -> dict[str, Any]:
    """
    Request a read-only remediation plan from lattice-mcp via mcp_server.

    Returns a list of recommended actions (route_refresh, soft_clear_in,
    escalate_only, etc.) with confidence level and follow-up steps.
    Never executes — plan_only=True is enforced in the capability handler.
    """
    params: dict[str, Any] = {
        "device":           device,
        "network_instance": network_instance,
        "afi_safi":         afi_safi,
    }

    if peer              is not None: params["peer"]              = peer
    if from_timestamp_ms is not None: params["from_timestamp_ms"] = from_timestamp_ms
    if to_timestamp_ms   is not None: params["to_timestamp_ms"]   = to_timestamp_ms
    if incident_id       is not None: params["incident_id"]       = incident_id

    response = _post_mcp("bgp.remediation_plan", params)
    return _unwrap_mcp_result(response)


# ── BGP RAG context ───────────────────────────────────────────────────────────

def call_mcp_bgp_rag_context(
    *,
    vendor: str | None = None,
    anomaly_type: str | None = None,
    device: str | None = None,
    limit: int = 4,
) -> list[dict[str, Any]]:
    """
    Fetch vendor BGP knowledge chunks from Qdrant via mcp_server.

    Returns a list of chunk dicts, each with text, document_id, vendor,
    and section_title. Returns an empty list when:
      - Qdrant is unreachable
      - The BGP collection has not been ingested yet
      - mcp_server returns ok=false for any reason

    RAG context is enrichment, not a hard dependency. The agent always
    proceeds — with or without chunks. When chunks are present they are
    attached to the incident payload as rag_context so operators and
    downstream systems know which vendor documentation informed the
    diagnosis.
    """
    try:
        params: dict[str, Any] = {"limit": limit}
        if vendor:       params["vendor"]       = vendor
        if anomaly_type: params["anomaly_type"] = anomaly_type
        if device:       params["device"]       = device

        response = _post_mcp("bgp.rag_context", params)

        if not response.get("ok"):
            return []

        return response.get("result", {}).get("chunks", [])

    except Exception as exc:
        # Log and continue — never let a RAG failure stop the agent loop
        print(
            f"[nre_agent] bgp.rag_context failed (non-fatal): {exc}",
            flush=True,
        )
        return []


# ── EVPN analysis ─────────────────────────────────────────────────────────────

def call_mcp_evpn_analyze(
    *,
    question: str,
    vendor: str,
    nos_family: str,
    scenario: str,
    capability: str,
    device: str,
    fabric: str,
    site: str | None = None,
    pod: str | None = None,
    vni: int | None = None,
    mac: str | None = None,
    incident_id: str | None = None,
    timestamp_utc: str | None = None,
    limit: int = 4,
) -> dict[str, Any]:
    """
    Request EVPN analysis from mcp_server → lattice (EVPN analysis service).

    Combines RAG retrieval, policy-governed MCP plan generation, and
    capability bridge reasoning in one call.
    """
    response = _post_mcp(
        "evpn.analyze",
        {
            "question":      question,
            "vendor":        vendor,
            "nos_family":    nos_family,
            "scenario":      scenario,
            "capability":    capability,
            "device":        device,
            "fabric":        fabric,
            "site":          site,
            "pod":           pod,
            "vni":           vni,
            "mac":           mac,
            "incident_id":   incident_id,
            "timestamp_utc": timestamp_utc,
            "limit":         limit,
        },
    )
    return _unwrap_mcp_result(response)


# ── Scenario mode (legacy) ────────────────────────────────────────────────────

def call_lattice(
    scenario: str,
    base_url: str = "http://lattice:8080",
) -> dict[str, Any]:
    """
    Scenario-mode stub. The scenario path is not yet migrated to MCP.

    Returns a not_implemented error so the agent loop handles it
    gracefully without crashing.
    """
    return {
        "ok": False,
        "error": {
            "code":    "not_implemented",
            "message": (
                f"scenario path not yet migrated to MCP "
                f"for scenario '{scenario}'"
            ),
        },
    }
