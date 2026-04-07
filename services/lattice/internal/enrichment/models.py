from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

LabelMode = Literal["metrics_safe", "rich"]


@dataclass(frozen=True)
class EnrichmentKey:
    """
    Primary lookup key used to resolve enrichment context.

    Most interface related enrichment will use:
    - device
    - interface

    Some workflows may later use:
    - subinterface
    - lag
    - network_instance
    - circuit_id
    """

    device: str
    interface: str | None = None
    subinterface: str | None = None
    lag: str | None = None
    network_instance: str | None = None
    circuit_id: str | None = None
    customer_attachment_id: str | None = None


@dataclass(frozen=True)
class InfrastructureContext:
    datacenter: str | None = None
    pop: str | None = None
    region: str | None = None
    site_code: str | None = None
    role: str | None = None
    topology_role: str | None = None
    fabric: str | None = None
    pod: str | None = None
    rack: str | None = None


@dataclass(frozen=True)
class CustomerContext:
    customer_id: str | None = None
    attachment_type: str | None = None
    service_id: str | None = None
    circuit_id: str | None = None
    tenant_id: str | None = None


@dataclass(frozen=True)
class TopologyContext:
    peer_device: str | None = None
    peer_interface: str | None = None
    cluster: str | None = None
    availability_zone: str | None = None


@dataclass(frozen=True)
class EnrichmentData:
    infrastructure: InfrastructureContext = field(default_factory=InfrastructureContext)
    customer: CustomerContext = field(default_factory=CustomerContext)
    topology: TopologyContext = field(default_factory=TopologyContext)

    def to_flat_labels(self, mode: LabelMode = "metrics_safe") -> dict[str, str]:
        """
        Returns a flat label map.

        metrics_safe:
            Low cardinality labels intended for Prometheus.

        rich:
            Broader label map for controlled non Prometheus use cases.
        """
        labels: dict[str, str] = {}

        infra = asdict(self.infrastructure)
        cust = asdict(self.customer)
        topo = asdict(self.topology)

        metrics_safe_fields = {
            "datacenter",
            "pop",
            "region",
            "site_code",
            "role",
            "topology_role",
            "fabric",
            "pod",
            "customer_id",
            "attachment_type",
        }

        rich_fields = {
            "datacenter",
            "pop",
            "region",
            "site_code",
            "role",
            "topology_role",
            "fabric",
            "pod",
            "rack",
            "customer_id",
            "attachment_type",
            "service_id",
            "circuit_id",
            "tenant_id",
            "cluster",
            "availability_zone",
            "peer_device",
            "peer_interface",
        }

        allowed = metrics_safe_fields if mode == "metrics_safe" else rich_fields

        for source in (infra, cust, topo):
            for key, value in source.items():
                if key in allowed and value is not None:
                    labels[key] = str(value)

        return labels

    def to_rich_context(self) -> dict[str, Any]:
        """
        Rich structured context for event, object, and audit exports.
        """
        return {
            "infrastructure": asdict(self.infrastructure),
            "customer": asdict(self.customer),
            "topology": asdict(self.topology),
        }


@dataclass
class NormalizedMetric:
    name: str
    value: float | int
    labels: dict[str, str]
    timestamp_ms: int | None = None

    def copy(self) -> NormalizedMetric:
        return NormalizedMetric(
            name=self.name,
            value=self.value,
            labels=dict(self.labels),
            timestamp_ms=self.timestamp_ms,
        )


@dataclass
class EnrichedMetric:
    name: str
    value: float | int
    labels: dict[str, str]
    timestamp_ms: int | None = None
    enrichment: dict[str, Any] = field(default_factory=dict)

    def to_prometheus_sample(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "labels": self.labels,
            "timestamp_ms": self.timestamp_ms,
        }


@dataclass
class NormalizedEvent:
    event_type: str
    severity: str
    attributes: dict[str, Any]
    timestamp_ms: int | None = None


@dataclass
class EnrichedEvent:
    event_type: str
    severity: str
    attributes: dict[str, Any]
    timestamp_ms: int | None = None
    enrichment: dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizedObject:
    object_type: str
    object_id: str
    attributes: dict[str, Any]


@dataclass
class EnrichedObject:
    object_type: str
    object_id: str
    attributes: dict[str, Any]
    enrichment: dict[str, Any] = field(default_factory=dict)
