from datacenter_orchestrator.agent.execution_mode import ExecutionMode
from datacenter_orchestrator.agent.guard import ExecutionGuard, GuardConfig
from datacenter_orchestrator.planner.risk import PlanRiskAssessment, RiskLevel


def test_guard_blocks_apply_when_requires_approval():
    guard = ExecutionGuard(
        config=GuardConfig(
            default_mode=ExecutionMode.apply,
            require_approval_blocks_apply=True,
        )
    )

    risk = PlanRiskAssessment(
        risk_level=RiskLevel.medium,
        blast_radius_score=50,
        requires_approval=True,
        reasons=["requires approval"],
        evidence={},
    )

    decision = guard.decide(risk)
    assert decision.mode == ExecutionMode.dry_run
    assert decision.allowed is False
