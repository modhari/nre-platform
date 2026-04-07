from datacenter_orchestrator.core.types import (
    DeviceEndpoints,
    DeviceIdentity,
    DeviceRecord,
    DeviceRole,
    FabricLocation,
)
from datacenter_orchestrator.inventory.store import InventoryStore


def test_inventory_store_add_get():
    store = InventoryStore()

    dev = DeviceRecord(
        name="leaf1",
        role=DeviceRole.leaf,
        identity=DeviceIdentity(vendor="x", model="y", os_name="z", os_version="1"),
        endpoints=DeviceEndpoints(mgmt_host="1.1.1.1", gnmi_host="1.1.1.1"),
        location=FabricLocation(pod="pod1", rack="r1"),
    )

    store.add(dev)
    assert store.get("leaf1") is not None
    assert store.names() == ["leaf1"]
