"""
api.py — MCP server HTTP request handler.

Responsibilities:
  - Enforce the Authorization header on every /mcp request.
  - Route incoming MCP method names to capability handlers.
  - Return a consistent JSON envelope:
      {api_version, request_id, ok, result|error}

Adding a new capability:
  1. Create src/mcp_server/capabilities/<domain>/<file>.py with a
     handler function: (request: dict) -> dict.
  2. Import it below and add an elif branch in do_POST.
  3. No other files need to change.

MCP methods currently supported:
  plan.evaluate / evaluate_plan        blast-radius scoring for a change plan
  ecmp.trace  / trace_ecmp_path        ECMP path tracing via ecmp-trace service
  bgp.analyze / analyze_bgp            BGP snapshot diagnosis via lattice
  bgp.history_query                    historical route queries via lattice-mcp
  bgp.remediation_plan                 read-only remediation planning
  bgp.remediation_execute              write-path remediation (gated)
  bgp.rag_context                      RAG context from Qdrant BGP collection
  evpn.analyze / evpn_analyze_issue    EVPN analysis via lattice + Qdrant
  evpn.execute_read_only               EVPN read-only inspection plan
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict

# ── BGP capability handlers ───────────────────────────────────────────────────
from mcp_server.capabilities.bgp import analyze as bgp_analyze
from mcp_server.capabilities.bgp import history_query as bgp_history_query
from mcp_server.capabilities.bgp import remediation_execute as bgp_remediation_execute
from mcp_server.capabilities.bgp import remediation_plan as bgp_remediation_plan
from mcp_server.capabilities.bgp.rag_context import bgp_rag_context

# ── EVPN capability handlers ──────────────────────────────────────────────────
from mcp_server.capabilities.evpn.analyze import analyze as evpn_analyze
from mcp_server.capabilities.evpn.execute_read_only import (
    execute_read_only as evpn_execute_read_only,
)

# ── ECMP trace capability ─────────────────────────────────────────────────────
from mcp_server.capabilities.trace_ecmp import trace_ecmp_path


class MCPRequestHandler(BaseHTTPRequestHandler):
    """
    Single HTTP handler for all MCP requests.

    All traffic arrives as POST /mcp with a JSON body:
      {
        "api_version": "v1",
        "request_id":  "<stable id for tracing>",
        "method":      "<capability method name>",
        "params":      { ...method-specific... }
      }

    The handler enforces auth, routes by method, and returns a consistent
    envelope. It never talks to infrastructure directly — all domain
    logic lives in the capability modules.
    """

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress BaseHTTPRequestHandler's default per-request stdout noise.
        # Structured logging from capability modules is preferred.
        return

    def do_POST(self) -> None:
        # ── Route guard ───────────────────────────────────────────────────────
        if self.path != "/mcp":
            self._send_json(self._error("not_found", "unknown endpoint"))
            return

        # ── Auth ──────────────────────────────────────────────────────────────
        # Every MCP request must carry Authorization: Bearer <token>.
        auth_header = self.headers.get("Authorization")
        if not auth_header:
            self._send_json(
                self._error("validation_error", "missing Authorization header")
            )
            return

        # ── Parse body ────────────────────────────────────────────────────────
        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length)

        try:
            request = json.loads(raw_body)
        except Exception:
            self._send_json(
                self._error("invalid_json", "unable to parse request body")
            )
            return

        print("=== MCP REQUEST ===", flush=True)
        print(request, flush=True)
        print("==================", flush=True)

        method = request.get("method")

        # ── Capability dispatch ───────────────────────────────────────────────
        # Each branch calls exactly one capability handler.
        # Handlers are pure functions: (request: dict) -> dict.
        # They never raise — errors are returned as ok=false envelopes.

        if method in ("plan.evaluate", "evaluate_plan"):
            # Blast-radius scoring for a proposed network change plan.
            response = self._handle_evaluate_plan(request)

        elif method in ("ecmp.trace", "trace_ecmp_path"):
            # ECMP path tracing — delegates to the Go ecmp-trace service.
            response = self._handle_trace_ecmp_path(request)

        elif method in ("bgp.analyze", "analyze_bgp"):
            # BGP snapshot diagnosis: classify peer events, propose actions.
            response = bgp_analyze(request)

        elif method in ("bgp.history_query",):
            # Historical route queries: removed prefixes, events, anomalies.
            response = bgp_history_query(request)

        elif method in ("bgp.remediation_plan",):
            # Read-only remediation plan: anomaly → recommended action list.
            response = bgp_remediation_plan(request)

        elif method in ("bgp.remediation_execute",):
            # Write-path remediation: executes operator-approved actions.
            response = bgp_remediation_execute(request)

        elif method in ("bgp.rag_context",):
            # RAG context retrieval: returns vendor BGP knowledge chunks
            # from Qdrant so the agent can ground its reasoning in docs.
            response = bgp_rag_context(request)

        elif method in ("evpn.analyze", "evpn_analyze_issue"):
            # EVPN analysis: RAG retrieval + policy-governed MCP plan.
            response = evpn_analyze(request)

        elif method in ("evpn.execute_read_only", "evpn_execute_read_only_plan"):
            # EVPN read-only execution plan: safe inspection steps only.
            response = evpn_execute_read_only(request)

        else:
            response = self._error(
                "not_implemented",
                f"unsupported method: {method}",
                request,
            )

        self._send_json(response)

    # ── Inline capability: plan.evaluate ──────────────────────────────────────

    def _handle_evaluate_plan(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Score a proposed network change plan for blast radius.

        Input params:
          plan.actions      list of {device, model_paths}
          inventory.devices list of {name, role}

        Output result:
          risk_level          low | medium | high
          blast_radius_score  integer, higher = riskier
          requires_approval   bool (true when score >= 50)
          reasons             list of human-readable explanations
          touched_devices     sorted list of device names in the plan
        """
        params    = request.get("params", {})
        plan      = params.get("plan", {})
        inventory = params.get("inventory", {})

        actions = plan.get("actions", [])
        devices = inventory.get("devices", [])

        # ── Index devices by name for role lookup ─────────────────────────────
        touched_devices = {a.get("device") for a in actions if "device" in a}
        device_index    = {d.get("name"): d for d in devices if isinstance(d, dict)}

        blast_radius = 0
        reasons:     list[str] = []
        touches_bgp  = False

        for action in actions:
            device = action.get("device", "unknown")
            paths  = action.get("model_paths", {})

            for path, value in paths.items():
                path_str = str(path)

                # Interface changes carry moderate risk
                if "interfaces/interface" in path_str:
                    blast_radius += 10
                    reasons.append("interface configuration change detected")

                # BGP neighbor changes are high-risk
                if "bgp/neighbors" in path_str:
                    touches_bgp   = True
                    blast_radius += 30
                    reasons.append("plan modifies bgp-related model paths")

                    if value is False:
                        blast_radius += 10
                        reasons.append("bgp neighbor disable requested")

            # Spine-tier devices multiply risk — they carry all traffic
            role = str(device_index.get(device, {}).get("role", "unknown"))
            if role == "spine":
                blast_radius += 20
                reasons.append("plan touches spine tier")

                if touches_bgp:
                    blast_radius += 20
                    reasons.append(
                        "spine + bgp change increases blast radius significantly"
                    )

        # ── Risk classification ───────────────────────────────────────────────
        requires_approval = blast_radius >= 50
        if blast_radius >= 50:
            risk_level = "high"
        elif blast_radius >= 20:
            risk_level = "medium"
        else:
            risk_level = "low"

        return {
            "api_version": "v1",
            "request_id":  request.get("request_id", "unknown"),
            "ok":          True,
            "result": {
                "risk_level":         risk_level,
                "blast_radius_score": blast_radius,
                "requires_approval":  requires_approval,
                "reasons":            reasons,
                "touched_devices":    sorted(
                    str(d) for d in touched_devices if d
                ),
            },
        }

    # ── Inline capability: ecmp.trace ─────────────────────────────────────────

    def _handle_trace_ecmp_path(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Delegate ECMP path tracing to the Go ecmp-trace service.

        Required params: source, destination
        Optional params: mode (default: data_plane), flow dict
        """
        params = request.get("params", {})

        source      = str(params.get("source",      ""))
        destination = str(params.get("destination", ""))
        mode        = str(params.get("mode",        "data_plane"))
        flow        = params.get("flow", {})

        if not source:
            return self._error(
                "validation_error", "missing required field source", request
            )
        if not destination:
            return self._error(
                "validation_error", "missing required field destination", request
            )

        try:
            result = trace_ecmp_path(
                source=source,
                destination=destination,
                flow=flow if isinstance(flow, dict) else {},
                mode=mode,
            )
            return {
                "api_version": "v1",
                "request_id":  request.get("request_id", "unknown"),
                "ok":          True,
                "result":      result,
            }
        except Exception as exc:
            return {
                "api_version": "v1",
                "request_id":  request.get("request_id", "unknown"),
                "ok":          False,
                "error": {
                    "code":    "trace_failed",
                    "message": str(exc),
                },
            }

    # ── HTTP response helpers ─────────────────────────────────────────────────

    def _send_json(self, payload: Dict[str, Any]) -> None:
        """Serialise payload to JSON and write the HTTP response."""
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _error(
        self,
        code: str,
        message: str,
        request: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Build a standard ok=false error envelope."""
        return {
            "api_version": "v1",
            "request_id":  (request or {}).get("request_id", "unknown"),
            "ok":          False,
            "error": {
                "code":    code,
                "message": message,
            },
        }


# ── Server entrypoint ─────────────────────────────────────────────────────────

def run_server() -> None:
    """Start the blocking HTTP server on 0.0.0.0:8080."""
    server = HTTPServer(("0.0.0.0", 8080), MCPRequestHandler)
    print("mcp_server listening on http://0.0.0.0:8080/mcp", flush=True)
    server.serve_forever()
