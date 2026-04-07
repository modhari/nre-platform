from __future__ import annotations

from .models import (
    CustomerContext,
    EnrichmentData,
    EnrichmentKey,
    InfrastructureContext,
    TopologyContext,
)
from .providers import DeviceContextRecord, InterfaceContextRecord, ProviderBundle


class EnrichmentResolver:
    """
    Provider backed enrichment resolver.

    This version resolves enrichment using provider interfaces so the
    backing source can later be NetBox, Netconfig, a cache, or a database.
    """

    def __init__(self, providers: ProviderBundle) -> None:
        self.providers = providers

    def resolve(self, key: EnrichmentKey) -> EnrichmentData:
        device_record = self.providers.device_provider.get_device_context(key.device)
        interface_record = None

        if key.interface:
            interface_record = self.providers.interface_provider.get_interface_context(
                key.device,
                key.interface,
            )

        infrastructure = self._build_infrastructure(device_record)
        customer = self._build_customer(interface_record)
        topology = self._build_topology(interface_record)

        return EnrichmentData(
            infrastructure=infrastructure,
            customer=customer,
            topology=topology,
        )

    def _build_infrastructure(
        self,
        record: DeviceContextRecord | None,
    ) -> InfrastructureContext:
        if not record:
            return InfrastructureContext()

        return InfrastructureContext(
            datacenter=record.datacenter,
            pop=record.pop,
            region=record.region,
            site_code=record.site_code,
            role=record.role,
            topology_role=record.topology_role,
            fabric=record.fabric,
            pod=record.pod,
            rack=record.rack,
        )

    def _build_customer(
        self,
        record: InterfaceContextRecord | None,
    ) -> CustomerContext:
        if not record:
            return CustomerContext()

        return CustomerContext(
            customer_id=record.customer_id,
            attachment_type=record.attachment_type,
            service_id=record.service_id,
            circuit_id=record.circuit_id,
            tenant_id=record.tenant_id,
        )

    def _build_topology(
        self,
        record: InterfaceContextRecord | None,
    ) -> TopologyContext:
        if not record:
            return TopologyContext()

        return TopologyContext(
            peer_device=record.peer_device,
            peer_interface=record.peer_interface,
            cluster=record.cluster,
            availability_zone=record.availability_zone,
        )
