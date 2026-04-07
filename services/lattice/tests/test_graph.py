from datacenter_orchestrator.core.types import (
    DeviceEndpoints,
    DeviceIdentity,
    DeviceRecord,
    DeviceRole,
    FabricLocation,
    Link,
    LinkKind,
)
from datacenter_orchestrator.fabric.graph import build_fabric_graph, validate_clos_topology
from datacenter_orchestrator.inventory.store import InventoryStore


def make_device(name: str, role: DeviceRole) -> DeviceRecord:
    """
    Helper to create a minimal DeviceRecord for tests.

    We keep identity and endpoints as placeholders.
    Topology validation cares about roles and links.
    """
    return DeviceRecord(
        name=name,
        role=role,
        identity=DeviceIdentity(vendor="demo", model="demo", os_name="demo", os_version="1"),
        endpoints=DeviceEndpoints(mgmt_host="10.0.0.1", gnmi_host="10.0.0.1"),
        location=FabricLocation(pod="pod1", rack="r1"),
    )


def test_two_tier_topology_passes_basic_validation():
    """
    Build a minimal valid two tier topology.

    leaf1 has two fabric uplinks to spines
    leaf2 has two fabric uplinks to spines
    """
    store = InventoryStore()

    leaf1 = make_device("leaf1", DeviceRole.leaf)
    leaf2 = make_device("leaf2", DeviceRole.leaf)
    spine1 = make_device("spine1", DeviceRole.spine)
    spine2 = make_device("spine2", DeviceRole.spine)

    leaf1.links.extend(
        [
            Link(local_intf="e1", peer_device="spine1", peer_intf="e1", kind=LinkKind.fabric),
            Link(local_intf="e2", peer_device="spine2", peer_intf="e1", kind=LinkKind.fabric),
        ]
    )
    leaf2.links.extend(
        [
            Link(local_intf="e1", peer_device="spine1", peer_intf="e2", kind=LinkKind.fabric),
            Link(local_intf="e2", peer_device="spine2", peer_intf="e2", kind=LinkKind.fabric),
        ]
    )

    store.add(leaf1)
    store.add(leaf2)
    store.add(spine1)
    store.add(spine2)

    g = build_fabric_graph(store)
    result = validate_clos_topology(g)

    assert result.ok
    assert result.errors == []


def test_leaf_with_one_uplink_fails_validation():
    """
    Invalid topology.

    leaf1 only has one fabric uplink to spines.
    The validator should block this.
    """
    store = InventoryStore()

    leaf1 = make_device("leaf1", DeviceRole.leaf)
    spine1 = make_device("spine1", DeviceRole.spine)

    leaf1.links.append(
        Link(local_intf="e1", peer_device="spine1", peer_intf="e1", kind=LinkKind.fabric)
    )

    store.add(leaf1)
    store.add(spine1)

    g = build_fabric_graph(store)
    result = validate_clos_topology(g)

    assert not result.ok
    assert any("require at least 2" in e for e in result.errors)


def test_three_tier_super_spine_rules():
    """
    Minimal three tier check.

    leaf1 has two fabric links to spine1
    spine1 has a fabric link to super1
    super1 only connects to spine1 via fabric

    This should be valid.
    """
    store = InventoryStore()

    leaf1 = make_device("leaf1", DeviceRole.leaf)
    spine1 = make_device("spine1", DeviceRole.spine)
    super1 = make_device("super1", DeviceRole.super_spine)

    leaf1.links.extend(
        [
            Link(local_intf="e1", peer_device="spine1", peer_intf="e1", kind=LinkKind.fabric),
            Link(local_intf="e2", peer_device="spine1", peer_intf="e2", kind=LinkKind.fabric),
        ]
    )

    spine1.links.append(
        Link(local_intf="e49", peer_device="super1", peer_intf="e1", kind=LinkKind.fabric)
    )

    store.add(leaf1)
    store.add(spine1)
    store.add(super1)

    g = build_fabric_graph(store)
    result = validate_clos_topology(g)

    assert result.ok
    assert result.errors == []
