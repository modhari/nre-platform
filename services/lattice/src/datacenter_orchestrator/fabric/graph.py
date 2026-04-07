"""
Fabric graph.

Converts normalized inventory records into a graph representation
that validators and planners can reason about.

Ruff notes
- Use builtin generics list, dict, set.
- Keep imports sorted.
- Avoid unused imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from datacenter_orchestrator.core.types import DeviceRecord, LinkKind
from datacenter_orchestrator.fabric.roles import (
    is_leaf_role,
    is_spine_role,
    is_super_spine_role,
)
from datacenter_orchestrator.inventory.store import InventoryStore


@dataclass(frozen=True)
class GraphEdge:
    """One adjacency entry in the fabric graph."""

    local_intf: str
    peer_device: str
    peer_intf: str
    kind: LinkKind


@dataclass
class FabricGraph:
    """
    FabricGraph stores the fabric topology in memory.

    nodes maps device name to DeviceRecord.
    adjacency maps device name to its outgoing edges.
    """

    nodes: dict[str, DeviceRecord]
    adjacency: dict[str, list[GraphEdge]] = field(default_factory=dict)

    def edges_from(self, device: str) -> list[GraphEdge]:
        """Return outgoing edges for a device."""
        return self.adjacency.get(device, [])

    def has_device(self, device: str) -> bool:
        """Return True if a device exists in the graph."""
        return device in self.nodes


def build_fabric_graph(store: InventoryStore) -> FabricGraph:
    """
    Build a FabricGraph from InventoryStore.

    Behavior
    - Add edges for each inventory link.
    - If the peer is managed, also add a reverse edge.
    """

    nodes = {d.name: d for d in store.all()}
    g = FabricGraph(nodes=nodes, adjacency={})

    for name in nodes:
        g.adjacency[name] = []

    for dev in store.all():
        for ln in dev.links:
            g.adjacency[dev.name].append(
                GraphEdge(
                    local_intf=ln.local_intf,
                    peer_device=ln.peer_device,
                    peer_intf=ln.peer_intf,
                    kind=ln.kind,
                )
            )

            # Add reverse edge for managed peers.
            if ln.peer_device in nodes:
                g.adjacency[ln.peer_device].append(
                    GraphEdge(
                        local_intf=ln.peer_intf,
                        peer_device=dev.name,
                        peer_intf=ln.local_intf,
                        kind=ln.kind,
                    )
                )

    return g


@dataclass
class TopologyValidationResult:
    """Result of CLOS topology validation."""

    ok: bool
    errors: list[str]
    warnings: list[str]
    evidence: dict[str, object]


def validate_clos_topology(g: FabricGraph) -> TopologyValidationResult:
    """
    Validate basic CLOS invariants.

    Validations
    1. Every leaf like device must have at least two fabric uplinks to spines.
    2. Spines should have fabric neighbors that are leaf like or super spine.
    3. If super spines exist, they must connect only to spines via fabric links.

    MLAG peer links are not counted as fabric uplinks.
    """

    errors: list[str] = []
    warnings: list[str] = []
    evidence: dict[str, object] = {}

    leaf_names: list[str] = []
    spine_names: list[str] = []
    super_spine_names: list[str] = []

    for dev in g.nodes.values():
        if is_leaf_role(dev.role):
            leaf_names.append(dev.name)
        elif is_spine_role(dev.role):
            spine_names.append(dev.name)
        elif is_super_spine_role(dev.role):
            super_spine_names.append(dev.name)

    evidence["device_counts"] = {
        "leaf_like": len(leaf_names),
        "spine_like": len(spine_names),
        "super_spine": len(super_spine_names),
    }

    def peer_role_class(peer: str) -> str | None:
        """
        Return a normalized role class string for a managed peer.
        Return None for unmanaged peers.
        """
        if peer not in g.nodes:
            return None

        role = g.nodes[peer].role
        if is_leaf_role(role):
            return "leaf_like"
        if is_spine_role(role):
            return "spine_like"
        if is_super_spine_role(role):
            return "super_spine"
        return "unknown"

    # Validation 1: leaf redundancy.
    leaf_uplink_evidence: dict[str, object] = {}
    for leaf in leaf_names:
        uplinks_to_spines = 0
        fabric_neighbors: set[str] = set()

        for e in g.edges_from(leaf):
            if e.kind != LinkKind.fabric:
                continue

            fabric_neighbors.add(e.peer_device)

            if peer_role_class(e.peer_device) == "spine_like":
                uplinks_to_spines += 1

        leaf_uplink_evidence[leaf] = {
            "fabric_uplinks_to_spines": uplinks_to_spines,
            "fabric_neighbor_count": len(fabric_neighbors),
        }

        if uplinks_to_spines < 2:
            errors.append(
                "leaf like device "
                f"{leaf} has only {uplinks_to_spines} fabric uplinks to spines, "
                "require at least 2"
            )

    evidence["leaf_uplinks"] = leaf_uplink_evidence

    # Validation 2: spine neighbor classes.
    spine_neighbor_evidence: dict[str, object] = {}
    for spine in spine_names:
        bad_neighbors: list[str] = []
        role_counts: dict[str, int] = {
            "leaf_like": 0,
            "spine_like": 0,
            "super_spine": 0,
            "unknown": 0,
        }

        for e in g.edges_from(spine):
            if e.kind != LinkKind.fabric:
                continue

            cls = peer_role_class(e.peer_device)
            if cls is None:
                role_counts["unknown"] += 1
                bad_neighbors.append(e.peer_device)
                continue

            role_counts[cls] = role_counts.get(cls, 0) + 1

            # Spines should connect to leaf like devices and super spines.
            if cls not in {"leaf_like", "super_spine"}:
                bad_neighbors.append(e.peer_device)

        spine_neighbor_evidence[spine] = {
            "fabric_neighbor_roles": role_counts,
            "bad_fabric_neighbors": sorted(set(bad_neighbors)),
        }

        if bad_neighbors:
            warnings.append(
                "spine like device "
                f"{spine} has unexpected fabric neighbors: {sorted(set(bad_neighbors))}"
            )

    evidence["spine_neighbors"] = spine_neighbor_evidence

    # Validation 3: super spine constraints.
    if super_spine_names:
        super_spine_evidence: dict[str, object] = {}

        for ss in super_spine_names:
            spine_bad_neighbors: list[str] = []
            spine_neighbor_count = 0

            for e in g.edges_from(ss):
                if e.kind != LinkKind.fabric:
                    continue

                if peer_role_class(e.peer_device) != "spine_like":
                    spine_bad_neighbors.append(e.peer_device)
                else:
                    spine_neighbor_count += 1

            super_spine_evidence[ss] = {
                "spine_neighbor_count": spine_neighbor_count,
                "bad_neighbors": sorted(set(spine_bad_neighbors)),
            }

            if bad_neighbors:
                errors.append(
                    "super spine "
                    f"{ss} has fabric neighbors that are not spines: {sorted(set(bad_neighbors))}"
                )

            if spine_neighbor_count == 0:
                errors.append(f"super spine {ss} has no spine neighbors via fabric links")

        evidence["super_spine_neighbors"] = super_spine_evidence

    ok = len(errors) == 0
    return TopologyValidationResult(ok=ok, errors=errors, warnings=warnings, evidence=evidence)
