"""
External connectivity policy.

Border pod or border leaf model
- Internal routing protocols stay isolated from external routing.
- Only border leaves should connect to external networks.

Spine external model for smaller networks
- If spines connect to the external world, all spines must do so.
- Partial external connectivity breaks CLOS symmetry and can cause congestion.

This policy runs after topology validation and before any config is applied.
"""

from __future__ import annotations

from dataclasses import dataclass

from datacenter_orchestrator.core.types import DeviceRole, LinkKind
from datacenter_orchestrator.fabric.graph import FabricGraph
from datacenter_orchestrator.fabric.roles import is_spine_role


@dataclass
class ExternalConnectivityPolicyResult:
    """Result of external connectivity validation."""

    ok: bool
    errors: list[str]
    warnings: list[str]
    evidence: dict[str, object]


def validate_external_connectivity(g: FabricGraph) -> ExternalConnectivityPolicyResult:
    """
    Validate external connectivity architecture.

    Rule 1
    If any border_leaf devices exist, treat the design as border pod model.
    - At least one border_leaf must have an external link.
    - If spines also have external links, warn because it is mixed mode.

    Rule 2
    If no border_leaf devices exist, treat the design as spine external model.
    - If any spine has an external link, then all spines must have one.

    What counts as external
    LinkKind external, internet, wan.
    """

    errors: list[str] = []
    warnings: list[str] = []
    evidence: dict[str, object] = {}

    border_leafs = [d for d in g.nodes.values() if d.role == DeviceRole.border_leaf]
    spines = [d for d in g.nodes.values() if is_spine_role(d.role)]

    external_kinds = {LinkKind.external, LinkKind.internet, LinkKind.wan}

    spines_with_external: list[str] = []
    border_leafs_with_external: list[str] = []
    other_with_external: list[str] = []

    for dev in g.nodes.values():
        for e in g.edges_from(dev.name):
            if e.kind not in external_kinds:
                continue

            if dev.role == DeviceRole.border_leaf:
                border_leafs_with_external.append(dev.name)
            elif is_spine_role(dev.role):
                spines_with_external.append(dev.name)
            else:
                other_with_external.append(dev.name)

    if border_leafs:
        if not border_leafs_with_external:
            errors.append(
                "border_leaf role present but no border_leaf has external connectivity"
            )

        if spines_with_external:
            warnings.append(
                "border_leaf model detected but spines also have external links. "
                "Verify design intent."
            )

        if other_with_external:
            warnings.append(
                f"non border devices have external links: {sorted(set(other_with_external))}"
            )
    else:
        if spines:
            if 0 < len(set(spines_with_external)) < len(spines):
                errors.append(
                    "partial spine external connectivity detected. "
                    "If spines connect externally, all spines must connect externally."
                )

    evidence["external_connectivity_counts"] = {
        "border_leaf_count": len(border_leafs),
        "spine_count": len(spines),
        "border_leafs_with_external": len(set(border_leafs_with_external)),
        "spines_with_external": len(set(spines_with_external)),
        "other_with_external": len(set(other_with_external)),
    }
    evidence["external_connectivity_nodes"] = {
        "border_leafs_with_external": sorted(set(border_leafs_with_external)),
        "spines_with_external": sorted(set(spines_with_external)),
        "other_with_external": sorted(set(other_with_external)),
    }

    ok = len(errors) == 0
    return ExternalConnectivityPolicyResult(
        ok=ok,
        errors=errors,
        warnings=warnings,
        evidence=evidence,
    )
