from __future__ import annotations

from dataclasses import asdict, dataclass, field

from internal.bgp.history_query_service import (
    BgpHistoryQueryRequest,
    BgpHistoryQueryService,
)
from internal.bgp.history_store import BgpHistoryStore


@dataclass(frozen=True)
class PrefixPresence:
    device: str
    present_prefixes: list[str] = field(default_factory=list)
    missing_prefixes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CrossDeviceCorrelationResult:
    checked_prefixes: list[str] = field(default_factory=list)
    source_device: str = ""
    sibling_devices_checked: list[str] = field(default_factory=list)
    present_on_siblings: dict[str, list[str]] = field(default_factory=dict)
    missing_on_siblings: dict[str, list[str]] = field(default_factory=dict)
    prefixes_present_anywhere_else: list[str] = field(default_factory=list)
    prefixes_missing_everywhere_checked: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class BgpCrossDeviceCorrelator:
    """
    Check whether prefixes missing on one device still exist on sibling devices.
    """

    def __init__(self, history_store: BgpHistoryStore) -> None:
        self.history_store = history_store
        self.history_service = BgpHistoryQueryService(history_store=history_store)

    def correlate_missing_prefixes(
        self,
        *,
        source_device: str,
        peer: str,
        network_instance: str,
        afi_safi: str,
        direction: str,
        timestamp_ms: int,
        missing_prefixes: list[str],
    ) -> CrossDeviceCorrelationResult:
        if not missing_prefixes:
            return CrossDeviceCorrelationResult(
                checked_prefixes=[],
                source_device=source_device,
                sibling_devices_checked=[],
                present_on_siblings={},
                missing_on_siblings={},
                prefixes_present_anywhere_else=[],
                prefixes_missing_everywhere_checked=[],
            )

        sibling_devices = self._discover_sibling_devices(
            source_device=source_device,
            peer=peer,
            network_instance=network_instance,
            afi_safi=afi_safi,
            direction=direction,
            timestamp_ms=timestamp_ms,
        )

        present_on_siblings: dict[str, list[str]] = {}
        missing_on_siblings: dict[str, list[str]] = {}

        for device in sibling_devices:
            response = self.history_service.handle(
                BgpHistoryQueryRequest(
                    device=device,
                    peer=peer,
                    network_instance=network_instance,
                    direction=direction,
                    afi_safi=afi_safi,
                    timestamp_ms=timestamp_ms,
                    query_type="routes_at_time",
                )
            )

            current_prefixes = {item["prefix"] for item in response.results}
            present = [prefix for prefix in missing_prefixes if prefix in current_prefixes]
            missing = [prefix for prefix in missing_prefixes if prefix not in current_prefixes]

            present_on_siblings[device] = present
            missing_on_siblings[device] = missing

        prefixes_present_anywhere_else = sorted(
            {
                prefix
                for prefixes in present_on_siblings.values()
                for prefix in prefixes
            }
        )
        prefixes_missing_everywhere_checked = sorted(
            [
                prefix
                for prefix in missing_prefixes
                if prefix not in prefixes_present_anywhere_else
            ]
        )

        return CrossDeviceCorrelationResult(
            checked_prefixes=list(missing_prefixes),
            source_device=source_device,
            sibling_devices_checked=sibling_devices,
            present_on_siblings=present_on_siblings,
            missing_on_siblings=missing_on_siblings,
            prefixes_present_anywhere_else=prefixes_present_anywhere_else,
            prefixes_missing_everywhere_checked=prefixes_missing_everywhere_checked,
        )

    def _discover_sibling_devices(
        self,
        *,
        source_device: str,
        peer: str,
        network_instance: str,
        afi_safi: str,
        direction: str,
        timestamp_ms: int,
    ) -> list[str]:
        rows = self.history_store.routes_at_or_before(
            timestamp_ms=timestamp_ms,
            peer=peer,
            direction=direction,
            afi_safi=afi_safi,
        )

        devices = sorted(
            {
                row.device
                for row in rows
                if row.network_instance == network_instance and row.device != source_device
            }
        )
        return devices
