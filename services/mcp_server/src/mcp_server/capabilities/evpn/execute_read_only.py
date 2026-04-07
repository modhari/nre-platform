from __future__ import annotations

from mcp_server.capabilities.evpn_analyze_issue import EVPNAnalyzeIssueError
from mcp_server.capabilities.evpn_execute_read_only_plan import (
    EVPNExecuteReadOnlyPlanHandler,
)

_handler = EVPNExecuteReadOnlyPlanHandler()


def execute_read_only(request: dict) -> dict:
    try:
        return _handler.handle(request)
    except EVPNAnalyzeIssueError as exc:
        return {
            "api_version": "v1",
            "request_id": request.get("request_id", "unknown"),
            "ok": False,
            "error": {
                "code": "validation_error",
                "message": str(exc),
            },
        }
    except Exception as exc:
        return {
            "api_version": "v1",
            "request_id": request.get("request_id", "unknown"),
            "ok": False,
            "error": {
                "code": "evpn_read_only_execution_failed",
                "message": str(exc),
            },
        }
