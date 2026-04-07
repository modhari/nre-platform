from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.execution_plan import ExecutionPlan


@dataclass(frozen=True)
class PlanMemoryRecord:
    """
    Persisted memory of the last seen execution plan for one incident.
    """

    incident_id: str
    fingerprint: str
    safe_step_count: int
    gated_step_count: int
    skipped_action_count: int
    updated_at: str


def _memory_root() -> Path:
    """
    Resolve the local storage path for plan memory.

    This is intentionally file based for now.
    """
    root = os.environ.get("NRE_AGENT_PLAN_MEMORY_DIR", "/tmp/nre_agent_plan_memory")
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _memory_path(incident_id: str) -> Path:
    safe_name = (
        incident_id.replace(":", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(" ", "_")
    )
    return _memory_root() / f"{safe_name}.json"


def compute_plan_fingerprint(plan: ExecutionPlan) -> str:
    """
    Build a stable fingerprint from the semantically meaningful parts of a plan.

    We intentionally exclude cosmetic summary text and focus on:
    safe step ids
    gated step ids
    targets
    commands
    skipped actions
    execution flags
    """
    payload = {
        "incident_id": plan.incident_id,
        "execution_enabled": plan.execution_enabled,
        "approval_required": plan.approval_required,
        "safe_steps": [_step_fingerprint_payload(step) for step in plan.safe_steps],
        "gated_steps": [_step_fingerprint_payload(step) for step in plan.gated_steps],
        "skipped_actions": list(plan.skipped_actions),
        "metadata": dict(plan.metadata),
    }

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def get_plan_memory_record(incident_id: str) -> PlanMemoryRecord | None:
    """
    Read the last stored plan memory record for an incident.
    """
    path = _memory_path(incident_id)
    if not path.exists():
        return None

    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        return None

    return PlanMemoryRecord(
        incident_id=str(data.get("incident_id", incident_id)),
        fingerprint=str(data.get("fingerprint", "")),
        safe_step_count=int(data.get("safe_step_count", 0)),
        gated_step_count=int(data.get("gated_step_count", 0)),
        skipped_action_count=int(data.get("skipped_action_count", 0)),
        updated_at=str(data.get("updated_at", "")),
    )


def write_plan_memory_record(
    *,
    incident_id: str,
    fingerprint: str,
    safe_step_count: int,
    gated_step_count: int,
    skipped_action_count: int,
    updated_at: str,
) -> PlanMemoryRecord:
    """
    Persist the latest plan memory record.
    """
    record = PlanMemoryRecord(
        incident_id=incident_id,
        fingerprint=fingerprint,
        safe_step_count=safe_step_count,
        gated_step_count=gated_step_count,
        skipped_action_count=skipped_action_count,
        updated_at=updated_at,
    )

    _memory_path(incident_id).write_text(
        json.dumps(
            {
                "incident_id": record.incident_id,
                "fingerprint": record.fingerprint,
                "safe_step_count": record.safe_step_count,
                "gated_step_count": record.gated_step_count,
                "skipped_action_count": record.skipped_action_count,
                "updated_at": record.updated_at,
            },
            indent=2,
        )
    )
    return record


def classify_plan_change(
    *,
    incident_id: str,
    current_fingerprint: str,
) -> str:
    """
    Classify the current plan relative to the last stored one.

    Returns:
    new
    unchanged
    materially_changed
    """
    previous = get_plan_memory_record(incident_id)
    if previous is None:
        return "new"

    if previous.fingerprint == current_fingerprint:
        return "unchanged"

    return "materially_changed"


def _step_fingerprint_payload(step: Any) -> dict[str, Any]:
    return {
        "step_id": getattr(step, "step_id", ""),
        "step_type": getattr(step, "step_type", ""),
        "target": getattr(step, "target", {}),
        "commands": getattr(step, "commands", []),
        "approval_required": getattr(step, "approval_required", False),
        "blocked": getattr(step, "blocked", False),
    }
