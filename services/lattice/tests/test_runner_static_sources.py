from __future__ import annotations

import json
from pathlib import Path

from datacenter_orchestrator.agent.runner import AgentRunner, RunnerConfig
from datacenter_orchestrator.execution.mock import InMemoryExecutor
from datacenter_orchestrator.intent.static_source import StaticIntentSource
from datacenter_orchestrator.inventory.plugins.static import StaticInventoryPlugin


def test_runner_cycle_with_static_inventory_and_intent(tmp_path: Path):
    inv_path = tmp_path / "inventory.json"
    intents_path = tmp_path / "intents.json"

    inv_payload = {
        "devices": [
            {
                "name": "leaf1",
                "role": "leaf",
                "identity": {
                    "vendor": "demo",
                    "model": "demo",
                    "os_name": "demo",
                    "os_version": "1",
                },
                "endpoints": {"mgmt_host": "10.0.0.1", "gnmi_host": "10.0.0.1"},
                "location": {"pod": "pod1", "rack": "r1"},
                "links": [],
            }
        ]
    }

    intents_payload = {
        "intents": [
            {
                "change_id": "c1",
                "scope": "fabric",
                "desired": {
                    "actions": [
                        {
                            "device": "leaf1",
                            "model_paths": {
                                "/openconfig/system/config/hostname": "leaf1",
                            },
                            "reason": "set hostname",
                        }
                    ]
                },
                "current": {},
                "diff_summary": "one change",
            }
        ]
    }

    inv_path.write_text(json.dumps(inv_payload), encoding="utf-8")
    intents_path.write_text(json.dumps(intents_payload), encoding="utf-8")

    executor = InMemoryExecutor()

    inv_plugin = StaticInventoryPlugin(path=inv_path)
    intent_source = StaticIntentSource(path=intents_path)

    runner = AgentRunner(
        executor=executor,
        inventory_plugin=inv_plugin,
        intent_source=intent_source,
        config=RunnerConfig(interval_seconds=0),
    )

    runner.run_cycle()

    assert executor.state["leaf1"]["/openconfig/system/config/hostname"] == "leaf1"
