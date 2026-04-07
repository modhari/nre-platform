"""
Plan risk analysis.

Purpose
Before executing a change, we want a deterministic risk assessment that is:
1) explainable
2) repeatable
3) fabric aware

This is the first step toward agentic behavior, because it turns context into a
decision that can change how the engine executes.

Important
This module must remain deterministic.
Do not call external models from here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from datacenter_orchestrator.core.types import ChangePlan
from datacenter_orchestrator.fabric.roles import (
    is_leaf_role,
    is_spine_role,
    is_super_spine_role,
)
from datacenter_orchestrator.inventory.store import InventoryStore


class RiskLevel(StrEnum):
    """Coarse risk level for a plan."""

    low = "low"
    medium = "medium"
    high = "high"


@dataclass(frozen=True)
class PlanRiskAssessment:
    """
    Risk assessment result.

    risk_level
    A coarse level to drive guardrails.

    blast_radius_score
    A simple numeric score to compare plans.

    requires_approval
    When True, engine should not apply automatically.

    reasons
    Human readable reasons for the risk result.

    evidence
    Structured evidence for alerts or audit logs.
    """

    risk_level: RiskLevel
    blast_radius_score: int
    requires_approval: bool
    reasons: list[str]
    evidence: dict[str, Any]


def assess_plan_risk(
    plan: ChangePlan,
    inventory: InventoryStore,
) -> PlanRiskAssessment:
    """
    Assess risk using simple deterministic heuristics.

    Heuristics used
    1) device count touched
    2) role tier criticality
    3) whether any action touches external connectivity paths
    4) whether BGP or OSPF related paths are modified

    This can be extended later with more fabric policies, capacity impact,
    and dependency graphs.
    """

    reasons: list[str] = []
    evidence: dict[str, Any] = {}

    devices_touched: list[str] = [a.device for a in plan.actions]
    unique_devices = sorted(set(devices_touched))
    device_count = len(unique_devices)

    evidence["device_count"] = device_count
    evidence["devices"] = unique_devices

    leaf_count = 0
    spine_count = 0
    super_spine_count = 0
    unknown_count = 0

    touches_external = False
    touches_bgp = False
    touches_ospf = False

    for act in plan.actions:
        dev = inventory.get(act.device)
        if dev is None:
            unknown_count += 1
        else:
            if is_super_spine_role(dev.role):
                super_spine_count += 1
            elif is_spine_role(dev.role):
                spine_count += 1
            elif is_leaf_role(dev.role):
                leaf_count += 1
            else:
                unknown_count += 1

        for path in act.model_paths.keys():
            p = str(path).lower()
            if "bgp" in p:
                touches_bgp = True
            if "ospf" in p:
                touches_ospf = True
            if "external" in p or "internet" in p or "wan" in p:
                touches_external = True

    evidence["role_counts"] = {
        "leaf": leaf_count,
        "spine": spine_count,
        "super_spine": super_spine_count,
        "unknown": unknown_count,
    }
    evidence["touches"] = {
        "external": touches_external,
        "bgp": touches_bgp,
        "ospf": touches_ospf,
    }

    blast = 0

    blast += device_count * 10
    blast += spine_count * 15
    blast += super_spine_count * 25

    if unknown_count:
        blast += 20
        reasons.append("plan references devices missing from inventory")

    if touches_external:
        blast += 30
        reasons.append("plan touches external connectivity related paths")

    if touches_bgp:
        blast += 20
        reasons.append("plan modifies bgp related model paths")

    if touches_ospf:
        blast += 15
        reasons.append("plan modifies ospf related model paths")

    if super_spine_count:
        reasons.append("plan touches super spine tier which impacts large blast radius")

    if spine_count and device_count <= 2:
        reasons.append("plan touches spine tier even though device count is small")

    if device_count <= 2 and not (touches_external or touches_bgp or touches_ospf):
        risk_level = RiskLevel.low
    elif blast < 80:
        risk_level = RiskLevel.medium
    else:
        risk_level = RiskLevel.high

    requires_approval = risk_level == RiskLevel.high or touches_external or super_spine_count > 0

    if not reasons:
        reasons.append("risk computed from device count and role tier impact")

    return PlanRiskAssessment(
        risk_level=risk_level,
        blast_radius_score=blast,
        requires_approval=requires_approval,
        reasons=reasons,
        evidence=evidence,
    )
