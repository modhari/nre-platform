from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from internal.knowledge.policy.evpn_policy_loader import EVPNPolicyBundle, load_evpn_policy_bundle
from internal.knowledge.reasoning.evpn_reasoner import ProblemContext, ReasoningOutput


@dataclass
class MCPToolCall:
    tool_name: str
    intent: str
    read_only: bool
    arguments: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


@dataclass
class MCPPlan:
    vendor: str
    scenario: str | None
    confidence: str
    risk_class: str
    approval_required: bool
    execution_mode: str
    summary: str
    recommended_tools: list[MCPToolCall] = field(default_factory=list)
    deferred_tools: list[MCPToolCall] = field(default_factory=list)
    blocked_actions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "vendor": self.vendor,
            "scenario": self.scenario,
            "confidence": self.confidence,
            "risk_class": self.risk_class,
            "approval_required": self.approval_required,
            "execution_mode": self.execution_mode,
            "summary": self.summary,
            "recommended_tools": [
                {
                    "tool_name": t.tool_name,
                    "intent": t.intent,
                    "read_only": t.read_only,
                    "arguments": t.arguments,
                    "reason": t.reason,
                }
                for t in self.recommended_tools
            ],
            "deferred_tools": [
                {
                    "tool_name": t.tool_name,
                    "intent": t.intent,
                    "read_only": t.read_only,
                    "arguments": t.arguments,
                    "reason": t.reason,
                }
                for t in self.deferred_tools
            ],
            "blocked_actions": self.blocked_actions,
            "notes": self.notes,
        }


class EVPNMCPPlanner:
    """
    Policy driven MCP planner for EVPN VXLAN scenarios.
    """

    def __init__(self, policy_dir: str | Path | None = None) -> None:
        if policy_dir is None:
            policy_dir = Path("internal/knowledge/policy/evpn")
        self.policy: EVPNPolicyBundle = load_evpn_policy_bundle(policy_dir)

    def build_plan(self, ctx: ProblemContext, reasoning: ReasoningOutput) -> MCPPlan:
        risk_class = self._derive_risk_class(reasoning.scenario)
        approval_required = self._approval_required(reasoning, risk_class)
        execution_mode = self._execution_mode(reasoning, approval_required)

        plan = MCPPlan(
            vendor=reasoning.vendor,
            scenario=reasoning.scenario,
            confidence=reasoning.confidence,
            risk_class=risk_class,
            approval_required=approval_required,
            execution_mode=execution_mode,
            summary=self._summary(reasoning, execution_mode),
        )

        tools = self._tool_names_for_context(ctx, reasoning)
        for tool_name in tools:
            plan.recommended_tools.append(
                MCPToolCall(
                    tool_name=tool_name,
                    intent=self._default_intent(tool_name),
                    read_only=True,
                    arguments=self._common_args(ctx, reasoning),
                    reason=self._default_reason(tool_name),
                )
            )

        if not tools:
            plan.deferred_tools.append(
                MCPToolCall(
                    tool_name="inspect_vendor_specific_evpn_state",
                    intent="Run additional vendor specific read only inspection when scenario mapping is incomplete.",
                    read_only=True,
                    arguments=self._common_args(ctx, reasoning),
                    reason="No direct policy mapping was found for this scenario.",
                )
            )

        self._add_blocked_actions(plan, reasoning)
        self._add_notes(plan, reasoning)

        return plan

    def _common_args(self, ctx: ProblemContext, reasoning: ReasoningOutput) -> dict[str, Any]:
        return {
            "vendor": ctx.vendor,
            "nos_family": ctx.nos_family,
            "scenario": reasoning.scenario,
            "capability": reasoning.capability,
            "feature": reasoning.feature,
            "confidence": reasoning.confidence,
        }

    def _tool_names_for_context(self, ctx: ProblemContext, reasoning: ReasoningOutput) -> list[str]:
        scenario = reasoning.scenario or ""
        tools = list(
            self.policy.scenario_tool_policy.get("scenarios", {})
            .get(scenario, {})
            .get("recommended_tools", [])
        )

        vendor_extra = (
            self.policy.vendor_overrides.get("vendors", {})
            .get(reasoning.vendor, {})
            .get("extra_tools_by_scenario", {})
            .get(scenario, [])
        )

        for tool in vendor_extra:
            if tool not in tools:
                tools.append(tool)

        deduped: list[str] = []
        seen: set[str] = set()
        for tool in tools:
            if tool not in seen:
                seen.add(tool)
                deduped.append(tool)
        return deduped

    def _derive_risk_class(self, scenario: str | None) -> str:
        scenario = scenario or ""
        risk_map = self.policy.risk_policy.get("risk", {})

        for risk_class, body in risk_map.items():
            scenarios = body.get("scenarios", []) if isinstance(body, dict) else []
            if scenario in scenarios:
                return risk_class

        return "medium"

    def _approval_required(self, reasoning: ReasoningOutput, risk_class: str) -> bool:
        if risk_class == "high":
            return True
        if "Do not claim production write support from these chunks alone." in reasoning.unsafe_actions:
            return True
        return True

    def _execution_mode(self, reasoning: ReasoningOutput, approval_required: bool) -> str:
        if approval_required:
            return "read_only_with_approval_gate"
        if reasoning.confidence == "high":
            return "read_only_guided"
        return "read_only_diagnostic"

    def _summary(self, reasoning: ReasoningOutput, execution_mode: str) -> str:
        scenario = reasoning.scenario or "general_evpn_analysis"
        return (
            f"Plan governed EVPN MCP inspection for scenario '{scenario}' "
            f"using {execution_mode} mode at {reasoning.confidence} confidence."
        )

    def _default_intent(self, tool_name: str) -> str:
        mapping = {
            "inspect_evpn_control_plane_state": "Collect read only EVPN route and peer state relevant to the scenario.",
            "inspect_vxlan_vni_oper_state": "Collect read only VXLAN VNI and VTEP operational state.",
            "inspect_overlay_diagnostics_support": "Check read only support for overlay ping, overlay traceroute, or equivalent diagnostics.",
            "inspect_mac_mobility_state": "Read only inspection of MAC move sequence, remote state freshness, and move visibility.",
            "inspect_duplicate_mac_state": "Read only inspection of duplicate MAC suppression, loop signals, or dampening state.",
            "inspect_mac_ip_binding_state": "Read only inspection of MAC and IP binding presence and freshness.",
            "inspect_arp_suppression_state": "Read only inspection of ARP suppression behavior and EVPN learned bindings.",
            "inspect_anycast_gateway_consistency": "Read only validation of distributed gateway identity and VNI alignment.",
            "inspect_evpn_route_scope": "Check read only domain scoping, gateway propagation, and route visibility.",
            "inspect_dci_route_propagation": "Read only inspection of cross domain EVPN route visibility and propagation scope.",
            "inspect_gateway_nexthop_behavior": "Read only inspection of gateway next hop rewriting and inter domain path interpretation.",
            "inspect_multihoming_model": "Read only inspection of MLAG versus EVPN all active design assumptions.",
            "inspect_ethernet_segment_state": "Read only inspection of Ethernet segment and designated forwarder semantics.",
            "inspect_vtep_reachability": "Read only validation of VTEP underlay reachability and remote endpoint visibility.",
            "inspect_type2_type5_route_preference": "Read only inspection of Type 2 versus Type 5 route visibility and preference behavior.",
            "inspect_vendor_specific_evpn_state": "Run additional vendor specific read only inspection when scenario mapping is incomplete.",
        }
        return mapping.get(tool_name, "Read only EVPN VXLAN inspection.")

    def _default_reason(self, tool_name: str) -> str:
        mapping = {
            "inspect_evpn_control_plane_state": "Control plane verification is broadly useful across EVPN scenarios.",
            "inspect_vxlan_vni_oper_state": "VNI and VTEP operational state is foundational for EVPN VXLAN diagnosis.",
            "inspect_overlay_diagnostics_support": "Overlay diagnostics can improve verification depth for supported vendors.",
            "inspect_mac_mobility_state": "MAC mobility is relevant to host movement and stale state interpretation.",
            "inspect_duplicate_mac_state": "Duplicate MAC behavior can explain suppression or instability symptoms.",
            "inspect_mac_ip_binding_state": "MAC and IP binding state supports EVPN learning and suppression validation.",
            "inspect_arp_suppression_state": "ARP suppression depends on accurate EVPN learned endpoint state.",
            "inspect_anycast_gateway_consistency": "Gateway identity consistency is central to distributed gateway validation.",
            "inspect_evpn_route_scope": "Route scope is important in hierarchical and multi domain EVPN topologies.",
            "inspect_dci_route_propagation": "Cross site behavior depends on route propagation and scope.",
            "inspect_gateway_nexthop_behavior": "Gateway next hop changes can affect cross domain path interpretation.",
            "inspect_multihoming_model": "Different multihoming models imply different failover expectations.",
            "inspect_ethernet_segment_state": "Ethernet segment semantics govern all active and DF behavior.",
            "inspect_vtep_reachability": "VTEP underlay reachability is foundational for overlay health.",
            "inspect_type2_type5_route_preference": "Type 2 and Type 5 interpretation is important for forwarding analysis.",
            "inspect_vendor_specific_evpn_state": "Fallback inspection keeps planning conservative when scenario mapping is incomplete.",
        }
        return mapping.get(tool_name, "Policy selected this tool for read only inspection.")

    def _add_blocked_actions(self, plan: MCPPlan, reasoning: ReasoningOutput) -> None:
        plan.blocked_actions.extend(
            [
                "No write action is permitted from reasoning output alone.",
                "Do not change EVPN policy, gateway identity, route propagation, or VNI configuration without separate capability validation.",
            ]
        )

        if plan.approval_required:
            plan.blocked_actions.append(
                "Approval is required before any action that could alter control plane, DCI, multihoming, or gateway behavior."
            )

        if reasoning.confidence == "low":
            plan.blocked_actions.append(
                "Confidence is low, so only evidence collection and read only inspection are allowed."
            )

    def _add_notes(self, plan: MCPPlan, reasoning: ReasoningOutput) -> None:
        plan.notes.append(
            "This plan is derived from EVPN VXLAN RAG reasoning and policy driven MCP planning."
        )
        plan.notes.append(
            "Use retrieved chunks as supporting context, not as sole authority for capability claims or automated remediation."
        )
        if reasoning.retrieved_chunks:
            plan.notes.append(
                f"Planning used {len(reasoning.retrieved_chunks)} retrieved chunks from the knowledge base."
            )


def pretty_print_plan(plan: MCPPlan) -> None:
    print("=" * 120)
    print("EVPN MCP PLAN")
    print("=" * 120)
    print(f"Vendor            : {plan.vendor}")
    print(f"Scenario          : {plan.scenario}")
    print(f"Confidence        : {plan.confidence}")
    print(f"Risk class        : {plan.risk_class}")
    print(f"Approval required : {plan.approval_required}")
    print(f"Execution mode    : {plan.execution_mode}")
    print(f"Summary           : {plan.summary}")
    print()

    print("Recommended tools:")
    for tool in plan.recommended_tools:
        print(f"  - {tool.tool_name}")
        print(f"    intent    : {tool.intent}")
        print(f"    read_only : {tool.read_only}")
        print(f"    reason    : {tool.reason}")
        print(f"    arguments : {tool.arguments}")
    print()

    print("Deferred tools:")
    for tool in plan.deferred_tools:
        print(f"  - {tool.tool_name}")
        print(f"    intent    : {tool.intent}")
        print(f"    reason    : {tool.reason}")
        print(f"    arguments : {tool.arguments}")
    print()

    print("Blocked actions:")
    for item in plan.blocked_actions:
        print(f"  - {item}")
    print()

    print("Notes:")
    for item in plan.notes:
        print(f"  - {item}")
    print()
