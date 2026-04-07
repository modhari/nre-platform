from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from internal.knowledge.retrieval.query_builder import EvpnQuestion, build_request
from internal.knowledge.retrieval.retriever import EvpnVxlanRetriever, RetrievedChunk


@dataclass
class ProblemContext:
    question: str
    vendor: str
    nos_family: str | None = None
    scenario: str | None = None
    capability: str | None = None
    feature: str | None = None
    role: str = "reasoning_primary"
    limit: int = 5
    allow_remediation_guidance: bool = False
    allow_capability_claims: bool = False


@dataclass
class ReasoningSignal:
    signal_type: str
    summary: str
    supporting_chunk_ids: list[str] = field(default_factory=list)
    supporting_documents: list[str] = field(default_factory=list)
    confidence: str = "medium"


@dataclass
class ReasoningOutput:
    vendor: str
    nos_family: str | None
    scenario: str | None
    capability: str | None
    feature: str | None
    question: str
    findings: list[str] = field(default_factory=list)
    likely_causes: list[str] = field(default_factory=list)
    verification_steps: list[str] = field(default_factory=list)
    safe_actions: list[str] = field(default_factory=list)
    unsafe_actions: list[str] = field(default_factory=list)
    supporting_signals: list[ReasoningSignal] = field(default_factory=list)
    retrieved_chunks: list[RetrievedChunk] = field(default_factory=list)
    confidence: str = "low"

    def to_dict(self) -> dict[str, Any]:
        return {
            "vendor": self.vendor,
            "nos_family": self.nos_family,
            "scenario": self.scenario,
            "capability": self.capability,
            "feature": self.feature,
            "question": self.question,
            "findings": self.findings,
            "likely_causes": self.likely_causes,
            "verification_steps": self.verification_steps,
            "safe_actions": self.safe_actions,
            "unsafe_actions": self.unsafe_actions,
            "supporting_signals": [
                {
                    "signal_type": s.signal_type,
                    "summary": s.summary,
                    "supporting_chunk_ids": s.supporting_chunk_ids,
                    "supporting_documents": s.supporting_documents,
                    "confidence": s.confidence,
                }
                for s in self.supporting_signals
            ],
            "retrieved_chunks": [
                {
                    "score": c.score,
                    "chunk_id": c.chunk_id,
                    "document_id": c.document_id,
                    "vendor": c.vendor,
                    "nos_family": c.nos_family,
                    "source_type": c.source_type,
                    "section_title": c.section_title,
                    "subsection_title": c.subsection_title,
                    "page_start": c.page_start,
                    "page_end": c.page_end,
                    "text": c.text,
                }
                for c in self.retrieved_chunks
            ],
            "confidence": self.confidence,
        }


class EvpnReasoner:
    def __init__(self, retriever: EvpnVxlanRetriever | None = None) -> None:
        self.retriever = retriever or EvpnVxlanRetriever()

    def reason(self, ctx: ProblemContext) -> ReasoningOutput:
        request = build_request(
            EvpnQuestion(
                question=ctx.question,
                vendor=ctx.vendor,
                nos_family=ctx.nos_family,
                scenario=ctx.scenario,
                capability=ctx.capability,
                feature=ctx.feature,
                role=ctx.role,
                limit=ctx.limit,
            )
        )

        request.safe_for_diagnosis = True
        request.safe_for_explanation = True
        request.safe_for_remediation = ctx.allow_remediation_guidance
        request.safe_for_capability_claim = ctx.allow_capability_claims

        chunks = self.retriever.retrieve(request)

        output = ReasoningOutput(
            vendor=ctx.vendor,
            nos_family=ctx.nos_family,
            scenario=ctx.scenario,
            capability=ctx.capability,
            feature=ctx.feature,
            question=ctx.question,
            retrieved_chunks=chunks,
        )

        if not chunks:
            output.findings.append("No matching EVPN VXLAN knowledge chunks were retrieved for this context.")
            output.confidence = "low"
            return output

        self._derive_findings(output, chunks, ctx)
        self._derive_likely_causes(output, chunks, ctx)
        self._derive_verification_steps(output, chunks, ctx)
        self._derive_actions(output, chunks, ctx)
        output.confidence = self._derive_confidence(chunks)

        return output

    def _derive_findings(self, output: ReasoningOutput, chunks: list[RetrievedChunk], ctx: ProblemContext) -> None:
        seen: set[str] = set()

        for chunk in chunks:
            tags = chunk.payload.get("tags", {})
            features = set(tags.get("features", []))
            route_types = set(tags.get("route_types", []))
            scenarios = set(tags.get("scenarios", []))

            if "mac_mobility" in features:
                self._append_signal(
                    output,
                    signal_type="feature_alignment",
                    summary="MAC mobility behavior is explicitly relevant in the retrieved vendor guidance.",
                    chunk=chunk,
                )

            if "duplicate_mac_detection" in features:
                self._append_signal(
                    output,
                    signal_type="feature_alignment",
                    summary="Duplicate MAC detection is explicitly relevant in the retrieved vendor guidance.",
                    chunk=chunk,
                )

            if "arp_suppression" in features:
                self._append_signal(
                    output,
                    signal_type="feature_alignment",
                    summary="ARP suppression behavior is explicitly described in the retrieved guidance.",
                    chunk=chunk,
                )

            if "anycast_gateway" in features:
                self._append_signal(
                    output,
                    signal_type="feature_alignment",
                    summary="Anycast gateway behavior is explicitly described in the retrieved guidance.",
                    chunk=chunk,
                )

            if "gateway" in features or "hierarchical_evpn" in features:
                self._append_signal(
                    output,
                    signal_type="topology_behavior",
                    summary="Hierarchical gateway and domain scoped EVPN behavior is relevant to this problem.",
                    chunk=chunk,
                )

            if "type2" in route_types and "type5" in route_types:
                self._append_signal(
                    output,
                    signal_type="route_semantics",
                    summary="Both Type 2 and Type 5 route semantics appear relevant in the retrieved material.",
                    chunk=chunk,
                )

            if ctx.scenario and ctx.scenario in scenarios:
                finding = f"Retrieved chunks align directly to scenario '{ctx.scenario}'."
                if finding not in seen:
                    output.findings.append(finding)
                    seen.add(finding)

        for signal in output.supporting_signals:
            if signal.summary not in seen:
                output.findings.append(signal.summary)
                seen.add(signal.summary)

    def _derive_likely_causes(self, output: ReasoningOutput, chunks: list[RetrievedChunk], ctx: ProblemContext) -> None:
        scenario = ctx.scenario or ""
        feature = ctx.feature or ""

        if scenario == "mac_mobility_analysis" or feature == "mac_mobility":
            output.likely_causes.extend(
                [
                    "A legitimate host move may be causing newer EVPN advertisements to replace older state.",
                    "Duplicate MAC detection or suppression may be preventing expected learning behavior.",
                    "Stale Type 2 state may still exist on one or more remote VTEPs.",
                ]
            )

        elif scenario == "arp_suppression_validation":
            output.likely_causes.extend(
                [
                    "ARP suppression may not have the expected EVPN MAC and IP bindings populated.",
                    "Local answering behavior may be bypassed when the target is unknown or stale.",
                    "Control plane learning may be incomplete or inconsistent across VTEPs.",
                ]
            )

        elif scenario == "anycast_gateway_validation":
            output.likely_causes.extend(
                [
                    "Distributed gateway configuration may be inconsistent across participating VTEPs.",
                    "Gateway MAC or VNI association may not be aligned across the EVPN domain.",
                    "Host mobility or route propagation timing may be exposing inconsistent gateway behavior.",
                ]
            )

        elif scenario == "dci_connectivity_analysis":
            output.likely_causes.extend(
                [
                    "Cross domain route propagation may be scoped or summarized in a way that hides expected reachability.",
                    "Gateway next hop rewriting across domains may be affecting end to end path interpretation.",
                    "BUM forwarding or flood domain boundaries may be limiting expected cross site behavior.",
                ]
            )

        elif scenario == "multihoming_design_selection":
            output.likely_causes.extend(
                [
                    "The current design may be mixing assumptions from MLAG and EVPN all active models.",
                    "Ethernet segment or designated forwarder behavior may not match the intended failover model.",
                    "Operational expectations may differ between shared VTEP and unique VTEP designs.",
                ]
            )

        else:
            output.likely_causes.extend(
                [
                    "Retrieved vendor guidance indicates EVPN control plane and VXLAN data plane alignment should be checked.",
                    "Topology scoping, route type interpretation, and local versus remote state should be verified together.",
                ]
            )

    def _derive_verification_steps(self, output: ReasoningOutput, chunks: list[RetrievedChunk], ctx: ProblemContext) -> None:
        scenario = ctx.scenario or ""

        common_steps = [
            "Inspect the retrieved chunk sections and confirm whether the relevant feature is described as control plane, data plane, or topology scoped behavior.",
            "Confirm that the vendor, NOS family, and scenario filters are aligned with the device or fabric under investigation.",
        ]

        if scenario == "mac_mobility_analysis":
            scenario_steps = [
                "Inspect MAC mobility related state and compare whether newer advertisements replaced older state.",
                "Check duplicate MAC detection or suppression behavior before assuming a forwarding defect.",
                "Compare Type 2 route state across participating VTEPs if available.",
            ]
        elif scenario == "arp_suppression_validation":
            scenario_steps = [
                "Verify that EVPN learned MAC and IP bindings exist for the expected endpoint.",
                "Check whether local answering behavior is expected for the target endpoint.",
                "Compare ARP behavior against the EVPN database rather than only packet symptoms.",
            ]
        elif scenario == "anycast_gateway_validation":
            scenario_steps = [
                "Validate that distributed gateway behavior is intended across all participating VTEPs in the VNI.",
                "Confirm that the gateway identity and VNI association are consistent across the fabric.",
                "Check whether the issue is tied to mobility timing or stale remote state.",
            ]
        elif scenario == "dci_connectivity_analysis":
            scenario_steps = [
                "Verify whether the design expects domain scoped route advertisement rather than flat end to end EVPN visibility.",
                "Check gateway next hop rewriting and route propagation between local and remote domains.",
                "Confirm whether the interconnect model is VXLAN to VXLAN or VXLAN to MPLS.",
            ]
        elif scenario == "multihoming_design_selection":
            scenario_steps = [
                "Identify whether the design is MLAG based or EVPN all active based before interpreting failover behavior.",
                "Inspect Ethernet segment and designated forwarder semantics where applicable.",
                "Validate whether downstream redundancy expectations match the chosen model.",
            ]
        else:
            scenario_steps = [
                "Check route type relevance, VTEP reachability, and local versus remote state interpretation.",
                "Confirm whether the retrieved guidance emphasizes route propagation, flooding scope, or gateway behavior.",
            ]

        output.verification_steps.extend(common_steps + scenario_steps)

    def _derive_actions(self, output: ReasoningOutput, chunks: list[RetrievedChunk], ctx: ProblemContext) -> None:
        output.safe_actions.extend(
            [
                "Retrieve additional read only EVPN state for the same vendor and scenario.",
                "Compare multiple retrieved chunks across design guidance and troubleshooting guidance.",
                "Use the retrieved evidence to drive read only MCP inspections before suggesting changes.",
            ]
        )

        output.unsafe_actions.extend(
            [
                "Do not infer write level capability solely from RAG results.",
                "Do not perform remediation that changes EVPN policy, gateway behavior, or route propagation without separate capability and risk checks.",
            ]
        )

        if ctx.allow_remediation_guidance:
            output.safe_actions.append(
                "Only provide remediation suggestions when a separate policy layer confirms safe_for_remediation and capability support."
            )

        if not ctx.allow_capability_claims:
            output.unsafe_actions.append(
                "Do not claim production write support from these chunks alone."
            )

    def _derive_confidence(self, chunks: list[RetrievedChunk]) -> str:
        if not chunks:
            return "low"
        best = max(c.score for c in chunks)
        if best >= 0.75:
            return "high"
        if best >= 0.55:
            return "medium"
        return "low"

    def _append_signal(self, output: ReasoningOutput, signal_type: str, summary: str, chunk: RetrievedChunk) -> None:
        for existing in output.supporting_signals:
            if existing.summary == summary:
                if chunk.chunk_id not in existing.supporting_chunk_ids:
                    existing.supporting_chunk_ids.append(chunk.chunk_id)
                if chunk.document_id not in existing.supporting_documents:
                    existing.supporting_documents.append(chunk.document_id)
                return

        output.supporting_signals.append(
            ReasoningSignal(
                signal_type=signal_type,
                summary=summary,
                supporting_chunk_ids=[chunk.chunk_id],
                supporting_documents=[chunk.document_id],
                confidence="medium",
            )
        )


def pretty_print_reasoning(result: ReasoningOutput) -> None:
    print("=" * 120)
    print("EVPN REASONING OUTPUT")
    print("=" * 120)
    print(f"Vendor      : {result.vendor}")
    print(f"NOS         : {result.nos_family}")
    print(f"Scenario    : {result.scenario}")
    print(f"Capability  : {result.capability}")
    print(f"Feature     : {result.feature}")
    print(f"Confidence  : {result.confidence}")
    print(f"Question    : {result.question}")
    print()

    print("Findings:")
    for item in result.findings:
        print(f"  - {item}")
    print()

    print("Likely causes:")
    for item in result.likely_causes:
        print(f"  - {item}")
    print()

    print("Verification steps:")
    for item in result.verification_steps:
        print(f"  - {item}")
    print()

    print("Safe actions:")
    for item in result.safe_actions:
        print(f"  - {item}")
    print()

    print("Unsafe actions:")
    for item in result.unsafe_actions:
        print(f"  - {item}")
    print()

    print("Supporting signals:")
    for signal in result.supporting_signals:
        print(f"  - [{signal.signal_type}] {signal.summary}")
        print(f"    chunk_ids   : {', '.join(signal.supporting_chunk_ids)}")
        print(f"    documents   : {', '.join(signal.supporting_documents)}")
    print()

    print("Retrieved chunks:")
    for idx, chunk in enumerate(result.retrieved_chunks, start=1):
        print(f"  {idx}. {chunk.document_id} | score={chunk.score:.4f} | pages={chunk.page_start}-{chunk.page_end}")
        if chunk.section_title:
            print(f"     section    : {chunk.section_title}")
        if chunk.subsection_title:
            print(f"     subsection : {chunk.subsection_title}")
        print(f"     text       : {chunk.text}")
        print()
