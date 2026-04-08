from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from internal.knowledge.planning.evpn_capability_bridge import (
    EVPNCapabilityBridge,
    EVPNCapabilityRegistry,
    GovernedMCPPlan,
)
from internal.knowledge.planning.evpn_mcp_planner import EVPNMCPPlanner, MCPPlan
from internal.knowledge.reasoning.evpn_reasoner import (
    EvpnReasoner,
    ProblemContext,
    ReasoningOutput,
)


@dataclass
class EVPNAnalysisRequest:
    question: str
    vendor: str
    nos_family: str | None = None
    scenario: str | None = None
    capability: str | None = None
    feature: str | None = None
    device: str | None = None
    fabric: str | None = None
    site: str | None = None
    pod: str | None = None
    vrf: str | None = None
    vni: int | None = None
    mac: str | None = None
    vtep: str | None = None
    incident_id: str | None = None
    timestamp_utc: str | None = None
    limit: int = 5


@dataclass
class EVPNAnalysisResponse:
    request: dict[str, Any]
    reasoning: dict[str, Any]
    mcp_plan: dict[str, Any]
    governed_plan: dict[str, Any]
    audit: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": self.request,
            "reasoning": self.reasoning,
            "mcp_plan": self.mcp_plan,
            "governed_plan": self.governed_plan,
            "audit": self.audit,
        }


class EVPNAnalysisService:
    """
    Unified EVPN VXLAN orchestration entrypoint.

    Flow:
      request -> reasoner -> MCP planner -> capability bridge -> structured response
    """

    def __init__(
        self,
        coverage_summary_path: str | Path | None = None,
        policy_dir: str | Path | None = None,
        qdrant_url: str | None = None,
    ) -> None:
        import os as _os
        if coverage_summary_path is None:
            coverage_summary_path = Path("data/generated/schema/evpn_vxlan_coverage_summary.json")

        from internal.knowledge.retrieval.retriever import EvpnVxlanRetriever, RetrieverConfig
        _qdrant_url = qdrant_url or _os.environ.get("QDRANT_URL", "http://127.0.0.1:6333")
        retriever = EvpnVxlanRetriever(config=RetrieverConfig(qdrant_url=_qdrant_url))
        self.reasoner = EvpnReasoner(retriever=retriever)
        self.planner = EVPNMCPPlanner(policy_dir=policy_dir)
        self.registry = EVPNCapabilityRegistry(coverage_summary_path=coverage_summary_path)
        self.bridge = EVPNCapabilityBridge(registry=self.registry, policy_dir=policy_dir)

    def analyze(self, req: EVPNAnalysisRequest) -> EVPNAnalysisResponse:
        problem = ProblemContext(
            question=req.question,
            vendor=req.vendor,
            nos_family=req.nos_family,
            scenario=req.scenario,
            capability=req.capability,
            feature=req.feature,
            limit=req.limit,
        )

        reasoning: ReasoningOutput = self.reasoner.reason(problem)
        mcp_plan: MCPPlan = self.planner.build_plan(problem, reasoning)
        governed: GovernedMCPPlan = self.bridge.govern(problem, reasoning, mcp_plan)

        response = EVPNAnalysisResponse(
            request=self._request_dict(req),
            reasoning=reasoning.to_dict(),
            mcp_plan=mcp_plan.to_dict(),
            governed_plan=governed.to_dict(),
            audit=self._audit_dict(req, reasoning, governed),
        )
        return response

    def _request_dict(self, req: EVPNAnalysisRequest) -> dict[str, Any]:
        return {
            "question": req.question,
            "vendor": req.vendor,
            "nos_family": req.nos_family,
            "scenario": req.scenario,
            "capability": req.capability,
            "feature": req.feature,
            "device": req.device,
            "fabric": req.fabric,
            "site": req.site,
            "pod": req.pod,
            "vrf": req.vrf,
            "vni": req.vni,
            "mac": req.mac,
            "vtep": req.vtep,
            "incident_id": req.incident_id,
            "timestamp_utc": req.timestamp_utc,
            "limit": req.limit,
        }

    def _audit_dict(
        self,
        req: EVPNAnalysisRequest,
        reasoning: ReasoningOutput,
        governed: GovernedMCPPlan,
    ) -> dict[str, Any]:
        return {
            "vendor": req.vendor,
            "scenario": req.scenario,
            "incident_id": req.incident_id,
            "device": req.device,
            "retrieved_chunk_ids": [c["chunk_id"] for c in reasoning.to_dict().get("retrieved_chunks", [])],
            "retrieved_document_ids": sorted(
                {c["document_id"] for c in reasoning.to_dict().get("retrieved_chunks", [])}
            ),
            "reasoning_confidence": reasoning.confidence,
            "governed_execution_mode": governed.execution_mode,
            "allowed_tools": [t.tool_name for t in governed.allowed_tools],
            "blocked_tools": [t.tool_name for t in governed.blocked_tools],
            "downgraded_tools": [t.tool_name for t in governed.downgraded_tools],
        }
