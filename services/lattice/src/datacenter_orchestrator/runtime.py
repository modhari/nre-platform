from __future__ import annotations

import os
from dataclasses import dataclass

from datacenter_orchestrator.agent.runner import AgentRunner, RunnerConfig
from datacenter_orchestrator.core.types import (
    CapabilityClass,
    Confidence,
    DeviceEndpoints,
    DeviceIdentity,
    DeviceRecord,
    DeviceRole,
    FabricLocation,
    IntentChange,
    Link,
    LinkKind,
)
from datacenter_orchestrator.execution.mock import InMemoryExecutor
from datacenter_orchestrator.intent.base import IntentSource
from datacenter_orchestrator.inventory.store import InventoryStore


class StaticInventoryPlugin:
    """
    Defines a small in memory fabric inventory used for scenario driven tests.
    """

    def load(self) -> InventoryStore:
        store = InventoryStore()

        leaf_01 = DeviceRecord(
            name="leaf-01",
            role=DeviceRole.leaf,
            identity=DeviceIdentity(
                vendor="Arista",
                model="DCS-7280",
                os_name="EOS",
                os_version="4.31.1F",
                serial="LEAF01",
            ),
            endpoints=DeviceEndpoints(
                mgmt_host="leaf-01.lab.local",
                gnmi_host="leaf-01.lab.local",
                gnmi_port=57400,
            ),
            location=FabricLocation(
                pod="pod-1",
                rack="rack-1",
                plane="default",
            ),
            links=[
                Link("Ethernet49", "spine-01", "Ethernet1", LinkKind.fabric),
                Link("Ethernet50", "spine-02", "Ethernet1", LinkKind.fabric),
            ],
            bandwidth_class=CapabilityClass(
                name="100g",
                confidence=Confidence.high,
                evidence=[],
            ),
        )

        leaf_02 = DeviceRecord(
            name="leaf-02",
            role=DeviceRole.leaf,
            identity=DeviceIdentity(
                vendor="Arista",
                model="DCS-7280",
                os_name="EOS",
                os_version="4.31.1F",
                serial="LEAF02",
            ),
            endpoints=DeviceEndpoints(
                mgmt_host="leaf-02.lab.local",
                gnmi_host="leaf-02.lab.local",
                gnmi_port=57400,
            ),
            location=FabricLocation(
                pod="pod-1",
                rack="rack-2",
                plane="default",
            ),
            links=[
                Link("Ethernet49", "spine-01", "Ethernet2", LinkKind.fabric),
                Link("Ethernet50", "spine-02", "Ethernet2", LinkKind.fabric),
            ],
            bandwidth_class=CapabilityClass(
                name="100g",
                confidence=Confidence.high,
                evidence=[],
            ),
        )

        spine_01 = DeviceRecord(
            name="spine-01",
            role=DeviceRole.spine,
            identity=DeviceIdentity(
                vendor="Arista",
                model="DCS-7800",
                os_name="EOS",
                os_version="4.31.1F",
                serial="SPINE01",
            ),
            endpoints=DeviceEndpoints(
                mgmt_host="spine-01.lab.local",
                gnmi_host="spine-01.lab.local",
                gnmi_port=57400,
            ),
            location=FabricLocation(
                pod="pod-1",
                rack="spine-rack-1",
                plane="default",
            ),
            links=[],
        )

        spine_02 = DeviceRecord(
            name="spine-02",
            role=DeviceRole.spine,
            identity=DeviceIdentity(
                vendor="Arista",
                model="DCS-7800",
                os_name="EOS",
                os_version="4.31.1F",
                serial="SPINE02",
            ),
            endpoints=DeviceEndpoints(
                mgmt_host="spine-02.lab.local",
                gnmi_host="spine-02.lab.local",
                gnmi_port=57400,
            ),
            location=FabricLocation(
                pod="pod-1",
                rack="spine-rack-2",
                plane="default",
            ),
            links=[],
        )

        store.add(leaf_01)
        store.add(leaf_02)
        store.add(spine_01)
        store.add(spine_02)

        return store


@dataclass(frozen=True)
class InMemoryIntentSource(IntentSource):
    intents: list[IntentChange]

    def fetch(self) -> list[IntentChange]:
        return list(self.intents)


def build_runner(scenario: str | None = None) -> AgentRunner:
    """
    Build a scenario driven runner wired to the live MCP policy endpoint.
    """

    selected_scenario = scenario or os.environ.get("NRE_SCENARIO", "leaf_bgp_disable")

    if selected_scenario == "interface_enable":
        interface_enabled_path = "interfaces/interface[name=Ethernet1]/config/enabled"

        test_intent = IntentChange(
            change_id="test-change-iface-enable",
            scope="fabric",
            desired={
                "actions": [
                    {
                        "device": "leaf-01",
                        "model_paths": {
                            interface_enabled_path: True,
                        },
                        "reason": "enable interface for controlled test",
                    }
                ]
            },
            current={},
            diff_summary="enable interface on leaf-01",
        )

    elif selected_scenario == "leaf_bgp_disable":
        bgp_leaf_neighbor_enabled_path = (
            "network-instances/network-instance[name=default]/"
            "protocols/protocol[name=BGP]/bgp/neighbors/"
            "neighbor[neighbor-address=10.0.0.1]/config/enabled"
        )

        test_intent = IntentChange(
            change_id="test-change-leaf-bgp-disable",
            scope="fabric",
            desired={
                "actions": [
                    {
                        "device": "leaf-01",
                        "model_paths": {
                            bgp_leaf_neighbor_enabled_path: False,
                        },
                        "reason": "simulate BGP neighbor disable on leaf",
                    }
                ]
            },
            current={},
            diff_summary="disable BGP neighbor on leaf-01",
        )

    elif selected_scenario == "spine_bgp_disable":
        bgp_spine_neighbor_enabled_path = (
            "network-instances/network-instance[name=default]/"
            "protocols/protocol[name=BGP]/bgp/neighbors/"
            "neighbor[neighbor-address=10.0.0.101]/config/enabled"
        )

        test_intent = IntentChange(
            change_id="test-change-spine-bgp-disable",
            scope="fabric",
            desired={
                "actions": [
                    {
                        "device": "spine-01",
                        "model_paths": {
                            bgp_spine_neighbor_enabled_path: False,
                        },
                        "reason": "simulate BGP neighbor disable on spine",
                    }
                ]
            },
            current={},
            diff_summary="disable BGP neighbor on spine-01",
        )

    else:
        raise ValueError(f"unsupported NRE_SCENARIO: {selected_scenario}")

    return AgentRunner(
        executor=InMemoryExecutor(),
        inventory_plugin=StaticInventoryPlugin(),
        intent_source=InMemoryIntentSource(intents=[test_intent]),
        config=RunnerConfig(
            use_mcp=os.environ.get("USE_MCP", "true").lower() == "true",
            mcp_url=os.environ.get("MCP_SERVER_URL", "http://mcp-server:8080"),
            mcp_auth_token=os.environ.get("MCP_AUTH_TOKEN", "change_me"),
            mcp_hmac_secret=os.environ.get("MCP_HMAC_SECRET", "change_me_too"),
        ),
    )
