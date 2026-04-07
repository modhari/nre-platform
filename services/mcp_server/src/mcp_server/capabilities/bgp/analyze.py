from __future__ import annotations

from mcp_server.capabilities.bgp.analyzer import analyze_bgp_snapshot


def analyze(request: dict) -> dict:
    params = request.get("params", {})
    fabric = str(params.get("fabric", "default"))
    device = str(params.get("device", ""))
    snapshot = params.get("snapshot", {})

    if not device:
        return {
            "api_version": "v1",
            "request_id": request.get("request_id", "unknown"),
            "ok": False,
            "error": {
                "code": "validation_error",
                "message": "missing required field device",
            },
        }

    if not isinstance(snapshot, dict):
        return {
            "api_version": "v1",
            "request_id": request.get("request_id", "unknown"),
            "ok": False,
            "error": {
                "code": "validation_error",
                "message": "snapshot must be an object",
            },
        }

    try:
        result = analyze_bgp_snapshot(
            fabric=fabric,
            device=device,
            snapshot=snapshot,
        )
        return {
            "api_version": "v1",
            "request_id": request.get("request_id", "unknown"),
            "ok": True,
            "result": result,
        }
    except Exception as exc:
        return {
            "api_version": "v1",
            "request_id": request.get("request_id", "unknown"),
            "ok": False,
            "error": {
                "code": "bgp_analysis_failed",
                "message": str(exc),
            },
        }
