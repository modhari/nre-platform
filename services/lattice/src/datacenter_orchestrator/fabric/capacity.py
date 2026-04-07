"""
CLOS Capacity and Architecture Planner.

This module synthesizes a plausible CLOS architecture
based on required server count and switch capabilities.

It supports:
- Two tier leaf spine
- Three tier leaf spine super spine
- Breakout scenarios
- Non blocking assumptions

All math is documented for auditability.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SwitchSpec:
    """
    Physical switch specification.

    port_count:
        Total physical ports.

    breakout_factor:
        If ports can be broken into lower speed lanes.
        Example:
            32 x 100G broken into 4 x 25G gives breakout_factor = 4.
    """

    port_count: int
    breakout_factor: int = 1

    @property
    def effective_ports(self) -> int:
        """Return usable port count after breakout."""
        return self.port_count * self.breakout_factor


@dataclass
class ArchitecturePlan:
    """
    Structured output of capacity planning.

    tier:
        "two-tier" or "three-tier"

    leaf_count:
        Number of leaf switches

    spine_count:
        Number of spine switches

    super_spine_count:
        Number of super spines if applicable

    max_servers:
        Maximum servers supported by this plan

    explanation:
        Human readable reasoning string
    """

    tier: str
    leaf_count: int
    spine_count: int
    super_spine_count: int
    max_servers: int
    explanation: str


# ---------------------------
# TWO TIER MATH
# ---------------------------

def two_tier_capacity(leaf_ports: int, spine_ports: int) -> int:
    """
    Two tier non blocking capacity formula.

    If we want non blocking:
        total_servers = n * m / 2

    where:
        n = ports per leaf
        m = ports per spine

    This assumes:
        Half of leaf ports face servers.
        Half face spines.
    """
    return (leaf_ports * spine_ports) // 2


# ---------------------------
# THREE TIER MATH
# ---------------------------

def three_tier_capacity(n: int) -> int:
    """
    Three tier capacity when all tiers use same port count.

    total_servers = n^3 / 4

    Derived from:
        leaf_count = n / 2
        spine_count = n / 2
        super_spine_count = n / 2

    This matches the canonical Clos derivation.
    """
    return (n ** 3) // 4


# ---------------------------
# BREAKOUT SUPPORT
# ---------------------------

def breakout_adjusted_capacity(
    leaf_spec: SwitchSpec,
    spine_spec: SwitchSpec,
) -> int:
    """
    Compute capacity using effective ports.

    Effective ports account for breakout.

    Example:
        32 x 100G with breakout 4
        effective = 128 ports
    """
    return two_tier_capacity(
        leaf_spec.effective_ports,
        spine_spec.effective_ports,
    )


# ---------------------------
# ARCHITECTURE SYNTHESIS
# ---------------------------

def synthesize_architecture(
    required_servers: int,
    leaf_spec: SwitchSpec,
    spine_spec: SwitchSpec,
) -> ArchitecturePlan:
    """
    Decide whether to use two tier or three tier.

    Logic:
        1. Compute max two tier capacity.
        2. If sufficient, use two tier.
        3. Else use three tier.

    This is deterministic and safe.
    """

    two_tier_max = breakout_adjusted_capacity(
        leaf_spec,
        spine_spec,
    )

    if required_servers <= two_tier_max:
        explanation = (
            f"Two tier sufficient. "
            f"Capacity {two_tier_max} servers >= required {required_servers}."
        )

        leaf_count = leaf_spec.effective_ports // 2
        spine_count = spine_spec.effective_ports // 2

        return ArchitecturePlan(
            tier="two-tier",
            leaf_count=leaf_count,
            spine_count=spine_count,
            super_spine_count=0,
            max_servers=two_tier_max,
            explanation=explanation,
        )

    # Otherwise escalate to three tier

    n = leaf_spec.effective_ports
    three_tier_max = three_tier_capacity(n)

    explanation = (
        f"Two tier insufficient ({two_tier_max}). "
        f"Escalating to three tier with capacity {three_tier_max}."
    )

    leaf_count = n // 2
    spine_count = n // 2
    super_spine_count = n // 2

    return ArchitecturePlan(
        tier="three-tier",
        leaf_count=leaf_count,
        spine_count=spine_count,
        super_spine_count=super_spine_count,
        max_servers=three_tier_max,
        explanation=explanation,
    )
