from __future__ import annotations

import json

from .in_memory_provider import (
    InMemoryDeviceContextProvider,
    InMemoryInterfaceContextProvider,
)
from .metric_adapter import MetricAdapter
from .models import NormalizedMetric
from .pipeline import EnrichmentPipeline
from .providers import DeviceContextRecord, InterfaceContextRecord, ProviderBundle
from .resolver import EnrichmentResolver


def build_sample_providers() -> ProviderBundle:
    devices = {
        "leaf-01": DeviceContextRecord(
            device="leaf-01",
            datacenter="sjc1",
            pop="sjc",
            region="us-west",
            site_code="sjc1",
            role="leaf",
            topology_role="fabric_leaf",
            fabric="clos-a",
            pod="pod-2",
            rack="r42",
        ),
        "leaf-02": DeviceContextRecord(
            device="leaf-02",
            datacenter="sjc1",
            pop="sjc",
            region="us-west",
            site_code="sjc1",
            role="leaf",
            topology_role="fabric_leaf",
            fabric="clos-a",
            pod="pod-2",
            rack="r43",
        ),
    }

    interfaces = {
        ("leaf-01", "Ethernet3"): InterfaceContextRecord(
            device="leaf-01",
            interface="Ethernet3",
            customer_id="cust-12345",
            attachment_type="dedicated",
            service_id="svc-9001",
            circuit_id="ckt-7788",
            tenant_id="tenant-44",
            peer_device="customer-ce-01",
            peer_interface="xe-0/0/0",
            cluster="cluster-a",
            availability_zone="us-west-1a",
        ),
    }

    return ProviderBundle(
        device_provider=InMemoryDeviceContextProvider(devices),
        interface_provider=InMemoryInterfaceContextProvider(interfaces),
    )


def main() -> None:
    providers = build_sample_providers()
    resolver = EnrichmentResolver(providers=providers)
    pipeline = EnrichmentPipeline(resolver=resolver)
    adapter = MetricAdapter(pipeline=pipeline)

    metric = NormalizedMetric(
        name="lattice_interface_in_octets_total",
        value=182736451,
        labels={
            "device": "leaf-01",
            "interface": "Ethernet3",
            "vendor": "arista",
        },
        timestamp_ms=1711812345000,
    )

    prom_record = adapter.to_prometheus_record(metric)
    rich_record = adapter.to_rich_record(metric)

    print("PROMETHEUS RECORD")
    print(json.dumps(prom_record.to_dict(), indent=2))
    print()
    print("RICH RECORD")
    print(json.dumps(rich_record.to_dict(), indent=2))


if __name__ == "__main__":
    main()
