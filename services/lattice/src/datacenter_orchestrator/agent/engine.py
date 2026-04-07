"""
Orchestration engine.

This engine coordinates:
planning, risk evaluation, optional guarded execution, verification, rollback,
and alert emission.

Determinism and safety
The planner remains deterministic.
Risk assessment is deterministic by default.
A tool hook can enrich evaluation but should not bypass guardrails.

ECMP enrichment
This version can call MCP trace_ecmp_path and use returned
data plane information to enrich the base risk assessment.

Adaptive endpoint selection
This version derives trace endpoints from the actual plan and inventory
instead of using fixed source and destination values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from datacenter_orchestrator.agent.execution_mode import ExecutionMode
from datacenter_orchestrator.agent.guard import ExecutionGuard, GuardDecision
from datacenter_orchestrator.core.types import IntentChange
from datacenter_orchestrator.execution.base import PlanExecutor
from datacenter_orchestrator.inventory.store import InventoryStore
from datacenter_orchestrator.planner.planner import DeterministicPlanner
from datacenter_orchestrator.planner.risk import PlanRiskAssessment, RiskLevel, assess_plan_risk
from datacenter_orchestrator.planner.rollback import build_rollback_plan
from datacenter_orchestrator.planner.verification import evaluate_verification


@dataclass(frozen=True)
class EngineAlert:
    """
    Alert produced by a failed orchestration run.
    """

    severity: str
    summary: str
    risk: PlanRiskAssessment | None
    verification_failures: list[str]
    rollback_attempted: bool


@dataclass(frozen=True)
class EngineRunResult:
    ok: bool
    plan: Any | None
    risk: PlanRiskAssessment | None
    guard: GuardDecision | None
    alert: EngineAlert | None


class OrchestrationEngine:
    """
    Orchestration engine.

    planner
    Deterministic planner that converts intent to a change plan.

    executor
    Applies plan to devices.

    guard
    Decides whether the engine is allowed to apply.

    evaluation_tool
    Optional tool hook for MCP integration.
    If present, it can be used to produce risk assessment and
    optional ECMP aware enrichment.
    """

    def __init__(
        self,
        planner: DeterministicPlanner,
        executor: PlanExecutor,
        guard: ExecutionGuard | None = None,
        evaluation_tool: Any | None = None,
    ) -> None:
        self._planner = planner
        self._executor = executor
        self._guard = guard or ExecutionGuard()
        self._evaluation_tool = evaluation_tool

    def _evaluate_risk(self, plan: Any, inventory: InventoryStore) -> PlanRiskAssessment:
        """
        Evaluate plan risk.

        Step 1
        Get a base risk assessment from MCP or deterministic local logic.

        Step 2
        If MCP generic capability calling is available, call trace_ecmp_path
        and enrich the base assessment with data plane observations.

        Important
        PlanRiskAssessment is immutable, so enrichment must construct and return
        a new instance rather than mutating the existing one.
        """
        if self._evaluation_tool is not None:
            tool = self._evaluation_tool
            base_risk = tool.evaluate_plan(plan, inventory)
        else:
            base_risk = assess_plan_risk(plan, inventory)

        if self._evaluation_tool is None:
            return base_risk

        try:
            tool = self._evaluation_tool

            source, destination = self._derive_trace_endpoints(plan, inventory)

            if not source or not destination or source == destination:
                return base_risk

            trace = tool.call(
                method="trace_ecmp_path",
                params={
                    "source": source,
                    "destination": destination,
                    "mode": "data_plane",
                    "flow": {
                        "src_ip": "1.1.1.1",
                        "dst_ip": "10.1.1.1",
                        "src_port": 12345,
                        "dst_port": 443,
                        "protocol": "tcp",
                    },
                },
            )

            if not trace or not trace.get("ok"):
                return base_risk

            result = trace.get("result", {})
            ecmp_width = int(result.get("ecmp_width", 1))
            paths = result.get("paths", [])

            enriched_blast_radius = int(base_risk.blast_radius_score)
            enriched_reasons = list(base_risk.reasons)
            enriched_evidence = dict(base_risk.evidence)

            base_reasons_text = " ".join(enriched_reasons).lower()

            is_interface_change = "interface configuration change detected" in base_reasons_text
            is_routing_change = (
                "bgp" in base_reasons_text
                or "ospf" in base_reasons_text
                or "protocol" in base_reasons_text
            )

            spine_seen = False
            for path in paths:
                hops = path.get("hops", [])
                for hop in hops:
                    node = str(hop.get("node", ""))
                    if "spine" in node:
                        spine_seen = True
                        break
                if spine_seen:
                    break

            if ecmp_width > 1:
                if is_routing_change:
                    enriched_blast_radius += 15
                    enriched_reasons.append(
                        "ecmp multi path detected increases routing uncertainty"
                    )
                elif is_interface_change:
                    enriched_blast_radius += 5
                    enriched_reasons.append(
                        "ecmp multi path detected adds limited uncertainty"
                    )
                else:
                    enriched_blast_radius += 10
                    enriched_reasons.append(
                        "ecmp multi path detected increases uncertainty"
                    )

            if spine_seen:
                if is_routing_change:
                    enriched_blast_radius += 15
                    enriched_reasons.append(
                        "data plane path traverses spine tier during routing sensitive change"
                    )
                elif is_interface_change:
                    enriched_blast_radius += 5
                    enriched_reasons.append(
                        "data plane path traverses spine tier"
                    )
                else:
                    enriched_blast_radius += 10
                    enriched_reasons.append(
                        "data plane path traverses spine tier"
                    )

            enriched_evidence["ecmp"] = {
                "source": source,
                "destination": destination,
                "ecmp_width": ecmp_width,
                "path_count": len(paths),
                "spine_seen": spine_seen,
            }

            if enriched_blast_radius >= 50:
                enriched_risk_level = RiskLevel.high
                enriched_requires_approval = True
            elif enriched_blast_radius >= 20:
                enriched_risk_level = RiskLevel.medium
                enriched_requires_approval = False
            else:
                enriched_risk_level = RiskLevel.low
                enriched_requires_approval = False

            return PlanRiskAssessment(
                risk_level=enriched_risk_level,
                blast_radius_score=enriched_blast_radius,
                requires_approval=enriched_requires_approval,
                reasons=enriched_reasons,
                evidence=enriched_evidence,
            )

        except Exception as exc:
            print(f"[engine] ecmp enrichment failed: {exc}", flush=True)
            return base_risk

    def _derive_trace_endpoints(self, plan: Any, inventory: InventoryStore) -> tuple[str, str]:
        """
        Derive trace source and destination from plan and inventory.

        Strategy
        1. Use the first touched device in the plan as source.
        2. Prefer a directly linked peer as destination.
        3. If no link is present, choose another device in inventory.
        """
        plan_devices: list[str] = []
        for action in getattr(plan, "actions", []):
            device = getattr(action, "device", "")
            if device:
                plan_devices.append(device)

        if not plan_devices:
            return "", ""

        source = plan_devices[0]

        inventory_devices = getattr(inventory, "_devices", {})
        source_record = inventory_devices.get(source)

        if source_record is not None:
            links = getattr(source_record, "links", [])
            for link in links:
                peer_device = getattr(link, "peer_device", "")
                if peer_device and peer_device != source:
                    return source, peer_device

        for device_name in inventory_devices.keys():
            if device_name != source:
                return source, str(device_name)

        return source, ""

    def run_once(self, intent: IntentChange, inventory: InventoryStore) -> EngineRunResult:
        """
        Execute a single intent change.

        Steps
        1) plan
        2) risk assess
        3) guard decision
        4) apply or simulate or dry run
        5) verify
        6) rollback on failure
        """
        plan = self._planner.plan_change(intent, inventory)
        risk = self._evaluate_risk(plan, inventory)
        guard = self._guard.decide(risk)

        if guard.mode == ExecutionMode.dry_run:
            alert = EngineAlert(
                severity="info",
                summary="dry run only, plan not applied",
                risk=risk,
                verification_failures=[],
                rollback_attempted=False,
            )
            return EngineRunResult(
                ok=False,
                plan=plan,
                risk=risk,
                guard=guard,
                alert=alert,
            )

        if guard.mode == ExecutionMode.simulate:
            observed = self._simulate_observed_state(plan)
            outcome = evaluate_verification(plan.verification, observed)

            if outcome.ok:
                return EngineRunResult(
                    ok=True,
                    plan=plan,
                    risk=risk,
                    guard=guard,
                    alert=None,
                )

            alert = EngineAlert(
                severity="warning",
                summary="simulation verification failed, plan not applied",
                risk=risk,
                verification_failures=outcome.failures,
                rollback_attempted=False,
            )
            return EngineRunResult(
                ok=False,
                plan=plan,
                risk=risk,
                guard=guard,
                alert=alert,
            )

        observed_state, pre_snapshot = self._executor.apply_plan(plan)
        outcome = evaluate_verification(plan.verification, observed_state)

        if outcome.ok:
            return EngineRunResult(
                ok=True,
                plan=plan,
                risk=risk,
                guard=guard,
                alert=None,
            )

        rollback_attempted = False
        if plan.rollback.enabled:
            rollback_attempted = True
            rb = build_rollback_plan(plan, pre_snapshot)
            self._executor.apply_plan(rb.plan)

        alert = EngineAlert(
            severity="critical",
            summary="verification failed after apply",
            risk=risk,
            verification_failures=outcome.failures,
            rollback_attempted=rollback_attempted,
        )
        return EngineRunResult(
            ok=False,
            plan=plan,
            risk=risk,
            guard=guard,
            alert=alert,
        )

    def _simulate_observed_state(self, plan: Any) -> dict[str, dict[str, Any]]:
        """
        Build a simulated observed state.

        Simulation rule
        Treat desired model paths as already applied.

        This is intentionally simple. Later you can plug in a fabric simulator
        that models adjacency changes or routing convergence.
        """
        observed: dict[str, dict[str, Any]] = {}
        for act in plan.actions:
            observed[act.device] = dict(act.model_paths)
        return observed
