"""
Fabric role helpers.

Why this file exists
The inventory store includes a role field, but the fabric logic often needs to ask questions like:

- Is this a leaf like device, meaning it has servers or services southbound
- Is this a spine like device, meaning it is only fabric transit
- Is this a border role, meaning it participates in external connectivity

We keep these helpers centralized so validation and planning remain consistent.
"""

from __future__ import annotations

from datacenter_orchestrator.core.types import DeviceRole


def is_leaf_role(role: DeviceRole) -> bool:
    """
    Return True if this role behaves like a leaf in topology terms.

    This includes:
    leaf
    border_leaf
    services_leaf
    edge_leaf

    Even though border_leaf connects externally, it still behaves like a leaf
    in the internal fabric.
    """
    return role in {
        DeviceRole.leaf,
        DeviceRole.border_leaf,
        DeviceRole.services_leaf,
        DeviceRole.edge_leaf,
    }


def is_spine_role(role: DeviceRole) -> bool:
    """
    Return True if this role behaves like a spine layer.

    spine and border_spine both behave like spines internally.
    The difference is that border_spine is allowed external connectivity.
    """
    return role in {DeviceRole.spine, DeviceRole.border_spine}


def is_super_spine_role(role: DeviceRole) -> bool:
    """
    Return True if this role is super spine.

    Super spines are only present in three tier designs.
    """
    return role == DeviceRole.super_spine


def is_border_role(role: DeviceRole) -> bool:
    """
    Return True if this role is intended to connect externally.

    In a border pod model, border_leaf is the role that connects externally.
    In a spine external model, border_spine or spine may connect externally,
    but the policy requires symmetry across the spine layer.
    """
    return role in {DeviceRole.border_leaf, DeviceRole.border_spine}
