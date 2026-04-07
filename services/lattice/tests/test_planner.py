from datacenter_orchestrator.agent.engine import OrchestrationEngine, PlanExecutor
from datacenter_orchestrator.core.types import (
    DeviceEndpoints,
    DeviceIdentity,
    DeviceRecord,
    DeviceRole,
    FabricLocation,
    IntentChange,
)
from datacenter_orchestrator.inventory.store import InventoryStore
from datacenter_orchestrator.planner.planner import DeterministicPlanner, PlannerConfig


class FakeExecutor:
    """
    A fake executor used for unit tests.

    Behavior
    - Captures a snapshot for the exact paths in the plan
    - Applies desired values into internal state
    - Returns observed state equal to internal state

    You can force failure by providing a mismatch map.
    """

    def __init__(self, mismatch: dict[str, dict[str, object]] | None = None) -> None:
        self._state: dict[str, dict[str, object]] = {}
        self._mismatch = mismatch or {}

    def apply_plan(self, plan):  # type: ignore[no-untyped-def]
        pre_snapshot: dict[str, dict[str, object]] = {}
        observed_state: dict[str, dict[str, object]] = {}

        for act in plan.actions:
            dev_state = self._state.setdefault(act.device, {})
            pre_snapshot.setdefault(act.device, {})

            for path in act.model_paths:
                if path in dev_state:
                    pre_snapshot[act.device][path] = dev_state[path]
                else:
                    pre_snapshot[act.device][path] = None

            for path, value in act.model_paths.items():
                dev_state[path] = value

            observed_state[act.device] = dict(dev_state)

        for dev, paths in self._mismatch.items():
            observed_state.setdefault(dev, {})
            for path, bad_value in paths.items():
                observed_state[dev][path] = bad_value

        return observed_state, pre_snapshot


def _make_inventory() -> InventoryStore:
    store = InventoryStore()
    dev = DeviceRecord(
        name="leaf1",
        role=DeviceRole.leaf,
        identity=DeviceIdentity(vendor="demo", model="demo", os_name="demo", os_version="1"),
        endpoints=DeviceEndpoints(mgmt_host="10.0.0.1", gnmi_host="10.0.0.1"),
        location=FabricLocation(pod="pod1", rack="r1"),
    )
    store.add(dev)
    return store


def test_planner_builds_change_plan_from_actions():
    store = _make_inventory()
    planner = DeterministicPlanner(config=PlannerConfig(max_devices_low_risk=2))

    intent = IntentChange(
        change_id="c1",
        scope="fabric",
        desired={
            "actions": [
                {
                    "device": "leaf1",
                    "model_paths": {
                        "/openconfig test path": "value1",
                    },
                    "reason": "set a value",
                }
            ]
        },
        current={},
        diff_summary="one change",
    )

    plan = planner.plan_change(intent, store)

    assert plan.plan_id == "c1"
    assert plan.risk == "low"
    assert len(plan.actions) == 1
    assert plan.actions[0].device == "leaf1"
    assert "/openconfig test path" in plan.actions[0].model_paths
    assert len(plan.verification.checks) == 1


def test_engine_raises_alert_on_verification_failure_and_attempts_rollback():
    store = _make_inventory()
    planner = DeterministicPlanner()

    mismatch = {"leaf1": {"/openconfig test path": "wrong"}}
    executor: PlanExecutor = FakeExecutor(mismatch=mismatch)

    engine = OrchestrationEngine(planner=planner, executor=executor)

    intent = IntentChange(
        change_id="c2",
        scope="fabric",
        desired={
            "actions": [
                {
                    "device": "leaf1",
                    "model_paths": {"/openconfig test path": "expected"},
                    "reason": "set expected",
                }
            ]
        },
        current={},
        diff_summary="force mismatch",
    )

    result = engine.run_once(intent, store)

    assert not result.ok
    assert result.alert is not None
    assert result.alert.rollback_attempted
    assert len(result.alert.verification_failures) == 1
