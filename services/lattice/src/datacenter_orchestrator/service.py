from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from datacenter_orchestrator.agent.mcp_client import MCPClient
from datacenter_orchestrator.mcp.security import McpAuthConfig
from datacenter_orchestrator.runtime import build_runner

app = FastAPI(title="lattice", version="0.1.0")


@app.get("/")
def root() -> dict[str, str]:
    """
    Basic service identity endpoint.
    """
    return {
        "service": "lattice",
        "package": "datacenter_orchestrator",
        "status": "running",
    }


@app.get("/health/live")
def health_live() -> JSONResponse:
    """
    Liveness probe.
    """
    return JSONResponse(content={"status": "alive"})


@app.get("/health/ready")
def health_ready() -> JSONResponse:
    """
    Readiness probe.
    """
    return JSONResponse(content={"status": "ready"})


@app.get("/version")
def version() -> dict[str, str]:
    """
    Simple version endpoint.
    """
    return {
        "service": "lattice",
        "package": "datacenter_orchestrator",
        "version": "0.1.0",
    }


@app.post("/run")
async def run_once(request: Request) -> dict:
    """
    Execute one orchestration cycle.

    Request body may optionally provide:
    {
      "scenario": "leaf_bgp_disable"
    }

    Response returns high level orchestration status and the primary run result.
    """

    body = (
        await request.json()
        if request.headers.get("content-type", "").startswith("application/json")
        else {}
    )

    scenario = body.get("scenario")

    runner = build_runner(scenario=scenario)
    results = runner.run_cycle()

    if not results:
        return {
            "status": "ok",
            "message": "one orchestration cycle completed",
            "scenario": scenario,
            "results": [],
        }

    result = results[0]

    risk_payload = None
    if result.risk is not None:
        risk_payload = {
            "risk_level": result.risk.risk_level.value,
            "blast_radius_score": result.risk.blast_radius_score,
            "requires_approval": result.risk.requires_approval,
            "reasons": result.risk.reasons,
            "evidence": result.risk.evidence,
        }

    alert_payload = None
    if result.alert is not None:
        alert_payload = {
            "summary": result.alert.summary,
        }

    return {
        "status": "ok",
        "message": "one orchestration cycle completed",
        "scenario": scenario,
        "result": {
            "ok": result.ok,
            "intent_id": getattr(result, "intent_id", None),
            "risk": risk_payload,
            "alert": alert_payload,
        },
    }


@app.post("/diagnostics/bgp")
async def diagnostics_bgp(request: Request) -> dict:
    """
    Forward a normalized BGP snapshot to MCP for deterministic read only diagnosis.

    Check in 2 expectation:
    the request body should increasingly follow the stronger normalized contract:
    {
      "fabric": "prod-dc-west",
      "device": "leaf-01",
      "snapshot": {
        "correlation_window_seconds": 180,
        "neighbors": [...],
        "adj_rib_in": [...],
        "loc_rib": [...],
        "adj_rib_out": [...],
        "events": [...],
        "logs": [...]
      }
    }

    Lattice remains permissive at the edge so the integration can evolve safely.
    """

    body = (
        await request.json()
        if request.headers.get("content-type", "").startswith("application/json")
        else {}
    )

    fabric = str(body.get("fabric", "default"))
    device = str(body.get("device", ""))
    snapshot = body.get("snapshot", {})

    if not device:
        return {
            "status": "error",
            "message": "missing required field device",
        }

    if not isinstance(snapshot, dict):
        return {
            "status": "error",
            "message": "snapshot must be an object",
        }

    mcp_client = _build_mcp_client()
    diagnosis = mcp_client.analyze_bgp(
        fabric=fabric,
        device=device,
        snapshot=snapshot,
    )

    return {
        "status": "ok",
        "message": "bgp diagnostics completed",
        "fabric": fabric,
        "device": device,
        "diagnosis": diagnosis.get("result", {}),
    }


def _build_mcp_client() -> MCPClient:
    """
    Build an MCP client from environment settings.

    This mirrors the existing runner configuration so service endpoints and the agent use
    the same trust boundary and destination settings.
    """
    return MCPClient(
        base_url=os.environ.get("MCP_SERVER_URL", "http://mcp-server:8080"),
        auth=McpAuthConfig(
            auth_token=os.environ.get("MCP_AUTH_TOKEN", "change_me"),
            hmac_secret=os.environ.get("MCP_HMAC_SECRET", "change_me_too"),
        ),
    )
