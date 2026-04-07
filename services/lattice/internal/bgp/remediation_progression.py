from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from internal.bgp.mcp_risk_wrapper import McpRiskWrapper
from internal.bgp.remediation_to_intent import McpIntentRequest


@dataclass(frozen=True)
class NextStepDecision:
    should_continue: bool
    reason: str
    next_intent: McpIntentRequest | None = None
    governed_next_intent: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BgpRemediationProgression:
    """
    Choose the next safest remediation step after prefix verification fails.
    """

    def __init__(self) -> None:
        self.risk_wrapper = McpRiskWrapper()

    def next_step(
        self,
        *,
        current_intent: McpIntentRequest,
        verification_details: dict[str, Any] | None,
    ) -> NextStepDecision:
        intent_name = current_intent.intent_name
        params = current_intent.parameters
        context = params.get("context", {})

        missing_prefixes: list[str] = []
        if verification_details:
            prefix_verification = verification_details.get("prefix_verification")
            if prefix_verification:
                missing_prefixes = prefix_verification.get("missing_prefixes", [])

        if intent_name == "bgp_route_refresh":
            next_intent = McpIntentRequest(
                intent_name="bgp_soft_clear_in",
                target_device=current_intent.target_device,
                parameters={
                    "peer": params["peer"],
                    "network_instance": params["network_instance"],
                    "afi_safi": params["afi_safi"],
                    "context": {
                        **context,
                        "missing_prefixes_after_refresh": missing_prefixes,
                    },
                },
                risk_level="medium",
                requires_approval=False,
                verification_steps=[
                    "verify_received_route_count",
                    "verify_missing_prefixes_recovered",
                    "confirm_no_broad_blast_radius_expansion",
                ],
                rollback_hint="Escalate if recovery still fails after soft clear inbound",
                source_anomaly_type=current_intent.source_anomaly_type,
                confidence=current_intent.confidence,
                reasoning=(
                    "Route refresh completed but expected prefixes did not recover. "
                    "Advance to the next bounded inbound recovery step."
                ),
            )
            governed = self.risk_wrapper.wrap(next_intent)
            return NextStepDecision(
                should_continue=True,
                reason=(
                    "Prefix recovery failed after route refresh, so the next safest "
                    "step is soft clear inbound."
                ),
                next_intent=next_intent,
                governed_next_intent=governed.to_dict(),
                notes=[
                    "Recheck missing prefixes after soft clear inbound",
                    "Escalate if prefixes are still absent",
                ],
            )

        if intent_name == "bgp_soft_clear_in":
            next_intent = McpIntentRequest(
                intent_name="bgp_escalate_only",
                target_device=current_intent.target_device,
                parameters={
                    "peer": params["peer"],
                    "network_instance": params["network_instance"],
                    "afi_safi": params["afi_safi"],
                    "severity": "high",
                    "blast_radius": "peer_or_device_local",
                    "context": {
                        **context,
                        "missing_prefixes_after_soft_clear_in": missing_prefixes,
                    },
                },
                risk_level="none",
                requires_approval=False,
                verification_steps=[
                    "attach_missing_prefix_context",
                    "compare_sibling_devices",
                    "notify_operator",
                ],
                rollback_hint=None,
                source_anomaly_type=current_intent.source_anomaly_type,
                confidence="high",
                reasoning=(
                    "Soft clear inbound did not recover expected prefixes. "
                    "Escalate for operator review and wider correlation."
                ),
            )
            governed = self.risk_wrapper.wrap(next_intent)
            return NextStepDecision(
                should_continue=True,
                reason=(
                    "Prefix recovery failed after soft clear inbound, so continue with "
                    "escalation instead of stronger automated action."
                ),
                next_intent=next_intent,
                governed_next_intent=governed.to_dict(),
                notes=[
                    "Check sibling devices for the same missing prefixes",
                    "Validate policy and upstream scope before further action",
                ],
            )

        if intent_name == "bgp_soft_clear_out":
            next_intent = McpIntentRequest(
                intent_name="bgp_validate_policy_then_soft_clear_out",
                target_device=current_intent.target_device,
                parameters={
                    "peer": params["peer"],
                    "network_instance": params["network_instance"],
                    "afi_safi": params["afi_safi"],
                    "validation_scope": "export_policy_and_local_rib",
                    "context": {
                        **context,
                        "missing_prefixes_after_soft_clear_out": missing_prefixes,
                    },
                },
                risk_level="medium",
                requires_approval=False,
                verification_steps=[
                    "validate_export_policy",
                    "verify_local_rib_population",
                    "verify_expected_prefixes_are_advertised",
                ],
                rollback_hint=(
                    "Rollback recent export policy changes if validation finds a "
                    "regression"
                ),
                source_anomaly_type=current_intent.source_anomaly_type,
                confidence="medium",
                reasoning=(
                    "Outbound refresh path did not restore expected advertisements. "
                    "Advance to policy validation before any further action."
                ),
            )
            governed = self.risk_wrapper.wrap(next_intent)
            return NextStepDecision(
                should_continue=True,
                reason=(
                    "Prefix recovery failed after soft clear out, so validate policy "
                    "and local rib state next."
                ),
                next_intent=next_intent,
                governed_next_intent=governed.to_dict(),
                notes=[
                    "Do not continue with stronger action without policy inspection",
                    "Require approval if the next governed step demands it",
                ],
            )

        if intent_name == "bgp_validate_policy_then_soft_clear_out":
            next_intent = McpIntentRequest(
                intent_name="bgp_escalate_only",
                target_device=current_intent.target_device,
                parameters={
                    "peer": params["peer"],
                    "network_instance": params["network_instance"],
                    "afi_safi": params["afi_safi"],
                    "severity": "high",
                    "blast_radius": "peer_or_device_local",
                    "context": {
                        **context,
                        "missing_prefixes_after_policy_validation": missing_prefixes,
                    },
                },
                risk_level="none",
                requires_approval=False,
                verification_steps=[
                    "attach_missing_prefix_context",
                    "attach_policy_validation_context",
                    "notify_operator",
                ],
                rollback_hint=None,
                source_anomaly_type=current_intent.source_anomaly_type,
                confidence="high",
                reasoning=(
                    "Policy validation path did not recover expected advertisements. "
                    "Escalate for operator review."
                ),
            )
            governed = self.risk_wrapper.wrap(next_intent)
            return NextStepDecision(
                should_continue=True,
                reason=(
                    "The policy validation path did not restore expected prefixes, so "
                    "escalation is the next safe move."
                ),
                next_intent=next_intent,
                governed_next_intent=governed.to_dict(),
                notes=[
                    "Preserve full prefix evidence for operator review",
                ],
            )

        return NextStepDecision(
            should_continue=False,
            reason="No staged remediation rule matched for this intent.",
            next_intent=None,
            governed_next_intent=None,
            notes=[],
        )
