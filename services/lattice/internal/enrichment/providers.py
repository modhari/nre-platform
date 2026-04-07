from __future__ import annotations

from dataclasses import dataclass

from .interfaces import DeviceContextProvider, InterfaceContextProvider


@dataclass(frozen=True)
class DeviceContextRecord:
    device: str
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
class InterfaceContextRecord:
    device: str
    interface: str
    customer_id: str | None = None
    attachment_type: str | None = None
    service_id: str | None = None
    circuit_id: str | None = None
    tenant_id: str | None = None
    peer_device: str | None = None
    peer_interface: str | None = None
    cluster: str | None = None
    availability_zone: str | None = None


class ProviderBundle:
    """
    Simple container for enrichment providers.
    """

    def __init__(
        self,
        device_provider: DeviceContextProvider,
        interface_provider: InterfaceContextProvider,
    ) -> None:
        self.device_provider = device_provider
        self.interface_provider = interface_provider
