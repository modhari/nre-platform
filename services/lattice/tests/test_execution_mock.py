from datacenter_orchestrator.agent.engine import OrchestrationEngine
from datacenter_orchestrator.core.types import (
    DeviceEndpoints,
    DeviceIdentity,
    DeviceRecord,
    DeviceRole,
    FabricLocation,
    IntentChange,
)
from datacenter_orchestrator.execution.mock import InMemoryExecutor
from datacenter_orchestrator.inventory.store import InventoryStore
from datacenter_orchestrator.planner.planner import DeterministicPlanner


def make_inventory() -> InventoryStore:
    store = InventoryStore()
    store.add(
        DeviceRecord(
            name="leaf1",
            role=DeviceRole.leaf,
            identity=DeviceIdentity(
                vendor="demo",
                model="demo",
                os_name="demo",
                os_version="1",
            ),
            endpoints=DeviceEndpoints(
                mgmt_host="10.0.0.1",
                gnmi_host="10.0.0.1",
            ),
            location=FabricLocation(
                pod="pod1",
                rack="r1",
            ),
        )
    )
    return store


def test_inmemory_executor_snapshot_and_observed_state():
    inv = make_inventory()
    planner = DeterministicPlanner()
    executor = InMemoryExecutor()

    engine = OrchestrationEngine(planner=planner, executor=executor)

    path = "/openconfig/interfaces/interface[name=eth1]/config/enabled"

    intent = IntentChange(
        change_id="exec1",
        scope="fabric",
        desired={
            "actions": [
                {
                    "device": "leaf1",
                    "model_paths": {path: True},
                    "reason": "enable interface",
                }
            ]
        },
        current={},
        diff_summary="one path",
    )

    result = engine.run_once(intent, inv)

    assert result.ok
    assert executor.state["leaf1"][path] is True


def test_inmemory_executor_can_inject_mismatch_and_trigger_rollback():
    inv = make_inventory()
    planner = DeterministicPlanner()

    path = "/openconfig/system/config/hostname"

    executor = InMemoryExecutor(
        mismatch={"leaf1": {path: "wrong"}},
    )

    engine = OrchestrationEngine(planner=planner, executor=executor)

    intent = IntentChange(
        change_id="exec2",
        scope="fabric",
        desired={
            "actions": [
                {
                    "device": "leaf1",
                    "model_paths": {path: "expected"},
                    "reason": "set hostname",
                }
            ]
        },
        current={},
        diff_summary="force mismatch",
    )

    result = engine.run_once(intent, inv)

    assert not result.ok
    assert result.alert is not None
    assert result.alert.rollback_attempted
    assert len(result.alert.verification_failures) == 1
