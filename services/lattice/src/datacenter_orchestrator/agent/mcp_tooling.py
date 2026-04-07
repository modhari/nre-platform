"""
MCP style tooling hook.

Purpose
Allow an external agent or MCP server to participate in risk evaluation or
enrichment without making the deterministic core depend on a specific runtime.

This is intentionally narrow.
It is a hook, not a replacement for the deterministic planner or guard.
"""

from __future__ import annotations

from typing import Protocol

from datacenter_orchestrator.core.types import ChangePlan
from datacenter_orchestrator.inventory.store import InventoryStore
from datacenter_orchestrator.planner.risk import PlanRiskAssessment


class PlanEvaluationTool(Protocol):
    """
    Tool interface for plan evaluation.

    A real MCP server could implement this method by:
    1) fetching more context
    2) applying policy logic
    3) returning a structured assessment

    The engine can merge this with local deterministic assessment if desired.
    """

    def evaluate_plan(
        self,
        plan: ChangePlan,
        inventory: InventoryStore,
    ) -> PlanRiskAssessment:
        """Return a risk assessment for the plan."""
