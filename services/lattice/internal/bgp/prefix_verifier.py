from __future__ import annotations

from dataclasses import asdict, dataclass, field

from internal.bgp.history_query_service import (
    BgpHistoryQueryRequest,
    BgpHistoryQueryService,
)


@dataclass(frozen=True)
class PrefixVerificationResult:
    recovered: bool
    checked_prefixes: list[str] = field(default_factory=list)
    recovered_prefixes: list[str] = field(default_factory=list)
    missing_prefixes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class BgpPrefixVerifier:
    """
    Verify whether expected prefixes are present in the latest route view.
    """

    def __init__(self, history_service: BgpHistoryQueryService) -> None:
        self.history_service = history_service

    def verify_expected_prefixes_present(
        self,
        *,
        device: str,
        peer: str,
        network_instance: str,
        afi_safi: str,
        direction: str,
        timestamp_ms: int,
        expected_prefixes: list[str],
    ) -> PrefixVerificationResult:
        if not expected_prefixes:
            return PrefixVerificationResult(
                recovered=True,
                checked_prefixes=[],
                recovered_prefixes=[],
                missing_prefixes=[],
            )

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

        current_prefixes = {
            item["prefix"]
            for item in response.results
        }

        recovered_prefixes = [
            prefix for prefix in expected_prefixes if prefix in current_prefixes
        ]
        missing_prefixes = [
            prefix for prefix in expected_prefixes if prefix not in current_prefixes
        ]

        return PrefixVerificationResult(
            recovered=len(missing_prefixes) == 0,
            checked_prefixes=list(expected_prefixes),
            recovered_prefixes=recovered_prefixes,
            missing_prefixes=missing_prefixes,
        )
