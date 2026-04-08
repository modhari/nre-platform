from __future__ import annotations

from typing import List, Optional

from gnmi_collection_agent.core.types import DeviceIdentity
from gnmi_collection_agent.vendors.base import VendorPack


class VendorRegistry:
    """
    VendorRegistry is the single place that decides which vendor mapping pack to use.

    Why this exists:
    A real fleet is never uniform. Even within one vendor you may have multiple OS families.
    This registry lets you add new vendor packs without changing collector logic.

    Design:
    It is intentionally simple. It takes an ordered list of packs and returns the first match.
    Ordering matters because you might later have specialized packs that should match before a general pack.
    """

    def __init__(self, packs: List[VendorPack]) -> None:
        # Keep packs in a predictable order.
        # This makes behavior deterministic and testable.
        self._packs = list(packs)

    def pick(self, ident: DeviceIdentity) -> Optional[VendorPack]:
        """
        Return the first VendorPack that claims it can handle this device identity.

        We return None instead of raising because:
        1. This is normal when onboarding unknown devices
        2. The caller can choose to fall back to a generic plan
        """
        for pack in self._packs:
            if pack.match(ident):
                return pack
        return None
