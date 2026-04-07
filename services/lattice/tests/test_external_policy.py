from datacenter_orchestrator.core.types import (
    DeviceEndpoints,
    DeviceIdentity,
    DeviceRecord,
    DeviceRole,
    FabricLocation,
    Link,
    LinkKind,
)
from datacenter_orchestrator.fabric.external_policy import validate_external_connectivity
from datacenter_orchestrator.fabric.graph import build_fabric_graph
from datacenter_orchestrator.inventory.store import InventoryStore


def make_device(name: str, role: DeviceRole) -> DeviceRecord:
    return DeviceRecord(
        name=name,
        role=role,
        identity=DeviceIdentity(vendor="demo", model="demo", os_name="demo", os_version="1"),
        endpoints=DeviceEndpoints(mgmt_host="10.0.0.1", gnmi_host="10.0.0.1"),
        location=FabricLocation(pod="pod1", rack="r1"),
    )


def test_border_leaf_model_requires_border_leaf_external_link():
    store = InventoryStore()
    border1 = make_device("border1", DeviceRole.border_leaf)
    spine1 = make_device("spine1", DeviceRole.spine)

    border1.links.append(
        Link(local_intf="e1", peer_device="spine1", peer_intf="e1", kind=LinkKind.fabric)
    )

    store.add(border1)
    store.add(spine1)

    g = build_fabric_graph(store)
    res = validate_external_connectivity(g)

    assert not res.ok
    assert any("no border_leaf has external connectivity" in e for e in res.errors)


def test_border_leaf_model_allows_border_leaf_external_link():
    store = InventoryStore()
    border1 = make_device("border1", DeviceRole.border_leaf)
    spine1 = make_device("spine1", DeviceRole.spine)

    border1.links.append(
        Link(local_intf="e1", peer_device="spine1", peer_intf="e1", kind=LinkKind.fabric)
    )

    border1.links.append(
        Link(
            local_intf="e49",
            peer_device="internet",
            peer_intf="xe0",
            kind=LinkKind.internet,
        )
    )

    store.add(border1)
    store.add(spine1)

    g = build_fabric_graph(store)
    res = validate_external_connectivity(g)

    assert res.ok


def test_spine_external_model_blocks_partial_spines():
    store = InventoryStore()
    spine1 = make_device("spine1", DeviceRole.spine)
    spine2 = make_device("spine2", DeviceRole.spine)

    spine1.links.append(
        Link(
            local_intf="e49",
            peer_device="internet",
            peer_intf="xe0",
            kind=LinkKind.internet,
        )
    )

    store.add(spine1)
    store.add(spine2)

    g = build_fabric_graph(store)
    res = validate_external_connectivity(g)

    assert not res.ok
    assert any("partial spine external connectivity" in e for e in res.errors)


def test_spine_external_model_allows_all_spines_external():
    store = InventoryStore()
    spine1 = make_device("spine1", DeviceRole.spine)
    spine2 = make_device("spine2", DeviceRole.spine)

    spine1.links.append(
        Link(
            local_intf="e49",
            peer_device="internet",
            peer_intf="xe0",
            kind=LinkKind.internet,
        )
    )
    spine2.links.append(
        Link(
            local_intf="e49",
            peer_device="internet",
            peer_intf="xe0",
            kind=LinkKind.internet,
        )
    )

    store.add(spine1)
    store.add(spine2)

    g = build_fabric_graph(store)
    res = validate_external_connectivity(g)

    assert res.ok
