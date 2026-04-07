from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from datacenter_orchestrator.core.serialization import (
    inventory_store_to_json,
    to_json_safe_dict,
)
from datacenter_orchestrator.core.types import ChangePlan
from datacenter_orchestrator.inventory.store import InventoryStore
from datacenter_orchestrator.mcp.codec import decode_response, encode_request
from datacenter_orchestrator.mcp.errors import McpValidationError
from datacenter_orchestrator.mcp.schemas import McpApiVersion, McpMethod, McpRequest
from datacenter_orchestrator.mcp.security import McpAuthConfig, compute_signature
from datacenter_orchestrator.planner.risk import PlanRiskAssessment, RiskLevel


@dataclass(frozen=True)
class MCPClient:
    """
    MCP client used by lattice.

    Responsibilities:
    build signed MCP requests
    send requests to the MCP server
    decode structured responses
    expose high level helpers for plan evaluation
    expose a generic call method for new capabilities

    This keeps lattice decoupled from any one specific MCP capability.
    """

    base_url: str
    auth: McpAuthConfig
    timeout_seconds: int = 5

    def call(self, method: str, params: dict) -> dict:
        """
        Generic MCP method call.

        This is used for capabilities beyond evaluate_plan, for example ECMP tracing and
        BGP analysis. It returns the full decoded MCP response shape.
        """
        request_id = f"{method}_{uuid.uuid4().hex[:12]}"

        req = McpRequest(
            api_version=McpApiVersion.v1,
            request_id=request_id,
            method=McpMethod(method),
            params=params,
        )

        raw = self._post_request(req)
        mcp_resp = decode_response(raw)

        if not mcp_resp.ok:
            err = mcp_resp.error
            msg = err.message if err is not None else "unknown mcp error"
            raise McpValidationError(msg)

        return {
            "api_version": mcp_resp.api_version,
            "request_id": mcp_resp.request_id,
            "ok": mcp_resp.ok,
            "result": mcp_resp.result or {},
        }

    def analyze_bgp(
        self,
        *,
        fabric: str,
        device: str,
        snapshot: dict,
    ) -> dict:
        """
        High level helper for deterministic BGP diagnostics.

        Check in 1 keeps this helper read only. Lattice forwards a normalized snapshot and
        MCP returns structured findings and a grouped alert when multiple symptoms share a
        likely root cause.
        """
        return self.call(
            "analyze_bgp",
            {
                "fabric": fabric,
                "device": device,
                "snapshot": snapshot,
            },
        )

    def evaluate_plan(
        self,
        plan: ChangePlan,
        inventory: InventoryStore,
    ) -> PlanRiskAssessment:
        """
        Evaluate plan risk through MCP.

        This remains the primary policy call used by lattice to obtain structured risk
        assessment.
        """
        request_id = self._make_request_id(plan)

        req = McpRequest(
            api_version=McpApiVersion.v1,
            request_id=request_id,
            method=McpMethod.evaluate_plan,
            params={
                "plan": to_json_safe_dict(plan),
                "inventory": inventory_store_to_json(inventory),
            },
        )

        raw = self._post_request(req)
        mcp_resp = decode_response(raw)

        if not mcp_resp.ok:
            err = mcp_resp.error
            msg = err.message if err is not None else "unknown mcp error"
            raise McpValidationError(msg)

        result = mcp_resp.result or {}

        risk_level_raw = str(result.get("risk_level", "low"))
        blast = int(result.get("blast_radius_score", 0))
        requires_approval = bool(result.get("requires_approval", False))

        reasons_raw = result.get("reasons", [])
        reasons = [str(x) for x in reasons_raw] if isinstance(reasons_raw, list) else []

        evidence_raw = result.get("evidence", {})
        evidence = dict(evidence_raw) if isinstance(evidence_raw, dict) else {}

        return PlanRiskAssessment(
            risk_level=RiskLevel(risk_level_raw),
            blast_radius_score=blast,
            requires_approval=requires_approval,
            reasons=reasons,
            evidence=evidence,
        )

    def _post_request(self, req: McpRequest) -> dict:
        """
        Serialize, sign, send, and parse a raw MCP request.
        """
        payload = encode_request(req)
        body_bytes = json.dumps(payload).encode("utf-8")

        timestamp = str(int(time.time()))
        nonce = uuid.uuid4().hex

        signature = compute_signature(
            secret=self.auth.hmac_secret,
            timestamp=timestamp,
            nonce=nonce,
            body_bytes=body_bytes,
        )

        http_req = Request(
            url=f"{self.base_url}/mcp",
            data=body_bytes,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.auth.auth_token}",
                "X-MCP-Timestamp": timestamp,
                "X-MCP-Nonce": nonce,
                "X-MCP-Signature": signature,
            },
            method="POST",
        )

        try:
            with urlopen(http_req, timeout=self.timeout_seconds) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8")
            print("MCP HTTP error body:", body, flush=True)
            raise

    def _make_request_id(self, plan: ChangePlan) -> str:
        """
        Build a stable request id for plan evaluation.
        """
        return getattr(plan, "plan_id", "plan")
