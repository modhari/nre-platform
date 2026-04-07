"""
Core types.

This file defines shared data structures used across the engine.

Ruff notes
- We use builtin generics like list and dict instead of typing.List and typing.Dict.
- We use PEP 604 unions like X | None instead of Optional[X].
- We use enum.StrEnum instead of inheriting from both str and Enum.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class DeviceRole(StrEnum):
    """
    Device roles in a CLOS fabric.

    leaf
      Server facing leaf.

    spine
      Spine in a two tier or three tier design.

    super_spine
      Optional third tier for very large fabrics.

    border_leaf
      Leaf used for external connectivity in a border pod model.

    border_spine
      Used when smaller fabrics connect externally via spines.
      In that model, all spines must connect externally.

    services_leaf
      Leaf dedicated to service appliances.

    edge_leaf
      Optional role for edge aggregation patterns.
    """

    leaf = "leaf"
    spine = "spine"
    super_spine = "super_spine"
    border_leaf = "border_leaf"
    border_spine = "border_spine"
    services_leaf = "services_leaf"
    edge_leaf = "edge_leaf"


class LinkKind(StrEnum):
    """
    Link classification.

    fabric
      Internal CLOS fabric link.

    mlag_peer
      Leaf to leaf peer link used for MLAG pairs.

    external
      External neighbor not managed in inventory.

    internet
      External link intended for internet facing connectivity.

    wan
      External link intended for private WAN connectivity.
    """

    fabric = "fabric"
    mlag_peer = "mlag_peer"
    external = "external"
    internet = "internet"
    wan = "wan"


class Confidence(StrEnum):
    """
    Confidence for derived facts.

    high means we observed it directly from device or trusted source
    medium means inferred from multiple signals
    low means heuristic or incomplete evidence
    """

    high = "high"
    medium = "medium"
    low = "low"


@dataclass(frozen=True)
class Evidence:
    """
    Evidence explains why we believe a derived fact is true.

    source might be netbox, gnmi, napalm, or a capability catalog
    detail captures a short reason string
    """

    source: str
    detail: str


@dataclass
class CapabilityClass:
    """
    A normalized capability classification.

    We store normalized classes instead of raw numbers because the orchestrator
    often makes decisions in buckets such as:
    small, medium, large table scale
    low, medium, high buffers
    """

    name: str
    confidence: Confidence
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class DeviceIdentity:
    """Vendor identity used by adapter selection and reporting."""

    vendor: str
    model: str
    os_name: str
    os_version: str
    serial: str = ""


@dataclass
class DeviceEndpoints:
    """
    How to reach a device.

    gnmi_host and gnmi_port are used for model driven gNMI over gRPC.
    """

    mgmt_host: str
    gnmi_host: str
    gnmi_port: int = 57400


@dataclass
class FabricLocation:
    """
    Fabric location.

    pod groups devices into failure domains and scaling units.
    rack supports placement aware planning.
    plane supports multi plane fabrics later.
    """

    pod: str
    rack: str
    plane: str = "default"


@dataclass
class Link:
    """
    Link from one device interface to a peer.

    peer_device may be a managed device name, or an external placeholder.
    """

    local_intf: str
    peer_device: str
    peer_intf: str
    kind: LinkKind = LinkKind.fabric


@dataclass
class DeviceRecord:
    """
    Normalized inventory record.

    links comes from inventory sources like NetBox.
    capability fields are enriched by plugins.
    """

    name: str
    role: DeviceRole
    identity: DeviceIdentity
    endpoints: DeviceEndpoints
    location: FabricLocation
    links: list[Link] = field(default_factory=list)

    bandwidth_class: CapabilityClass | None = None
    asic_class: CapabilityClass | None = None
    buffer_class: CapabilityClass | None = None
    table_scale_class: CapabilityClass | None = None
    telemetry_class: CapabilityClass | None = None

    role_fitness: dict[str, CapabilityClass] = field(default_factory=dict)


@dataclass
class IntentChange:
    """
    IntentChange represents a desired state update.

    desired and current are untyped dictionaries because different sources will
    represent intent differently. The planner interprets them.
    """

    change_id: str
    scope: str
    desired: dict[str, Any]
    current: dict[str, Any]
    diff_summary: str


@dataclass
class ChangeAction:
    """
    A single device action produced by the planner.

    model_paths maps model path strings to desired values.
    """

    device: str
    model_paths: dict[str, Any]
    reason: str


@dataclass
class VerificationSpec:
    """
    Verification specification.

    checks are deterministic state checks.
    probes are active probes.
    """

    checks: list[dict[str, Any]]
    probes: list[dict[str, Any]]
    window_seconds: int = 60


@dataclass
class RollbackSpec:
    """Rollback specification, including triggers."""

    enabled: bool = True
    triggers: list[str] = field(default_factory=list)


@dataclass
class ChangePlan:
    """
    ChangePlan is the structured output of the planner.

    risk is a coarse string used by policy gate rules.
    explanation is stored for audit and operator review.
    """

    plan_id: str
    actions: list[ChangeAction]
    verification: VerificationSpec
    rollback: RollbackSpec
    risk: str
    explanation: str
