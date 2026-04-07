from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DecisionAction:
    action_id: str
    title: str
    summary: str
    action_type: str
    risk_level: str
    approval_required: bool
    blocked: bool
    target: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    prerequisites: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    rollback_hint: str | None = None
    suppressed_action_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BgpDecision:
    incident_id: str
    summary: str
    root_cause: str
    fabric: str
    device: str
    execution_enabled: bool
    approval_required: bool
    safe_actions: list[DecisionAction] = field(default_factory=list)
    gated_actions: list[DecisionAction] = field(default_factory=list)
    suppressed_actions: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


def build_bgp_decision(response: dict[str, Any]) -> BgpDecision:
    """
    Supports BOTH shapes:

    OLD:
        {
            "fabric": "...",
            "device": "...",
            "diagnosis": {...}
        }

    NEW (MCP direct):
        {
            "summary": "...",
            "root_cause": "...",
            "proposed_actions": [...],
            "alert": {...}
        }
    """

    if not isinstance(response, dict):
        response = {}

    raw_diagnosis = response.get("diagnosis")

    if isinstance(raw_diagnosis, dict):
        diagnosis = raw_diagnosis
        fabric = str(response.get("fabric", "default"))
        device = str(response.get("device", "unknown"))
    else:
        diagnosis = response
        fabric = str(
            diagnosis.get("fabric")
            or diagnosis.get("context", {}).get("fabric")
            or "default"
        )
        device = str(
            diagnosis.get("device")
            or diagnosis.get("context", {}).get("device")
            or "unknown"
        )

    # 🔥 Infer fabric/device from action targets if missing
    fabric, device = _infer_fabric_and_device(diagnosis, fabric, device)

    alert = diagnosis.get("alert")
    if not isinstance(alert, dict):
        alert = None

    approval_summary = diagnosis.get("approval_summary", {})
    if not isinstance(approval_summary, dict):
        approval_summary = {}

    incident_id = _build_incident_id(
        fabric=fabric,
        device=device,
        diagnosis=diagnosis,
        alert=alert,
    )

    raw_actions = diagnosis.get("proposed_actions", [])
    if not isinstance(raw_actions, list):
        raw_actions = []

    safe_actions: list[DecisionAction] = []
    gated_actions: list[DecisionAction] = []
    suppressed_actions: list[str] = []

    if alert is not None:
        consolidated_gated, suppressed = _consolidate_gated_actions(
            incident_id=incident_id,
            raw_actions=raw_actions,
        )
        gated_actions.extend(consolidated_gated)
        suppressed_actions.extend(suppressed)

        for item in raw_actions:
            action = _to_decision_action(item)
            if action is None:
                continue

            if action.approval_required:
                continue

            safe_actions.append(action)
    else:
        for item in raw_actions:
            action = _to_decision_action(item)
            if action is None:
                continue

            if action.approval_required:
                gated_actions.append(action)
            else:
                safe_actions.append(action)

    safe_actions = _dedupe_actions_preserve_order(safe_actions)
    gated_actions = _dedupe_actions_preserve_order(gated_actions)

    approval_required = bool(
        approval_summary.get("approval_required_count", 0) > 0
    )

    return BgpDecision(
        incident_id=incident_id,
        summary=str(diagnosis.get("summary", "BGP decision generated")),
        root_cause=str(diagnosis.get("root_cause", "unknown")),
        fabric=fabric,
        device=device,
        execution_enabled=bool(
            approval_summary.get("execution_enabled", False)
        ),
        approval_required=approval_required,
        safe_actions=safe_actions,
        gated_actions=gated_actions,
        suppressed_actions=suppressed_actions,
        evidence={
            "validation_summary": diagnosis.get("validation_summary", {}),
            "diagnosis_counts": diagnosis.get("diagnosis_counts", {}),
            "alert": alert,
        },
    )


def decision_to_dict(decision: BgpDecision) -> dict[str, Any]:
    return {
        "incident_id": decision.incident_id,
        "summary": decision.summary,
        "root_cause": decision.root_cause,
        "fabric": decision.fabric,
        "device": decision.device,
        "execution_enabled": decision.execution_enabled,
        "approval_required": decision.approval_required,
        "safe_actions": [_action_to_dict(a) for a in decision.safe_actions],
        "gated_actions": [_action_to_dict(a) for a in decision.gated_actions],
        "suppressed_actions": decision.suppressed_actions,
        "evidence": decision.evidence,
    }


def summarize_bgp_decision(decision: BgpDecision) -> str:
    return (
        f"[nre_agent] incident_id={decision.incident_id} "
        f"root_cause={decision.root_cause} "
        f"fabric={decision.fabric} device={decision.device} "
        f"safe_actions={len(decision.safe_actions)} "
        f"gated_actions={len(decision.gated_actions)} "
        f"suppressed_actions={len(decision.suppressed_actions)} "
        f"approval_required={decision.approval_required} "
        f"execution_enabled={decision.execution_enabled}"
    )


# -----------------------------
# Helpers
# -----------------------------


def _infer_fabric_and_device(
    diagnosis: dict[str, Any],
    fabric: str,
    device: str,
) -> tuple[str, str]:

    if fabric != "default" and device != "unknown":
        return fabric, device

    raw_actions = diagnosis.get("proposed_actions", [])
    if not isinstance(raw_actions, list):
        return fabric, device

    for item in raw_actions:
        if not isinstance(item, dict):
            continue

        target = item.get("target", {})
        if not isinstance(target, dict):
            continue

        if fabric == "default":
            inferred = target.get("fabric")
            if inferred:
                fabric = str(inferred)

        if device == "unknown":
            inferred = target.get("device")
            if inferred:
                device = str(inferred)

        if fabric != "default" and device != "unknown":
            break

    return fabric, device


def _build_incident_id(
    *,
    fabric: str,
    device: str,
    diagnosis: dict[str, Any],
    alert: dict[str, Any] | None,
) -> str:
    if alert is not None and "dedupe_key" in alert:
        return str(alert["dedupe_key"])

    root_cause = str(diagnosis.get("root_cause", "unknown"))
    return f"fabric:{fabric}:device:{device}:root:{root_cause}"


def _to_decision_action(item: Any) -> DecisionAction | None:
    if not isinstance(item, dict):
        return None

    return DecisionAction(
        action_id=str(item.get("action_id", "unknown")),
        title=str(item.get("title", "")),
        summary=str(item.get("summary", "")),
        action_type=str(item.get("action_type", "")),
        risk_level=str(item.get("risk_level", "low")),
        approval_required=bool(item.get("approval_required", False)),
        blocked=bool(item.get("blocked", False)),
        target=item.get("target", {}) or {},
        rationale=str(item.get("rationale", "")),
        prerequisites=item.get("prerequisites", []) or [],
        commands=item.get("commands", []) or [],
        rollback_hint=item.get("rollback_hint"),
    )


def _dedupe_actions_preserve_order(actions: list[DecisionAction]) -> list[DecisionAction]:
    seen = set()
    result = []
    for a in actions:
        if a.action_id in seen:
            continue
        seen.add(a.action_id)
        result.append(a)
    return result


def _consolidate_gated_actions(
    *,
    incident_id: str,
    raw_actions: list[dict[str, Any]],
) -> tuple[list[DecisionAction], list[str]]:

    grouped: dict[str, list[dict[str, Any]]] = {}
    suppressed: list[str] = []

    for item in raw_actions:
        if not isinstance(item, dict):
            continue
        if not item.get("approval_required"):
            continue

        key = item.get("action_type", "unknown")
        grouped.setdefault(key, []).append(item)

    consolidated: list[DecisionAction] = []

    for key, items in grouped.items():
        primary = items[0]
        suppressed.extend(
            str(i.get("action_id")) for i in items[1:] if "action_id" in i
        )

        consolidated.append(_to_decision_action(primary))

    return consolidated, suppressed


def _action_to_dict(action: DecisionAction) -> dict[str, Any]:
    return {
        "action_id": action.action_id,
        "title": action.title,
        "summary": action.summary,
        "action_type": action.action_type,
        "risk_level": action.risk_level,
        "approval_required": action.approval_required,
        "blocked": action.blocked,
        "target": action.target,
        "rationale": action.rationale,
        "prerequisites": action.prerequisites,
        "commands": action.commands,
        "rollback_hint": action.rollback_hint,
    }
