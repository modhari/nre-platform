from datacenter_orchestrator.fabric.capacity import (
    SwitchSpec,
    synthesize_architecture,
    three_tier_capacity,
    two_tier_capacity,
)


def test_two_tier_formula():
    assert two_tier_capacity(64, 64) == 2048


def test_three_tier_formula():
    assert three_tier_capacity(64) == 65536


def test_breakout_sizing():
    leaf = SwitchSpec(port_count=32, breakout_factor=4)
    spine = SwitchSpec(port_count=32, breakout_factor=3)

    capacity = two_tier_capacity(
        leaf.effective_ports,
        spine.effective_ports,
    )

    assert capacity > 0


def test_architecture_decision_two_tier():
    leaf = SwitchSpec(64)
    spine = SwitchSpec(64)

    plan = synthesize_architecture(
        required_servers=1000,
        leaf_spec=leaf,
        spine_spec=spine,
    )

    assert plan.tier == "two-tier"


def test_architecture_decision_three_tier():
    leaf = SwitchSpec(64)
    spine = SwitchSpec(64)

    plan = synthesize_architecture(
        required_servers=50000,
        leaf_spec=leaf,
        spine_spec=spine,
    )

    assert plan.tier == "three-tier"
