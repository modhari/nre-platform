from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mcp_server.capabilities.bgp import analyze_bgp_snapshot
from mcp_server.capabilities.evpn_analyze_issue import (
    EVPNAnalyzeIssueError,
    EVPNAnalyzeIssueHandler,
)


@dataclass
class ExecutedToolResult:
    tool_name: str
    status: str
    detail: dict[str, Any]


class EVPNExecuteReadOnlyPlanHandler:
    """
    Safe read only execution loop.

    Flow:
    1. Reuse evpn_analyze_issue to get governed plan
    2. Execute only allowed tools
    3. Execute only tools that have an actual safe implementation
    4. Defer everything else explicitly
    """

    def __init__(self) -> None:
        self.analysis_handler = EVPNAnalyzeIssueHandler()

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        analysis_response = self.analysis_handler.handle(request)
        result = analysis_response.get("result", {})
        governed_plan = result.get("governed_plan", {})
        reasoning = result.get("reasoning", {})
        original_request = result.get("request", {})

        allowed_tools = governed_plan.get("allowed_tools", [])
        blocked_tools = governed_plan.get("blocked_tools", [])
        downgraded_tools = governed_plan.get("downgraded_tools", [])

        executed: list[dict[str, Any]] = []
        deferred: list[dict[str, Any]] = []

        for tool in allowed_tools:
            tool_name = tool.get("tool_name", "")
            tool_args = tool.get("arguments", {}) or {}

            if tool_name == "inspect_evpn_control_plane_state":
                exec_result = self._execute_control_plane_state(
                    original_request=original_request,
                    reasoning=reasoning,
                    tool_args=tool_args,
                )
                executed.append(exec_result)
                continue

            # everything else is not yet backed by a real read path
            deferred.append(
                {
                    "tool_name": tool_name,
                    "status": "deferred",
                    "reason": "No concrete read only backend is wired yet for this tool.",
                    "arguments": tool_args,
                }
            )

        return {
            "api_version": "v1",
            "request_id": request.get("request_id", "unknown"),
            "ok": True,
            "result": {
                "analysis": result,
                "execution": {
                    "mode": "read_only",
                    "executed_tools": executed,
                    "deferred_tools": deferred,
                    "blocked_tools": blocked_tools,
                    "downgraded_tools": downgraded_tools,
                },
            },
        }

    def _execute_control_plane_state(
        self,
        original_request: dict[str, Any],
        reasoning: dict[str, Any],
        tool_args: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Minimal real execution path using existing BGP capability.

        Today this is conservative:
        - if a normalized snapshot is present in params.snapshot, call analyze_bgp_snapshot
        - otherwise return a read only placeholder saying snapshot is required

        This gives you a real loop without inventing device reads that do not exist yet.
        """
        snapshot = original_request.get("snapshot")
        device = original_request.get("device")
        fabric = original_request.get("fabric", "default")

        if isinstance(snapshot, dict) and device:
            bgp_result = analyze_bgp_snapshot(
                fabric=str(fabric),
                device=str(device),
                snapshot=snapshot,
            )
            return {
                "tool_name": "inspect_evpn_control_plane_state",
                "status": "executed",
                "backend": "analyze_bgp",
                "detail": bgp_result,
            }

        return {
            "tool_name": "inspect_evpn_control_plane_state",
            "status": "deferred",
            "backend": "analyze_bgp",
            "detail": {
                "reason": "A normalized snapshot was not provided, so BGP read only analysis was not executed.",
                "required_input": "params.snapshot as normalized control plane snapshot",
            },
        }
