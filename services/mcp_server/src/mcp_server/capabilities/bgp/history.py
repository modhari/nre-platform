from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


def _lattice_mcp_base_url() -> str:
    return os.getenv("BGP_HISTORY_URL", "http://lattice:8080").rstrip("/")


def _lattice_bearer_token() -> str:
    return os.getenv("LATTICE_MCP_AUTH_TOKEN", "local-dev-token")


def _post_lattice_capability(
    *,
    capability_name: str,
    payload: dict[str, Any],
    idempotency_key: str | None,
) -> dict[str, Any]:
    request_body = {"payload": payload}

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_lattice_bearer_token()}",
    }

    if idempotency_key:
        headers["X-Idempotency-Key"] = idempotency_key

    request = urllib.request.Request(
        url=f"{_lattice_mcp_base_url()}/mcp/capability/{capability_name}",
        data=json.dumps(request_body).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(
            f"lattice capability {capability_name} failed with HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"unable to reach lattice capability endpoint for {capability_name}: {exc}"
        ) from exc


def history_query(request: dict) -> dict:
    request_id = request.get("request_id", "unknown")
    params = request.get("params", {})

    if not isinstance(params, dict):
        return {
            "api_version": "v1",
            "request_id": request_id,
            "ok": False,
            "error": {
                "code": "validation_error",
                "message": "params must be an object",
            },
        }

    if "query_type" not in params:
        return {
            "api_version": "v1",
            "request_id": request_id,
            "ok": False,
            "error": {
                "code": "validation_error",
                "message": "missing required field query_type",
            },
        }

    idempotency_key = str(
        params.get("idempotency_key")
        or params.get("incident_id")
        or request_id
    )

    try:
        result = _post_lattice_capability(
            capability_name="bgp_history_query",
            payload=params,
            idempotency_key=idempotency_key,
        )
        return {
            "api_version": "v1",
            "request_id": request_id,
            "ok": True,
            "result": result,
        }
    except Exception as exc:
        return {
            "api_version": "v1",
            "request_id": request_id,
            "ok": False,
            "error": {
                "code": "bgp_history_query_failed",
                "message": str(exc),
            },
        }
