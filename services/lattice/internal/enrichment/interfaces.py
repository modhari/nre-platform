from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from .models import EnrichmentData, EnrichmentKey


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


class DeviceContextProvider(ABC):
    @abstractmethod
    def get_device_context(self, device: str) -> DeviceContextRecord | None:
        raise NotImplementedError


class InterfaceContextProvider(ABC):
    @abstractmethod
    def get_interface_context(
        self,
        device: str,
        interface: str,
    ) -> InterfaceContextRecord | None:
        raise NotImplementedError


class EnrichmentProvider(ABC):
    @abstractmethod
    def resolve(self, key: EnrichmentKey) -> EnrichmentData:
        raise NotImplementedError
