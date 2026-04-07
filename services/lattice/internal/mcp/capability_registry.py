from __future__ import annotations

from collections.abc import Callable
from typing import Any

from internal.bgp.history_store import BgpHistoryStore
from internal.bgp.mcp_history_query_capability import (
    handle_bgp_history_query_capability,
)
from internal.bgp.mcp_remediation_capability import (
    handle_bgp_remediation_capability,
)
from internal.bgp.route_state_tracker import BgpRouteStateTracker

CapabilityHandler = Callable[..., dict[str, Any]]


class CapabilityRegistry:
    """
    Thin registry for MCP capability handlers.
    """

    def __init__(
        self,
        *,
        tracker: BgpRouteStateTracker,
        history_store: BgpHistoryStore,
    ) -> None:
        self.tracker = tracker
        self.history_store = history_store

        self._handlers: dict[str, CapabilityHandler] = {
            "bgp_remediation_plan": self._handle_bgp_remediation,
            "bgp_remediation_execute": self._handle_bgp_remediation,
            "bgp_history_query": self._handle_bgp_history_query,
        }

    def get_handler(self, capability_name: str) -> CapabilityHandler | None:
        return self._handlers.get(capability_name)

    def list_capabilities(self) -> list[str]:
        return sorted(self._handlers.keys())

    def _handle_bgp_remediation(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        return handle_bgp_remediation_capability(
            payload=payload,
            tracker=self.tracker,
            history_store=self.history_store,
        )

    def _handle_bgp_history_query(self, *, payload: dict[str, Any]) -> dict[str, Any]:
        return handle_bgp_history_query_capability(
            payload=payload,
            history_store=self.history_store,
        )
