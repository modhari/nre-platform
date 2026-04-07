from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from internal.knowledge.planning.evpn_mcp_planner import MCPPlan, MCPToolCall
from internal.knowledge.policy.evpn_policy_loader import EVPNPolicyBundle, load_evpn_policy_bundle
from internal.knowledge.reasoning.evpn_reasoner import ProblemContext, ReasoningOutput


@dataclass
class CapabilityStatus:
    capability: str
    vendor: str
    status: str
    rationale: str | None = None

    @property
    def is_supported_for_read(self) -> bool:
        return self.status in {"claimable", "partial", "weak"}

    @property
    def is_strong(self) -> bool:
        return self.status == "claimable"

    @property
    def is_partial(self) -> bool:
        return self.status == "partial"

    @property
    def is_weak(self) -> bool:
        return self.status == "weak"

    @property
    def is_absent(self) -> bool:
        return self.status == "absent"


@dataclass
class GovernedToolDecision:
    tool_name: str
    allowed: bool
    reason: str
    read_only: bool
    capability_checks: list[str] = field(default_factory=list)
    missing_capabilities: list[str] = field(default_factory=list)
    downgraded: bool = False


@dataclass
class GovernedMCPPlan:
    vendor: str
    scenario: str | None
    confidence: str
    risk_class: str
    approval_required: bool
    execution_mode: str
    summary: str
    allowed_tools: list[MCPToolCall] = field(default_factory=list)
    blocked_tools: list[GovernedToolDecision] = field(default_factory=list)
    downgraded_tools: list[GovernedToolDecision] = field(default_factory=list)
    blocked_actions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    capability_snapshot: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "vendor": self.vendor,
            "scenario": self.scenario,
            "confidence": self.confidence,
            "risk_class": self.risk_class,
            "approval_required": self.approval_required,
            "execution_mode": self.execution_mode,
            "summary": self.summary,
            "allowed_tools": [
                {
                    "tool_name": t.tool_name,
                    "intent": t.intent,
                    "read_only": t.read_only,
                    "arguments": t.arguments,
                    "reason": t.reason,
                }
                for t in self.allowed_tools
            ],
            "blocked_tools": [
                {
                    "tool_name": t.tool_name,
                    "allowed": t.allowed,
                    "reason": t.reason,
                    "read_only": t.read_only,
                    "capability_checks": t.capability_checks,
                    "missing_capabilities": t.missing_capabilities,
                    "downgraded": t.downgraded,
                }
                for t in self.blocked_tools
            ],
            "downgraded_tools": [
                {
                    "tool_name": t.tool_name,
                    "allowed": t.allowed,
                    "reason": t.reason,
                    "read_only": t.read_only,
                    "capability_checks": t.capability_checks,
                    "missing_capabilities": t.missing_capabilities,
                    "downgraded": t.downgraded,
                }
                for t in self.downgraded_tools
            ],
            "blocked_actions": self.blocked_actions,
            "notes": self.notes,
            "capability_snapshot": self.capability_snapshot,
        }


class EVPNCapabilityRegistry:
    def __init__(
        self,
        coverage_summary_path: str | Path | None = None,
        coverage_summary_data: dict[str, Any] | None = None,
    ) -> None:
        if coverage_summary_data is not None:
            raw = coverage_summary_data
        elif coverage_summary_path is not None:
            p = Path(coverage_summary_path)
            raw = json.loads(p.read_text())
        else:
            raw = {}

        if isinstance(raw, dict) and "vendor_summary" in raw and isinstance(raw["vendor_summary"], dict):
            self.coverage = raw["vendor_summary"]
        else:
            self.coverage = raw

    def get_capability_status(self, vendor: str, capability: str) -> CapabilityStatus:
        vendor_view = self.coverage.get(vendor, {}) or {}

        if capability in set(vendor_view.get("claimable_capabilities", []) or []):
            return CapabilityStatus(capability=capability, vendor=vendor, status="claimable")

        if capability in set(vendor_view.get("partial_capabilities", []) or []):
            return CapabilityStatus(capability=capability, vendor=vendor, status="partial")

        if capability in set(vendor_view.get("weak_capabilities", []) or []):
            return CapabilityStatus(capability=capability, vendor=vendor, status="weak")

        if capability in set(vendor_view.get("absent_capabilities", []) or []):
            return CapabilityStatus(capability=capability, vendor=vendor, status="absent")

        return CapabilityStatus(
            capability=capability,
            vendor=vendor,
            status="absent",
            rationale="Capability not present in vendor coverage summary.",
        )


class EVPNCapabilityBridge:
    def __init__(self, registry: EVPNCapabilityRegistry, policy_dir: str | Path | None = None) -> None:
        self.registry = registry
        if policy_dir is None:
            policy_dir = Path("internal/knowledge/policy/evpn")
        self.policy: EVPNPolicyBundle = load_evpn_policy_bundle(policy_dir)

    def govern(
        self,
        ctx: ProblemContext,
        reasoning: ReasoningOutput,
        plan: MCPPlan,
    ) -> GovernedMCPPlan:
        governed = GovernedMCPPlan(
            vendor=plan.vendor,
            scenario=plan.scenario,
            confidence=plan.confidence,
            risk_class=plan.risk_class,
            approval_required=plan.approval_required,
            execution_mode=plan.execution_mode,
            summary=plan.summary,
            blocked_actions=list(plan.blocked_actions),
            notes=list(plan.notes),
        )

        deduped_tools = self._dedupe_tools(plan.recommended_tools)

        for tool in deduped_tools:
            required_capabilities = self._required_capabilities_for_tool(
                tool_name=tool.tool_name,
                scenario=reasoning.scenario,
                explicit_capability=reasoning.capability,
            )

            statuses = [
                self.registry.get_capability_status(reasoning.vendor, cap)
                for cap in required_capabilities
            ]

            for s in statuses:
                governed.capability_snapshot[s.capability] = s.status

            missing = [s.capability for s in statuses if s.is_absent]
            weak = [s.capability for s in statuses if s.is_weak]
            partial = [s.capability for s in statuses if s.is_partial]
            checks = [f"{s.capability}:{s.status}" for s in statuses]

            if missing:
                governed.blocked_tools.append(
                    GovernedToolDecision(
                        tool_name=tool.tool_name,
                        allowed=False,
                        reason=(
                            "Blocked because one or more required capabilities are absent "
                            f"for vendor '{reasoning.vendor}'."
                        ),
                        read_only=tool.read_only,
                        capability_checks=checks,
                        missing_capabilities=missing,
                        downgraded=False,
                    )
                )
                continue

            if weak:
                governed.allowed_tools.append(tool)
                governed.downgraded_tools.append(
                    GovernedToolDecision(
                        tool_name=tool.tool_name,
                        allowed=True,
                        reason=(
                            "Allowed only as a downgraded read only inspection because one or more "
                            "required capabilities are weak."
                        ),
                        read_only=tool.read_only,
                        capability_checks=checks,
                        missing_capabilities=[],
                        downgraded=True,
                    )
                )
                continue

            if partial:
                governed.allowed_tools.append(tool)
                governed.downgraded_tools.append(
                    GovernedToolDecision(
                        tool_name=tool.tool_name,
                        allowed=True,
                        reason=(
                            "Allowed as read only inspection, but capability support is partial and "
                            "results should be treated as advisory."
                        ),
                        read_only=tool.read_only,
                        capability_checks=checks,
                        missing_capabilities=[],
                        downgraded=True,
                    )
                )
                continue

            governed.allowed_tools.append(tool)

        self._finalize_notes(governed, reasoning)
        self._finalize_actions(governed, reasoning)

        return governed

    def _dedupe_tools(self, tools: list[MCPToolCall]) -> list[MCPToolCall]:
        seen: set[tuple[str, str]] = set()
        out: list[MCPToolCall] = []

        for tool in tools:
            key = (tool.tool_name, json.dumps(tool.arguments, sort_keys=True, default=str))
            if key in seen:
                continue
            seen.add(key)
            out.append(tool)

        return out

    def _required_capabilities_for_tool(
        self,
        tool_name: str,
        scenario: str | None,
        explicit_capability: str | None,
    ) -> list[str]:
        tools = self.policy.tool_capability_policy.get("tools", {})
        required = list(tools.get(tool_name, {}).get("required_capabilities", []))

        if explicit_capability and explicit_capability not in required:
            required.append(explicit_capability)

        if not required and explicit_capability:
            required.append(explicit_capability)

        return required

    def _finalize_notes(self, governed: GovernedMCPPlan, reasoning: ReasoningOutput) -> None:
        if governed.downgraded_tools:
            governed.notes.append(
                "Some tool recommendations were downgraded because vendor capability coverage is partial or weak."
            )

        if governed.blocked_tools:
            governed.notes.append(
                "Some tool recommendations were blocked because required vendor capability coverage is absent."
            )

        if reasoning.confidence == "low":
            governed.notes.append(
                "Reasoning confidence is low, so the bridge preserves an evidence collection posture."
            )

    def _finalize_actions(self, governed: GovernedMCPPlan, reasoning: ReasoningOutput) -> None:
        if governed.blocked_tools:
            governed.blocked_actions.append(
                "Do not bypass blocked tool decisions without updating capability coverage or providing explicit override logic."
            )

        if governed.downgraded_tools:
            governed.blocked_actions.append(
                "Do not treat downgraded tool output as sufficient basis for remediation or capability claims."
            )


def pretty_print_governed_plan(plan: GovernedMCPPlan) -> None:
    print("=" * 120)
    print("GOVERNED EVPN MCP PLAN")
    print("=" * 120)
    print(f"Vendor            : {plan.vendor}")
    print(f"Scenario          : {plan.scenario}")
    print(f"Confidence        : {plan.confidence}")
    print(f"Risk class        : {plan.risk_class}")
    print(f"Approval required : {plan.approval_required}")
    print(f"Execution mode    : {plan.execution_mode}")
    print(f"Summary           : {plan.summary}")
    print()

    print("Capability snapshot:")
    for cap, status in sorted(plan.capability_snapshot.items()):
        print(f"  - {cap}: {status}")
    print()

    print("Allowed tools:")
    for tool in plan.allowed_tools:
        print(f"  - {tool.tool_name}")
        print(f"    intent    : {tool.intent}")
        print(f"    read_only : {tool.read_only}")
        print(f"    reason    : {tool.reason}")
        print(f"    arguments : {tool.arguments}")
    print()

    print("Downgraded tools:")
    for tool in plan.downgraded_tools:
        print(f"  - {tool.tool_name}")
        print(f"    allowed             : {tool.allowed}")
        print(f"    reason              : {tool.reason}")
        print(f"    capability_checks   : {tool.capability_checks}")
        print(f"    missing_capabilities: {tool.missing_capabilities}")
        print(f"    downgraded          : {tool.downgraded}")
    print()

    print("Blocked tools:")
    for tool in plan.blocked_tools:
        print(f"  - {tool.tool_name}")
        print(f"    allowed             : {tool.allowed}")
        print(f"    reason              : {tool.reason}")
        print(f"    capability_checks   : {tool.capability_checks}")
        print(f"    missing_capabilities: {tool.missing_capabilities}")
        print(f"    downgraded          : {tool.downgraded}")
    print()

    print("Blocked actions:")
    for item in plan.blocked_actions:
        print(f"  - {item}")
    print()

    print("Notes:")
    for item in plan.notes:
        print(f"  - {item}")
    print()
